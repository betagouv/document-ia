#!/usr/bin/env python3
"""
Benchmark utility: Compare Barcode / 2D-Doc detection performance and memory footprint
between the legacy implementation and the new optimized memory implementation.

Usage:
    # Running on an existing directory of images:
    uv run python scripts/benchmark_barcode_detection.py --dataset-dir /path/to/images

    # Downloading from Roboflow Universe and running:
    uv run python scripts/benchmark_barcode_detection.py --roboflow-api-key YOUR_KEY

    # Running with limit on number of images:
    uv run python scripts/benchmark_barcode_detection.py --dataset-dir ./data/grandav-datamatrix --limit 50
"""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import gc
import json
import logging
import multiprocessing as mp
import os
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

import cv2
import numpy as np
import psutil
import zxingcpp
from numpy.typing import NDArray

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("benchmark_barcode")

ImageArray = NDArray[np.uint8]


# ==============================================================================
# Data Structures
# ==============================================================================


@dataclass
class DetectionResult:
    filename: str
    num_ants_2ddoc: int
    num_datamatrix: int
    num_qrcode: int
    total_detected: int
    execution_time_s: float
    is_success: bool
    error: str | None = None


@dataclass
class VersionBenchmarkSummary:
    version_name: str
    total_images: int
    successful_images: int
    total_codes_detected: int
    total_ants_2ddoc: int
    total_datamatrix: int
    total_qrcode: int
    detection_rate_pct: float
    baseline_ram_mb: float
    peak_ram_mb: float
    final_ram_mb: float
    ram_growth_mb: float
    total_time_s: float
    avg_time_per_image_s: float
    results_per_image: list[dict[str, Any]]


# ==============================================================================
# Memory Monitor
# ==============================================================================


class MemorySampler(threading.Thread):
    """High-frequency background thread sampling process RSS memory."""

    def __init__(self, interval_s: float = 0.01):
        super().__init__(daemon=True)
        self.interval_s = interval_s
        self.stop_event = threading.Event()
        self.process = psutil.Process(os.getpid())
        self.peak_rss_bytes = self.process.memory_info().rss
        self.samples: list[float] = []

    def run(self) -> None:
        while not self.stop_event.is_set():
            with contextlib.suppress(Exception):
                rss = self.process.memory_info().rss
                self.peak_rss_bytes = max(self.peak_rss_bytes, rss)
                self.samples.append(rss / (1024 * 1024))
            time.sleep(self.interval_s)

    def stop(self) -> tuple[float, float]:
        self.stop_event.set()
        final_rss_mb = self.process.memory_info().rss / (1024 * 1024)
        peak_rss_mb = self.peak_rss_bytes / (1024 * 1024)
        return peak_rss_mb, final_rss_mb


# ==============================================================================
# Helper Functions (Crop, Border, Upscale)
# ==============================================================================


def _add_white_border(img: ImageArray, border_ratio: float = 0.15) -> ImageArray:
    if border_ratio <= 0:
        return img
    height, width = img.shape[:2]
    pad = int(min(height, width) * border_ratio)
    if pad <= 0:
        return img
    bordered = cv2.copyMakeBorder(
        img, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=(255, 255, 255)
    )
    return cast(ImageArray, bordered)


def _upscale_crop(img: ImageArray, scale: int = 2) -> ImageArray:
    if scale <= 1:
        return img
    height, width = img.shape[:2]
    resized = cv2.resize(
        img, (width * scale, height * scale), interpolation=cv2.INTER_CUBIC
    )
    return cast(ImageArray, resized)


def _iter_crops(img: ImageArray, detections: list[Any]) -> list[ImageArray]:
    crops: list[ImageArray] = []
    height, width = img.shape[:2]
    for det in detections:
        bbox = det.get("bbox_xyxy")
        if bbox is None:
            continue
        if isinstance(bbox, np.ndarray):
            if bbox.size != 4:
                continue
            bbox_list = cast(list[float], bbox.tolist())
        else:
            if len(bbox) != 4:
                continue
            bbox_list = bbox
        x1, y1, x2, y2 = map(int, bbox_list)
        pad = int(min(x2 - x1, y2 - y1) * 0.02)
        x1, y1 = max(0, x1 - pad), max(0, y1 - pad)
        x2, y2 = min(width, x2 + pad), min(height, y2 + pad)
        if x2 <= x1 or y2 <= y1:
            continue
        crop = img[y1:y2, x1:x2]
        crop = _add_white_border(crop, border_ratio=0.25)
        crops.append(crop)
    return crops


