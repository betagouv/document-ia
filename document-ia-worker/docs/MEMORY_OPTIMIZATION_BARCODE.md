# Worker Memory Optimization & Barcode Extraction Resilience

## Overview
This document specifies the memory resilience architecture and algorithmic optimizations implemented in `document-ia-worker` to prevent Out-Of-Memory (OOM) crashes in memory-constrained container environments (e.g., Scalingo Linux containers with 2 GB RAM and concurrency `REDIS_WORKER_NUMBER=8`).

---

## 1. The OOM Bottleneck in 2D-Doc & Barcode Detection

Under multi-worker concurrency, the barcode extraction step (`ExtractBarcode2DDocData`) historically triggered OOM kills due to four compounding factors:
1. **Unconstrained Image Decompression (`cv2.imread`)**: High-resolution smartphone uploads (up to 25 MB file size or 48–100 Megapixels) decompress into 150 MB to 300 MB raw BGR NumPy arrays per page.
2. **Concurrent Image Ingestion**: Multiple worker threads concurrently read full-resolution images outside the critical section lock.
3. **QRDet PyTorch Peak Footprint**: When no 2D-Doc is initially decoded by `zxingcpp`, the fallback `QRDetector` (YOLOv8-segmentation) requires a peak of ~265 MB RAM on 12 MP images.
4. **Blind Crop Upscaling**: Candidacy crops extracted by QRDet were systematically upscaled by factors of 2x and 3x (`cv2.INTER_CUBIC`), multiplying pixel surface area by up to 9x, even for crops that were already large enough to decode.
5. **Glibc Fragmentation**: Released C/C++ memory pools (PyTorch, OpenCV, MuPDF) were not actively returned to the Linux OS kernel without explicit trim signals.

---

## 2. Architectural Mitigations

### 2.1. Global Serialized Image Processing Lock (`_BARCODE_LOCK`)
All barcode extraction steps (`ExtractBarcode2DDocData`, `ExtractBarcodeRawData`, and `ExtractBarcodeData`) serialize image reading, downsampling, and detection under a single process-wide lock (`_BARCODE_LOCK`). This guarantees:
- Exactly **one** heavy image is decompressed into uncompressed RAM at any given time across all worker threads.
- Total processing time under lock is brief (50 ms – 350 ms), preserving parallel execution for I/O-bound steps (S3 transfers, HTTP OCR, LLM inference).
- Any job aborted by the watchdog exits early before acquiring the barcode processing lock.

### 2.2. Intelligent Pre-Inference Downsampling
Before submitting images to barcode scanning or QRDet inference, the image dimensions are inspected:
- **Maximum Long Edge Threshold**: `MAX_BARCODE_IMAGE_DIM = 2400 px`.
- If $\max(\text{width}, \text{height}) > 2400\text{ px}$, the image is immediately resized using area interpolation (`cv2.INTER_AREA`).
- The original unscaled matrix is immediately deallocated (`del`).
- Detected coordinates are automatically reprojected back to the original document's coordinate space.
- *Impact*: Reduces raw image memory by over **90%** (e.g. from 144 MB down to ~16 MB) while keeping 2D-Doc / QR code features at 150–250 px, which is optimal for ZXing-cpp and YOLOv8.

### 2.3. Adaptive Crop Decoding & Memory Deallocation
Candidate crops extracted by QRDet are copied (`.copy()`) to detach NumPy array views from full-page buffers, allowing the full-page image and QRDet detection masks to be freed immediately before crop decoding:
- **Pass 1 (Native 1x)**: Always test native 1x resolution on the isolated crop first (0 allocation, eliminates cubic interpolation ringing on sharp DataMatrix modules).
- **Pass 2 (Conditional 2x Upscale)**: For crops with $\max(\text{crop\_width}, \text{crop\_height}) \le 250\text{ px}$, upscale 2x (`cv2.INTER_CUBIC`), scan, and deallocate immediately (`del image_scaled_2x`).
- **Pass 3 (3x Upscale)**: If still undetected, upscale 3x, scan, and deallocate immediately (`del image_scaled_3x`).
- **Pass 4 (Border Fallback)**: If crop boundaries clip the quiet zone, add a 15% white margin and test 2x / 3x upscales with immediate deallocation.

### 2.4. Explicit Cleanup & Linux `malloc_trim(0)`
1. Local variables holding large matrices (`img`, `detections`, `rois`, `crop`) are explicitly cleared using `del` in `finally` blocks.
2. At the end of workflow execution in `WorkflowManager`, `workflow_context.clear()` and `step_list.clear()` are executed **before** calling `gc.collect()` and `malloc_trim(0)`:
   ```python
   def _release_worker_memory() -> None:
       gc.collect()
       if _LIBC is not None:
           try:
               _LIBC.malloc_trim(0)
           except Exception:
               pass
   ```
3. A final cleanup pass in `WorkflowManager.start()` clears `self.main_workflow_context = None` and reclaims SQLAlchemy session and aggregate log memory.
   > [!IMPORTANT]
   > `malloc_trim(0)` reclaims fragmented heap memory back to the Linux kernel without unloading cached PyTorch models or Python singletons (`_qrdet_detector`, `YOLO-World`). Reload delay is **zero seconds**.

### 2.5. Bounded Loki Log Queue & HTTP Timeout
The Loki queue handler (`document-ia-infra/core/loki_settings.py`) enforces a bounded queue `Queue(maxsize=1000)` along with an enforced default HTTP timeout (`DEFAULT_LOKI_TIMEOUT_S = 5.0`). When remote log endpoints experience network latency or outages, excess records bypass expensive formatting and are discarded safely without blocking the application.

---

## 3. Configuration Reference

| Environment / Setting | Default | Description |
| :--- | :--- | :--- |
| `MAX_BARCODE_IMAGE_DIM` | `2400` | Max long edge (px) for whole-page barcode scanning |
| `MAX_CROP_DIM_FOR_UPSCALE` | `250` | Max crop dimension (px) eligible for 2x/3x upscaling |
| `REDIS_WORKER_NUMBER` | `8` | Number of concurrent workflow threads in ThreadConsumer |
| `MALLOC_ARENA_MAX` | `2` | Glibc arena limit to reduce virtual memory fragmentation |
