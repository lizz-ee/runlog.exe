# Test Machines

Hardware profiles used for testing runlog.exe across different configurations.

---

## Machine A — Desktop (Primary Dev)

| | |
|---|---|
| **Machine** | Custom Desktop (DESKTOP-PAULBUNYAN) |
| **OS** | Windows 11 Pro 10.0.26200 (64-bit) |

| Component | Spec |
|---|---|
| **CPU** | Intel Core i9-12900K @ 3.20GHz (16 cores / 24 threads) |
| **GPU (Dedicated)** | NVIDIA GeForce RTX 3090 (24GB VRAM) |
| **GPU (Integrated)** | Intel UHD Graphics 770 |
| **RAM** | 64 GB |
| **Display** | 3840x2160 (4K) |

### Test Results

| Feature | Status | Notes |
|---|---|---|
| Game detection (OCR) | Pass | 4K native, EasyOCR reads all regions reliably |
| Recording (WGC) | Pass | 4K 60fps, zero-copy GPU capture |
| Video processing | Pass | Native 3840px extraction, AI analysis accurate |
| Spawn coordinate matching | Pass | Loading screen coords extracted and matched |
| Overlay positioning | Pass | All corners correct at 4K |

---

## Machine B — Laptop (1080p Test)

| | |
|---|---|
| **Machine** | Alienware m17 R4 (Laptop) |
| **OS** | Windows 11 Home 10.0.26200 (64-bit) |

| Component | Spec |
|---|---|
| **CPU** | Intel Core i7-10870H @ 2.20GHz (8 cores / 16 threads) |
| **GPU (Dedicated)** | NVIDIA GeForce RTX 3070 Laptop GPU (8GB VRAM) |
| **GPU (Integrated)** | Intel UHD Graphics (1GB) |
| **RAM** | 16 GB (2x 8GB @ 2933 MHz) |
| **Display** | 1920x1080 @ 360Hz |
| **Storage** | KIOXIA KXG60ZNV1T02 NVMe (954 GB SSD) |

### Test Results

| Feature | Status | Notes |
|---|---|---|
| Install (install.bat) | Pass | Python found, all deps installed, build completes |
| Python path saved | Pass | Correct path saved to AppData/runlog/python-path |
| Backend launch | Pass | App starts, backend connects |
| OCR model download | Pass | Required PYTHONIOENCODING=utf-8 fix for cp1252 crash |
| Game detection (OCR) | Pending | Models downloaded, EasyOCR reads "PREPARE" at 98.9% confidence in manual test |
| Recording (WGC) | Pending | |
| Video processing | Pending | Dynamic resolution (1920px native) — needs live test |
| Overlay positioning | Pending | Fixed TC/TR/BC/BR offset (was using 290px width for 500px window) |
| App icon (exe) | Fail | rcedit blocked by SmartScreen, switched to npx @electron/rcedit — retesting |
| App icon (shortcut) | Pass | IconLocation set explicitly on .lnk |
| Spawn points seeded | Pending | 33 spawns in seed JSON, needs fresh DB verification |

---

## Issues Found on Machine B

| Issue | Root Cause | Fix |
|---|---|---|
| Backend wouldn't start | Electron packaged app didn't inherit user PATH | Installer saves exact Python path to AppData |
| OCR models not downloaded | EasyOCR progress bar crashes on Windows cp1252 encoding | Set PYTHONIOENCODING=utf-8 |
| OCR crops too small | 1080p crops ~50% of 4K, borderline for EasyOCR | Auto-upscale crops below 1000px wide |
| Frame extraction blurry | Hardcoded FRAME_RESOLUTION=3840 upscaled 1080p→4K | Dynamic resolution via ffprobe, never upscale |
| Overlay mispositioned | Position calculated with content width (290px) not window width (500px) | Use actual window width |
| "WGC // 4K" hardcoded | Frontend and overlay showed "4K" regardless of actual resolution | Show actual capture_resolution from backend |
| Exe icon missing | rcedit downloaded exe blocked by SmartScreen | Use npx @electron/rcedit instead |