def _classify_barcode(barcode: Any) -> str:
    """Classify decoded barcode into Ants2DDoc, DataMatrix or QRCode."""
    format_name = getattr(barcode.format, "name", str(barcode.format))
    if format_name in ("DataMatrix", "BarcodeFormat.DataMatrix", "Data Matrix"):
        text = str(barcode.text)
        # Check if ANTS 2D-Doc header
        if text.startswith("DC") or (len(text) > 4 and text[0:2] in ("01", "02")):
            with contextlib.suppress(Exception):
                from fr_2ddoc_parser.api import decode_2d_doc

                res = decode_2d_doc(text)
                if res and res.is_valid:
                    return "ants_2ddoc"
        return "datamatrix"
    if format_name in ("QRCode", "BarcodeFormat.QRCode", "QR Code"):
        return "qrcode"
    return "other"


# ==============================================================================
# Model Loader
# ==============================================================================

_QR_DETECTOR = None


def get_detector() -> Any:
    global _QR_DETECTOR
    if _QR_DETECTOR is None:
        from qrdet import QRDetector

        weights_dir = os.environ.get("QRDET_WEIGHTS_DIR")
        if not weights_dir:
            default_weights = (
                Path(__file__).resolve().parent.parent
                / "document-ia-worker"
                / ".models"
                / "qrdet"
            )
            if default_weights.exists():
                weights_dir = str(default_weights)
        if weights_dir and os.path.exists(weights_dir):
            _QR_DETECTOR = QRDetector(model_size="s", weights_folder=weights_dir)
        else:
            _QR_DETECTOR = QRDetector(model_size="s")
    return _QR_DETECTOR


# ==============================================================================
# Pipeline 1 : Legacy Implementation (Old Version)
# ==============================================================================


def process_image_legacy(file_path: str) -> DetectionResult:
    """
    Old version logic:
    - cv2.imread full resolution (no downscaling).
    - ZXing on raw image.
    - If no 2D-Doc: QRDet fallback.
    - Systematically upscales all crops by 2x then 3x cubic interpolation.
    - No explicit buffer deallocation or malloc_trim.
    """
    start_t = time.perf_counter()
    fname = Path(file_path).name
    try:
        img_raw = cv2.imread(file_path)
        if img_raw is None:
            return DetectionResult(fname, 0, 0, 0, 0, 0.0, False, "Cannot read image")

        target_formats = zxingcpp.barcode_formats_from_str("DataMatrix|QRCode")
        barcodes = zxingcpp.read_barcodes(img_raw, formats=target_formats)

        ants_count = 0
        dm_count = 0
        qr_count = 0
        seen_keys = set()

        for b in barcodes:
            k = f"{b.format}:{b.text}"
            if k in seen_keys:
                continue
            seen_keys.add(k)
            c = _classify_barcode(b)
            if c == "ants_2ddoc":
                ants_count += 1
            elif c == "datamatrix":
                dm_count += 1
            elif c == "qrcode":
                qr_count += 1

        # Legacy fallback logic: if no ANTS 2D-Doc found, run QRDet
        if ants_count == 0:
            detector = get_detector()
            try:
                detections = detector.detect(image=img_raw, is_bgr=True)
            except Exception as e:  # noqa: BLE001
                logger.debug("QRDet detection error: %s", e)
                detections = []

            rois = _iter_crops(img_raw, detections)
            for crop in rois:
                # Legacy: Always upscale 2x
                crop_scaled_2x = _upscale_crop(crop, scale=2)
                crop_barcodes = zxingcpp.read_barcodes(
                    crop_scaled_2x, formats=target_formats
                )
                has_dm = any(
                    getattr(b.format, "name", str(b.format))
                    in ("DataMatrix", "BarcodeFormat.DataMatrix", "Data Matrix")
                    for b in crop_barcodes
                )
                if not has_dm:
                    # Legacy: Always upscale 3x as last chance
                    crop_scaled_3x = _upscale_crop(crop, scale=3)
                    crop_barcodes = zxingcpp.read_barcodes(
                        crop_scaled_3x, formats=target_formats
                    )

                for b in crop_barcodes:
                    k = f"{b.format}:{b.text}"
                    if k in seen_keys:
                        continue
                    seen_keys.add(k)
                    c = _classify_barcode(b)
                    if c == "ants_2ddoc":
                        ants_count += 1
                    elif c == "datamatrix":
                        dm_count += 1
                    elif c == "qrcode":
                        qr_count += 1

        total = ants_count + dm_count + qr_count
        duration = time.perf_counter() - start_t
        return DetectionResult(
            fname, ants_count, dm_count, qr_count, total, duration, True
        )
    except Exception as exc:  # noqa: BLE001
        duration = time.perf_counter() - start_t
        return DetectionResult(fname, 0, 0, 0, 0, duration, False, str(exc))


