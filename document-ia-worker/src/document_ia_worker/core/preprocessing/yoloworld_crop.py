import math
import os
import threading
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Optional

from PIL import Image


YOLO_WORLD_MODEL = "yolov8m-world.pt"
_YOLO_LOCK = threading.Lock()


@dataclass(frozen=True)
class DetectionBox:
    x1: float
    y1: float
    x2: float
    y2: float
    confidence: float


_MODEL_CACHE: Any = None


def get_yoloworld_model() -> Any:
    global _MODEL_CACHE
    if _MODEL_CACHE is None:
        from ultralytics import YOLOWorld

        model_path = os.environ.get("YOLOWORLD_PATH", YOLO_WORLD_MODEL)
        _MODEL_CACHE = YOLOWorld(model_path)
    return _MODEL_CACHE


def detect_boxes(
    image: Image.Image,
    *,
    class_name: str,
    confidence_threshold: float,
    image_size: Optional[int] = None,
) -> list[DetectionBox]:
    predict_kwargs: dict[str, Any] = {"verbose": False}
    predict_kwargs["device"] = "cpu"
    if image_size is not None:
        predict_kwargs["imgsz"] = image_size

    with _YOLO_LOCK:
        yolo_model = get_yoloworld_model()
        yolo_model.set_classes([class_name])
        results = yolo_model.predict(image, **predict_kwargs)

    if not results:
        return []

    boxes = getattr(results[0], "boxes", None)
    if boxes is None:
        return []

    xyxy_values = _to_list(getattr(boxes, "xyxy", []))
    confidence_values = _to_list(getattr(boxes, "conf", []))

    detections: list[DetectionBox] = []
    for coordinates, confidence in zip(xyxy_values, confidence_values):
        if len(coordinates) < 4:
            continue
        confidence_float = float(confidence)
        if confidence_float < confidence_threshold:
            continue
        detections.append(
            DetectionBox(
                x1=float(coordinates[0]),
                y1=float(coordinates[1]),
                x2=float(coordinates[2]),
                y2=float(coordinates[3]),
                confidence=confidence_float,
            )
        )
    return detections


def crop_image_to_merged_boxes(
    image: Image.Image,
    boxes: Sequence[DetectionBox],
    *,
    margin: int,
) -> Image.Image:
    crop_box = compute_merged_crop_box(boxes, image.size, margin=margin)
    if crop_box is None:
        return image.copy()
    return image.crop(crop_box)


def yoloworld_crop_image(
    image: Image.Image,
    *,
    class_name: str = "book",
    margin: int = 20,
    confidence_threshold: float = 0.25,
    image_size: Optional[int] = None,
) -> Image.Image:
    boxes = detect_boxes(
        image,
        class_name=class_name,
        confidence_threshold=confidence_threshold,
        image_size=image_size,
    )
    return crop_image_to_merged_boxes(image, boxes, margin=margin)


def compute_merged_crop_box(
    boxes: Sequence[DetectionBox],
    image_size: tuple[int, int],
    *,
    margin: int,
) -> tuple[int, int, int, int] | None:
    width, height = image_size
    valid_boxes = [
        box
        for box in boxes
        if _is_finite_box(box) and box.x2 > box.x1 and box.y2 > box.y1
    ]
    if not valid_boxes:
        return None

    x1 = math.floor(min(box.x1 for box in valid_boxes)) - margin
    y1 = math.floor(min(box.y1 for box in valid_boxes)) - margin
    x2 = math.ceil(max(box.x2 for box in valid_boxes)) + margin
    y2 = math.ceil(max(box.y2 for box in valid_boxes)) + margin

    clamped = (
        max(0, x1),
        max(0, y1),
        min(width, x2),
        min(height, y2),
    )
    if clamped[2] <= clamped[0] or clamped[3] <= clamped[1]:
        return None
    return clamped


def _is_finite_box(box: DetectionBox) -> bool:
    return all(math.isfinite(value) for value in (box.x1, box.y1, box.x2, box.y2))


def _to_list(value: Any) -> list[Any]:
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "tolist"):
        parsed = value.tolist()
        return parsed if isinstance(parsed, list) else [parsed]
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, Iterable):
        return list(value)
    return []
