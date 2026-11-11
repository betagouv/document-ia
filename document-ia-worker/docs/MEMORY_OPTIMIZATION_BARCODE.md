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
`ExtractBarcode2DDocData` serializes image reading, downsampling, and detection under a single process-wide lock (`_BARCODE_LOCK`). This guarantees:
- Exactly **one** heavy image is decompressed into uncompressed RAM at any given time.
- Total processing time under lock is brief (50 ms – 350 ms), preserving parallel execution for I/O-bound steps (S3 transfers, HTTP OCR, LLM inference).

### 2.2. Intelligent Pre-Inference Downsampling
Before submitting images to barcode scanning or QRDet inference, the image dimensions are inspected:
- **Maximum Long Edge Threshold**: `MAX_BARCODE_IMAGE_DIM = 2048 px`.
- If $\max(\text{width}, \text{height}) > 2048\text{ px}$, the image is immediately resized using area interpolation (`cv2.INTER_AREA`).
- The original unscaled matrix is immediately deallocated (`del`).
- *Impact*: Reduces raw image memory by over **90%** (e.g. from 144 MB down to ~12 MB) while keeping 2D-Doc / QR code features at 150–250 px, which is optimal for ZXing-cpp and YOLOv8.

### 2.3. Conditional Crop Upscaling
The x2 / x3 upscaling is reserved exclusively for small or low-resolution crops:
- If $\max(\text{crop\_width}, \text{crop\_height}) \le 250\text{ px}$: Apply x2 upscale, and if no DataMatrix is found, x3 upscale.
- If $\max(\text{crop\_width}, \text{crop\_height}) > 250\text{ px}$: **Skip upscaling**. The crop is decoded directly at 1x scale, preventing memory ballooning and edge blur.

### 2.4. Explicit Cleanup & Linux `malloc_trim(0)`
1. Local variables holding large matrices (`img_raw`, `img`, `rois`, `crop`, `image_scaled`) are explicitly cleared using `del` in `finally` blocks.
2. Python garbage collection `gc.collect()` is explicitly invoked after heavy inference.
3. At the end of each workflow execution in `WorkflowManager`, `malloc_trim(0)` is invoked on Linux platforms:
   ```python
   import ctypes
   import gc
   import sys

   gc.collect()
   if sys.platform.startswith("linux"):
       try:
           ctypes.CDLL("libc.so.6").malloc_trim(0)
       except Exception:
           pass
   ```
   > [!IMPORTANT]
   > `malloc_trim(0)` reclaims fragmented heap memory back to the Linux kernel without unloading cached PyTorch models or Python singletons (`_qrdet_detector`, `YOLO-World`). Reload delay is **zero seconds**.

### 2.5. Bounded Loki Log Queue
The Loki queue handler (`document-ia-infra/core/loki_settings.py`) enforces a bounded queue `Queue(maxsize=1000)` instead of `Queue(-1)`. When remote log endpoints experience network latency or outages, un-emitted logs are discarded after reaching capacity rather than causing silent process OOM crashes.

---

## 3. Configuration Reference

| Environment / Setting | Default | Description |
| :--- | :--- | :--- |
| `MAX_BARCODE_IMAGE_DIM` | `2048` | Max long edge (px) for whole-page barcode scanning |
| `MAX_CROP_DIM_FOR_UPSCALE` | `250` | Max crop dimension (px) eligible for 2x/3x upscaling |
| `REDIS_WORKER_NUMBER` | `8` | Number of concurrent workflow threads in ThreadConsumer |
| `MALLOC_ARENA_MAX` | `2` | Glibc arena limit to reduce virtual memory fragmentation |