# ==============================================================================
# Pipeline 2 : Optimized Implementation (New Version)
# ==============================================================================

_NEW_BARCODE_LOCK = threading.Lock()
MAX_BARCODE_IMAGE_DIM = 2048
MAX_CROP_DIM_FOR_UPSCALE = 250


def process_image_optimized(file_path: str) -> DetectionResult:
    """
    New version logic:
    - Global lock on heavy image decompression.
    - Intelligent downscale to max 2048px before processing.
    - ZXing on downscaled image.
    - If no 2D-Doc: QRDet fallback.
    - Conditional crop upscaling: skip 2x/3x if crop max dim > 250px.
    - Explicit deallocation (del) + gc.collect() + malloc_trim(0).
    """
    start_t = time.perf_counter()
    fname = Path(file_path).name
    img = None
    img_raw = None
    rois: list[Any] = []

    try:
        with _NEW_BARCODE_LOCK:
            img_raw = cv2.imread(file_path)
            if img_raw is None:
                return DetectionResult(
                    fname, 0, 0, 0, 0, 0.0, False, "Cannot read image"
                )

            h, w = img_raw.shape[:2]
            max_dim = max(h, w)
            if max_dim > MAX_BARCODE_IMAGE_DIM:
                scale = MAX_BARCODE_IMAGE_DIM / max_dim
                new_w = round(w * scale)
                new_h = round(h * scale)
                img = cast(
                    ImageArray,
                    cv2.resize(img_raw, (new_w, new_h), interpolation=cv2.INTER_AREA),
                )
                img_raw = None  # Free original high-res matrix immediately
            else:
                img = cast(ImageArray, img_raw)

            target_formats = zxingcpp.barcode_formats_from_str("DataMatrix|QRCode")
            barcodes = zxingcpp.read_barcodes(img, formats=target_formats)

            ants_count = 0
            dm_count = 0
            qr_count = 0
            seen_keys = set()

            for b in barcodes:
                k = f"{b.format}:{b.text}"
                if k in seen_keys:
                    continue
                seen_keys.add(k)
                c = _classify_barcode(b)
                if c == "ants_2ddoc":
                    ants_count += 1
                elif c == "datamatrix":
                    dm_count += 1
                elif c == "qrcode":
                    qr_count += 1

            if ants_count == 0:
                detector = get_detector()
                try:
                    detections = detector.detect(image=img, is_bgr=True)
                except Exception as e:  # noqa: BLE001
                    logger.debug("QRDet detection error: %s", e)
                    detections = []

                rois = _iter_crops(img, detections)
                for crop in rois:
                    ch, cw = crop.shape[:2]
                    crop_dim = max(ch, cw)

                    # Conditional crop upscaling
                    if crop_dim > MAX_CROP_DIM_FOR_UPSCALE:
                        crop_barcodes = zxingcpp.read_barcodes(
                            crop, formats=target_formats
                        )
                    else:
                        crop_scaled = _upscale_crop(crop, scale=2)
                        try:
                            crop_barcodes = zxingcpp.read_barcodes(
                                crop_scaled, formats=target_formats
                            )
                            has_dm = any(
                                getattr(b.format, "name", str(b.format))
                                in (
                                    "DataMatrix",
                                    "BarcodeFormat.DataMatrix",
                                    "Data Matrix",
                                )
                                for b in crop_barcodes
                            )
                            if not has_dm:
                                crop_scaled_3x = _upscale_crop(crop, scale=3)
                                try:
                                    crop_barcodes = zxingcpp.read_barcodes(
                                        crop_scaled_3x, formats=target_formats
                                    )
                                finally:
                                    del crop_scaled_3x
                        finally:
                            del crop_scaled

                    for b in crop_barcodes:
                        k = f"{b.format}:{b.text}"
                        if k in seen_keys:
                            continue
                        seen_keys.add(k)
                        c = _classify_barcode(b)
                        if c == "ants_2ddoc":
                            ants_count += 1
                        elif c == "datamatrix":
                            dm_count += 1
                        elif c == "qrcode":
                            qr_count += 1

            total = ants_count + dm_count + qr_count
            duration = time.perf_counter() - start_t
            return DetectionResult(
                fname, ants_count, dm_count, qr_count, total, duration, True
            )
    except Exception as exc:  # noqa: BLE001
        duration = time.perf_counter() - start_t
        return DetectionResult(fname, 0, 0, 0, 0, duration, False, str(exc))
    finally:
        del img
        del img_raw
        del rois
        gc.collect()
        if sys.platform.startswith("linux"):
            with contextlib.suppress(Exception):
                ctypes.CDLL("libc.so.6").malloc_trim(0)


