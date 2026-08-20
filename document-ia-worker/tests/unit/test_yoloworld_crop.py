from pathlib import Path

import pytest
from PIL import Image

from document_ia_worker.core.preprocessing import yoloworld_crop as crop_mod
from document_ia_worker.core.preprocessing.yoloworld_crop import (
    DetectionBox,
    compute_merged_crop_box,
    crop_image_to_merged_boxes,
    detect_boxes,
)


def _make_image(path: Path, size: tuple[int, int] = (100, 80)) -> Path:
    image = Image.new("RGB", size, "white")
    image.save(path)
    return path


def test_no_box_keeps_image_unchanged():
    image = Image.new("RGB", (100, 80), "white")

    result = crop_image_to_merged_boxes(image, [], margin=20)

    assert result.size == image.size
    assert result.tobytes() == image.tobytes()


def test_multiple_boxes_are_merged_into_one_crop():
    crop_box = compute_merged_crop_box(
        [
            DetectionBox(10, 20, 30, 40, 0.9),
            DetectionBox(50, 5, 70, 60, 0.8),
        ],
        (100, 80),
        margin=5,
    )

    assert crop_box == (5, 0, 75, 65)


def test_margin_is_clamped_to_image_bounds():
    crop_box = compute_merged_crop_box(
        [DetectionBox(2, 3, 95, 77, 0.9)],
        (100, 80),
        margin=20,
    )

    assert crop_box == (0, 0, 100, 80)


def test_confidence_threshold_is_applied(monkeypatch):
    class FakeBoxes:
        xyxy = [[1, 2, 10, 20], [20, 25, 50, 60]]
        conf = [0.2, 0.8]

    class FakeResult:
        boxes = FakeBoxes()

    class FakeModel:
        def __init__(self):
            self.classes = None

        def set_classes(self, classes):  # noqa: ANN001
            self.classes = classes

        def predict(self, image, **kwargs):  # noqa: ANN001, ARG002
            return [FakeResult()]

    fake_model = FakeModel()
    monkeypatch.setattr(
        crop_mod,
        "get_yoloworld_model",
        lambda: fake_model,
    )

    boxes = detect_boxes(
        Image.new("RGB", (100, 80), "white"),
        class_name="book",
        confidence_threshold=0.25,
    )

    assert fake_model.classes == ["book"]
    assert boxes == [DetectionBox(20, 25, 50, 60, 0.8)]


def test_model_path_uses_yoloworld_environment_variable(monkeypatch):
    monkeypatch.setenv("YOLOWORLD_PATH", "/tmp/custom-yoloworld.pt")
    monkeypatch.setattr(crop_mod, "_MODEL_CACHE", None)

    class FakeYOLOWorld:
        def __init__(self, path):
            assert path == "/tmp/custom-yoloworld.pt"

    monkeypatch.setattr(
        "ultralytics.YOLOWorld",
        FakeYOLOWorld,
    )

    assert isinstance(crop_mod.get_yoloworld_model(), FakeYOLOWorld)

def test_invalid_box_falls_back_to_original_image():
    image = Image.new("RGB", (100, 80), "white")

    result = crop_image_to_merged_boxes(
        image,
        [DetectionBox(50, 20, 10, 40, 0.9)],
        margin=10,
    )

    assert result.size == image.size
    assert result.tobytes() == image.tobytes()