# ==============================================================================
# Isolated Runner (Subprocess per version to avoid memory contamination)
# ==============================================================================


def _worker_process_entrypoint(
    version_name: str,
    process_func_name: str,
    image_paths: list[str],
    queue: mp.Queue[Any],
) -> None:
    func: Callable[[str], DetectionResult]
    if process_func_name == "legacy":
        func = process_image_legacy
    else:
        func = process_image_optimized

    proc = psutil.Process(os.getpid())
    # Baseline before loading any model
    proc.memory_info().rss / (1024 * 1024)

    # Pre-warm detector once inside the process
    _ = get_detector()
    warm_baseline_mb = proc.memory_info().rss / (1024 * 1024)

    sampler = MemorySampler(interval_s=0.01)
    sampler.start()

    start_total_t = time.perf_counter()
    results: list[DetectionResult] = []

    for idx, img_path in enumerate(image_paths, 1):
        res = func(img_path)
        results.append(res)
        if idx % 10 == 0 or idx == len(image_paths):
            logger.info(
                f"[{version_name}] Processed {idx}/{len(image_paths)} images (detected={res.total_detected}, time={res.execution_time_s:.2f}s)"
            )

    total_duration = time.perf_counter() - start_total_t
    peak_mb, _final_mb = sampler.stop()

    # Extra GC & trim at process exit
    gc.collect()
    if sys.platform.startswith("linux"):
        with contextlib.suppress(Exception):
            ctypes.CDLL("libc.so.6").malloc_trim(0)
    post_trim_final_mb = proc.memory_info().rss / (1024 * 1024)

    total_images = len(results)
    successful = sum(1 for r in results if r.is_success)
    total_detected = sum(r.total_detected for r in results)
    total_ants = sum(r.num_ants_2ddoc for r in results)
    total_dm = sum(r.num_datamatrix for r in results)
    total_qr = sum(r.num_qrcode for r in results)
    images_with_codes = sum(1 for r in results if r.total_detected > 0)
    det_rate = (images_with_codes / total_images * 100) if total_images > 0 else 0.0
    avg_time = total_duration / total_images if total_images > 0 else 0.0

    summary = VersionBenchmarkSummary(
        version_name=version_name,
        total_images=total_images,
        successful_images=successful,
        total_codes_detected=total_detected,
        total_ants_2ddoc=total_ants,
        total_datamatrix=total_dm,
        total_qrcode=total_qr,
        detection_rate_pct=round(det_rate, 2),
        baseline_ram_mb=round(warm_baseline_mb, 1),
        peak_ram_mb=round(peak_mb, 1),
        final_ram_mb=round(post_trim_final_mb, 1),
        ram_growth_mb=round(post_trim_final_mb - warm_baseline_mb, 1),
        total_time_s=round(total_duration, 2),
        avg_time_per_image_s=round(avg_time, 3),
        results_per_image=[asdict(r) for r in results],
    )
    queue.put(asdict(summary))


def run_isolated_benchmark(
    version_name: str,
    process_func_name: str,
    image_paths: list[str],
) -> VersionBenchmarkSummary:
    logger.info(
        f"--- Starting Benchmark: {version_name} ({len(image_paths)} images) ---"
    )
    ctx = mp.get_context("spawn")
    queue: mp.Queue[Any] = ctx.Queue()
    p = ctx.Process(
        target=_worker_process_entrypoint,
        args=(version_name, process_func_name, image_paths, queue),
    )
    p.start()
    p.join(timeout=1800)  # 30 minutes timeout
    if p.is_alive():
        p.terminate()
        raise TimeoutError(f"Benchmark {version_name} timed out")

    if queue.empty():
        raise RuntimeError(
            f"Process for {version_name} exited without returning results"
        )
    data = queue.get()
    return VersionBenchmarkSummary(**data)


# ==============================================================================
# Roboflow Dataset Downloader
# ==============================================================================


def download_roboflow_dataset(
    api_key: str,
    workspace: str = "stemmasmoke",
    project_name: str = "grandav-datamatrix",
    target_dir: str = "./data/grandav-datamatrix",
) -> Path:
    """Download the dataset from Roboflow Universe using official SDK."""
    try:
        from roboflow import Roboflow
    except ImportError:
        logger.error(
            "Package 'roboflow' is not installed. Run: uv pip install roboflow"
        )
        sys.exit(1)

    target_path = Path(target_dir)
    if target_path.exists() and any(target_path.rglob("*.jpg")):
        logger.info(f"Dataset already exists in {target_path}. Using existing files.")
        return target_path

    logger.info(f"Downloading Roboflow dataset '{workspace}/{project_name}' via API...")
    rf = Roboflow(api_key=api_key)
    project = rf.workspace(workspace).project(project_name)
    version = project.version(1)
    dataset = version.download("yolov8", location=str(target_path))
    logger.info(f"Dataset downloaded successfully to: {dataset.location}")
    return Path(dataset.location)


def collect_images_from_directory(dir_path: Path) -> list[str]:
    extensions = ("*.jpg", "*.jpeg", "*.png", "*.bmp", "*.webp")
    images: list[str] = []
    for ext in extensions:
        images.extend(str(p) for p in dir_path.rglob(ext))
        images.extend(str(p) for p in dir_path.rglob(ext.upper()))
    # Sort for deterministic order across runs
    return sorted(set(images))


# ==============================================================================
# Reporting & Comparison
# ==============================================================================


def generate_comparison_table(
    old: VersionBenchmarkSummary, new: VersionBenchmarkSummary
) -> str:
    peak_diff_mb = new.peak_ram_mb - old.peak_ram_mb
    peak_pct = (
        ((new.peak_ram_mb - old.peak_ram_mb) / old.peak_ram_mb * 100)
        if old.peak_ram_mb > 0
        else 0
    )
    time_diff_s = new.total_time_s - old.total_time_s
    time_pct = (
        ((new.total_time_s - old.total_time_s) / old.total_time_s * 100)
        if old.total_time_s > 0
        else 0
    )

    table = rf"""
# 📊 Barcode & 2D-Doc Detection Benchmark Report

| Métrique | Ancienne Version (Old / Develop) | Nouvelle Version (New / Optimized) | Évolution (Diff) |
| :--- | :---: | :---: | :---: |
| **Total Images testées** | {old.total_images} | {new.total_images} | = |
| **Images décodées avec succès** | {old.successful_images} | {new.successful_images} | = |
| **Total Codes Détectés** | **{old.total_codes_detected}** | **{new.total_codes_detected}** | **{new.total_codes_detected - old.total_codes_detected:+d}** |
| ├─ 2D-Doc ANTS | {old.total_ants_2ddoc} | {new.total_ants_2ddoc} | {new.total_ants_2ddoc - old.total_ants_2ddoc:+d} |
| ├─ DataMatrix | {old.total_datamatrix} | {new.total_datamatrix} | {new.total_datamatrix - old.total_datamatrix:+d} |
| └─ QR Codes | {old.total_qrcode} | {new.total_qrcode} | {new.total_qrcode - old.total_qrcode:+d} |
| **Taux de détection (%)** | {old.detection_rate_pct}% | {new.detection_rate_pct}% | {new.detection_rate_pct - old.detection_rate_pct:+.2f}% |
| **RAM Baseline (Idle)** | {old.baseline_ram_mb} Mo | {new.baseline_ram_mb} Mo | {new.baseline_ram_mb - old.baseline_ram_mb:+.1f} Mo |
| **⚡ PIC MÉMOIRE (Peak RSS)** | **{old.peak_ram_mb} Mo** | **{new.peak_ram_mb} Mo** | **{peak_diff_mb:+.1f} Mo ({peak_pct:+.1f}%)** |
| **RAM Finale (Post-trim)** | {old.final_ram_mb} Mo | {new.final_ram_mb} Mo | {new.final_ram_mb - old.final_ram_mb:+.1f} Mo |
| **Dérive RAM ($\Delta$ Final - Base)** | {old.ram_growth_mb:+.1f} Mo | {new.ram_growth_mb:+.1f} Mo | {new.ram_growth_mb - old.ram_growth_mb:+.1f} Mo |
| **Temps Total d'exécution** | {old.total_time_s:.2f} s | {new.total_time_s:.2f} s | {time_diff_s:+.2f} s ({time_pct:+.1f}%) |
| **Temps Moyen par Image** | {old.avg_time_per_image_s:.3f} s | {new.avg_time_per_image_s:.3f} s | {new.avg_time_per_image_s - old.avg_time_per_image_s:+.3f} s |
"""
    return table


# ==============================================================================
# Main Entry Point
# ==============================================================================


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark barcode extraction (Old vs New implementation)"
    )
    parser.add_argument(
        "--dataset-dir",
        type=str,
        default=None,
        help="Path to directory containing test images",
    )
    parser.add_argument(
        "--roboflow-api-key",
        type=str,
        default=os.environ.get("ROBOFLOW_API_KEY"),
        help="Roboflow API key to download dataset automatically",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum number of images to benchmark (default: 100)",
    )
    parser.add_argument(
        "--mode",
        choices=["both", "old", "new"],
        default="both",
        help="Benchmark mode: both (default), old, or new",
    )
    parser.add_argument(
        "--output-json",
        type=str,
        default="benchmark_results.json",
        help="File path to save JSON results",
    )
    args = parser.parse_args()

    # Step 1 : Resolve images
    images_dir: Path | None = None
    if args.dataset_dir:
        images_dir = Path(args.dataset_dir)
        if not images_dir.exists():
            logger.error(f"Dataset directory not found: {images_dir}")
            sys.exit(1)
    elif args.roboflow_api_key:
        images_dir = download_roboflow_dataset(api_key=args.roboflow_api_key)
    else:
        logger.error(
            "Please provide either --dataset-dir <path> or --roboflow-api-key <key>."
        )
        logger.info(
            "Example: uv run python scripts/benchmark_barcode_detection.py --dataset-dir ./data/grandav-datamatrix"
        )
        sys.exit(1)

    all_images = collect_images_from_directory(images_dir)
    if not all_images:
        logger.error(f"No images found in {images_dir}")
        sys.exit(1)

    selected_images = all_images[: args.limit]
    logger.info(
        f"Selected {len(selected_images)} images (out of {len(all_images)} available) for benchmark."
    )

    old_summary: VersionBenchmarkSummary | None = None
    new_summary: VersionBenchmarkSummary | None = None

    if args.mode in ("both", "old"):
        old_summary = run_isolated_benchmark(
            version_name="Old Version (develop)",
            process_func_name="legacy",
            image_paths=selected_images,
        )

    if args.mode in ("both", "new"):
        new_summary = run_isolated_benchmark(
            version_name="New Version (optimized)",
            process_func_name="optimized",
            image_paths=selected_images,
        )

    # Print results
    print("\n" + "=" * 80)
    if old_summary and new_summary:
        table = generate_comparison_table(old_summary, new_summary)
        print(table)
    elif old_summary:
        print(f"Old Version Peak RAM: {old_summary.peak_ram_mb} MB")
        print(f"Old Version Codes: {old_summary.total_codes_detected}")
    elif new_summary:
        print(f"New Version Peak RAM: {new_summary.peak_ram_mb} MB")
        print(f"New Version Codes: {new_summary.total_codes_detected}")
    print("=" * 80 + "\n")

    # Export JSON
    output_data = {
        "old": asdict(old_summary) if old_summary else None,
        "new": asdict(new_summary) if new_summary else None,
    }
    with open(args.output_json, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    logger.info(f"Detailed benchmark results saved to {args.output_json}")


if __name__ == "__main__":
    main()
