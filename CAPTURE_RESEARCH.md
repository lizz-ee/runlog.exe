# Game Window Capture Research for Marathon (Bungie)

**Date:** 2026-03-17
**Goal:** Capture ONLY the Marathon game window (not full desktop) for privacy-safe recording.

---

## Critical Context: Marathon Uses DirectX 12

Marathon runs on Bungie's Tiger Engine with **DirectX 12**. This is the single most important finding:

> **DirectX 12 does NOT support true exclusive fullscreen.** All DX12 "fullscreen" modes are actually borderless windowed under the hood, using the DXGI Flip Model. The Windows Desktop Window Manager (DWM) always composites DX12 windows.

This means:
- Marathon's "Fullscreen" setting is actually an optimized borderless window state
- **Every capture method that works with borderless windowed will work with Marathon**
- We do NOT need to solve the "fullscreen exclusive capture" problem at all
- The game already behaves as borderless windowed regardless of in-game setting

Marathon also uses **BattlEye** anti-cheat (kernel-level), which affects some capture approaches.

---

## Approach Comparison Matrix

| Method | Fullscreen Exclusive | Borderless Windowed | Window-Only (Privacy) | Performance | Anti-Cheat Safe | Python Integration | Recommendation |
|--------|---------------------|--------------------|-----------------------|-------------|----------------|-------------------|---------------|
| **WGC (Windows Graphics Capture)** | No (DX12 issues) | Yes | **Yes (native)** | Excellent (GPU shared textures) | Yes | Good (windows-capture, wincam) | **BEST OPTION** |
| **DXGI Desktop Duplication (ddagrab)** | Sometimes | Yes | No (full desktop, crop after) | Excellent (GPU) | Yes | Good (DXcam, FFmpeg) | **CURRENT - needs privacy fix** |
| **FFmpeg gdigrab** | No (black screen) | Partial | Yes (by HWND) | Poor (GDI/CPU) | Yes | Native FFmpeg | Not recommended |
| **OBS Game Capture (DLL Hook)** | Yes | Yes | Yes (process-only) | Best | Whitelisted by BattlEye | None (C++ only) | Too complex, anti-cheat risk |
| **BitBlt / PrintWindow** | No (black screen) | Partial | Yes (by HWND) | Poor (CPU copy) | Yes | pywin32 | Not recommended |
| **NVIDIA NVFBC** | Yes | Yes | No (full framebuffer) | Best | Yes | Not available on consumer GPUs | **Not viable** |
| **OBS as middleware** | Via OBS | Via OBS | Via OBS config | Depends on OBS | Via OBS | WebSocket (control only) | Adds dependency |
| **DXcam/BetterCam** | Yes (DXGI) | Yes | No (full display, crop after) | 240+ fps | Yes | Native Python | Good fallback |
| **windows-capture (Python)** | No (WGC limitation) | Yes | **Yes (native)** | Excellent | Yes | `pip install windows-capture` | **BEST OPTION** |
| **wincam (Python)** | No (WGC) | Yes | **Yes (by HWND)** | <5ms latency | Yes | `pip install wincam` | **Strong option** |

---

## 1. Windows Graphics Capture API (WGC)

### How It Works
WGC (Windows.Graphics.Capture) is Microsoft's modern screen capture API, introduced in Windows 10 1803. It uses the DWM to share GPU textures directly from a specific window or display, without CPU-side copies.

### Key Properties
- **Window-specific capture:** Natively captures a single window by HWND via `IGraphicsCaptureItemInterop::CreateForWindow()`
- **Privacy:** Captures ONLY the target window content -- no desktop, no notifications, no other windows
- **Performance:** GPU texture sharing, no CPU round-trip. Low latency.
- **DX12 borderless:** Works perfectly with DX12 borderless windowed (which is what Marathon uses)
- **Fullscreen exclusive:** Does NOT reliably work with true FSE, but Marathon doesn't use FSE
- **Anti-cheat:** No DLL injection, no hooking. Completely safe with BattlEye.
- **Cross-GPU:** Works even if the game and capture app are on different GPUs

### Limitations
- Requires Windows 10 1803+
- Shows a yellow capture border on Windows 10 (removed in Windows 11 with `GraphicsCaptureSession.IsBorderRequired = false`)
- Some Vulkan/DX12 exclusive fullscreen paths may not be capturable (irrelevant for Marathon -- it's borderless)

### Python Bindings

**Option A: `windows-capture` (recommended)**
```
pip install windows-capture
```
```python
from windows_capture import WindowsCapture, Frame, InternalCaptureControl

capture = WindowsCapture(
    cursor_capture=None,
    draw_border=None,
    monitor_index=None,
    window_name="Marathon",  # Captures ONLY this window
)

@capture.event
def on_frame_arrived(frame: Frame, capture_control: InternalCaptureControl):
    # frame is a numpy array, process or encode as needed
    frame.save_as_image("frame.png")

@capture.event
def on_closed():
    print("Capture session closed")

capture.start()
```
- Built on Rust + WGC, extremely fast
- Window-specific capture by name
- Returns numpy arrays
- MIT licensed

**Option B: `wincam`**
```
pip install wincam
```
- Uses WGC via Direct3D11CaptureFramePool
- Supports `--hwnd` parameter for specific window capture
- Can encode H.264 video directly on GPU
- <5ms frame latency
- Requires Python 3.10+, Windows 10 19041+

**Option C: `python-winsdk` (low-level)**
```python
from winsdk.windows.graphics.capture.interop import create_for_window
item = create_for_window(hwnd)  # GraphicsCaptureItem for specific window
```

### FFmpeg Integration
WGC is NOT directly available as an FFmpeg input device. FFmpeg has `ddagrab` (DXGI) and `gdigrab` (GDI) but no WGC source. This means:
- For WGC-based capture, use a Python library, not FFmpeg
- The Python library captures frames as numpy arrays
- Encode with hardware encoder (NVENC) via a separate FFmpeg pipe or OpenCV VideoWriter

---

## 2. DXGI Desktop Duplication (ddagrab) -- Current Implementation

### How It Works
DXGI Desktop Duplication captures the entire desktop output buffer from the GPU. This is what our current `capture.py` uses via FFmpeg's `ddagrab` filter.

### Current Problem: Privacy
```
ddagrab=framerate=60:output_idx=0  -- captures ENTIRE desktop
```
This captures everything on the monitor: game, notifications, other windows, personal content.

### Can It Be Scoped to a Window?
**No.** ddagrab captures the full display output. However, it supports cropping parameters:
```
ddagrab=framerate=60:output_idx=0:offset_x=X:offset_y=Y:video_size=WxH
```
This crops the capture region, but:
- You must know the exact window coordinates
- If the game moves, coordinates are wrong
- If other windows overlap the game area, they get captured too
- **Not truly privacy-safe** -- just a crop of the full desktop

### Workaround: Dynamic Cropping
1. Use `win32gui.FindWindow()` / `GetWindowRect()` to get Marathon's window position
2. Pass coordinates to ddagrab's offset/size parameters
3. Re-launch FFmpeg if window moves (impractical)

**Verdict:** Not suitable for privacy. The GPU still captures the full desktop internally; the crop is applied after. Overlapping windows will be captured.

### Performance
- Excellent: GPU-only capture, no CPU involvement
- 60fps capture with h264_nvenc encoding has near-zero game impact
- This is why our current implementation performs well

---

## 3. FFmpeg gdigrab

### How It Works
GDI-based screen capture using the legacy Windows GDI API. Supports window capture by title or HWND.

### Window Capture Syntax
```bash
# By window title
ffmpeg -f gdigrab -i title="Marathon" -c:v h264_nvenc output.mp4

# By HWND (newer FFmpeg builds)
ffmpeg -f gdigrab -hwnd 0x12345 -i desktop output.mp4
```

### Why It Fails for Games
- GDI cannot capture hardware-accelerated (GPU-rendered) content
- DirectX/Vulkan surfaces bypass the GDI pipeline entirely
- Result: **black screen** for fullscreen exclusive games
- For borderless windowed: **may work** but often produces black frames for DX12 games because the content is GPU-composed

### Performance
- Very poor: GPU-to-CPU data copy through GDI
- High CPU usage, high latency
- Not suitable for 60fps game recording

### Verdict
**Not recommended.** Even in borderless windowed mode, DX12 games frequently produce black frames via gdigrab. Performance is poor.

---

## 4. Game Capture Hooks (DLL Injection)

### How OBS Does It
OBS's game capture works by:
1. Identifying the game process
2. Injecting a DLL (`graphics-hook64.dll`) into the game process
3. Hooking DirectX/Vulkan/OpenGL Present/SwapChain calls
4. Copying frames from the game's render pipeline via shared GPU textures
5. Communicating via named shared memory objects

Source code: `obsproject/obs-studio/plugins/win-capture/graphics-hook/`

### Privacy
**Excellent.** Only captures the game's own render output. No desktop, no other windows.

### Performance
**Best possible.** Directly intercepts the rendering pipeline. Frame delivery is synchronized with the game's own rendering.

### Anti-Cheat Concerns
- OBS is specifically whitelisted by BattlEye (Marathon's anti-cheat)
- A custom DLL injection tool would **NOT** be whitelisted
- BattlEye's BEDaisy kernel driver filters DLL loads into protected processes
- Using our own injection hook would almost certainly trigger BattlEye detection
- Players could get **permanently banned** -- Bungie has a zero-tolerance policy

### Integration
- OBS's hook code is C++ and deeply integrated with OBS's plugin architecture
- No standalone library exists for this approach
- Building our own would require significant C++ development
- **Anti-cheat risk makes this completely unacceptable for a commercial product**

### Verdict
**Do not pursue.** Anti-cheat risk is disqualifying. We cannot risk getting users banned from Marathon.

---

## 5. BitBlt / PrintWindow

### How They Work
Win32 GDI functions that copy window content to a device context (DC).

### Game Capture
- **BitBlt:** Captures from the screen DC. GPU-rendered content appears as black.
- **PrintWindow:** Sends WM_PRINT to the target window. Games don't handle this message.
- Both methods: **black screen** for DirectX/Vulkan games, even borderless windowed.

### Performance
- CPU-based pixel copying
- Very slow for 1080p/4K content
- Not suitable for real-time recording

### Verdict
**Not viable.** Black screen with DX games. Poor performance.

---

## 6. OBS as Middleware

### Approach
Run OBS in the background with game capture configured, then either:
- Read from OBS's replay buffer files
- Use OBS WebSocket API to control recording
- Read from OBS's virtual camera output

### OBS WebSocket API (Python)
```python
# pip install obsws-python
import obsws_python as obs
client = obs.ReqClient(host='localhost', port=4455)
client.start_replay_buffer()
client.save_replay_buffer()  # Saves last N seconds to file
```

### Limitations
- **Cannot read frame data** via WebSocket -- only control commands
- Replay buffer saves to files, which we'd then need to read and process
- Requires user to install and configure OBS separately
- OBS must be running with correct scene/source configuration
- Virtual camera output only works as a camera device, not for file recording
- Adds a major external dependency

### Privacy
Good -- OBS game capture only captures the game window.

### Performance
Good -- OBS's capture is well-optimized.

### Verdict
**Possible but poor UX.** Requiring users to install and configure OBS is not acceptable for a consumer product. However, we could potentially bundle a minimal OBS configuration.

---

## 7. Borderless Windowed Mode

### Marathon's Reality
**Marathon already runs in borderless windowed mode** regardless of the in-game "Fullscreen" setting. This is because:
- Marathon uses DirectX 12
- DX12 uses DXGI Flip Model, which doesn't support true exclusive fullscreen
- Windows 10/11 "Fullscreen Optimizations" convert all DX12 fullscreen to borderless
- Bungie has confirmed Marathon's fullscreen is an "optimized borderless window state"

### Performance Impact
- On modern systems (Windows 10/11 with DX12): **0-5% FPS difference** from true exclusive fullscreen
- 1-25ms extra frame time, 0-10ms added input latency
- For most players: **unnoticeable**
- Since Marathon is already borderless, there is **zero additional performance cost**

### What This Means for Capture
Since Marathon is already borderless windowed:
- **WGC window capture works perfectly**
- DXGI Desktop Duplication works (but captures full desktop)
- We do NOT need to tell users to change any settings
- No "please switch to borderless" requirement needed

### Verdict
**This is already the case.** Marathon is borderless windowed. No user action needed.

---

## 8. NVIDIA ShadowPlay / NVENC

### How ShadowPlay Captures
ShadowPlay uses two proprietary NVIDIA APIs:
- **NVFBC (Frame Buffer Capture):** Captures the entire GPU framebuffer directly. Used for full-screen capture.
- **NVIFR (Inband Frame Readback):** Captures a single window. Used for window-specific capture.

Both capture independently of DirectX/Vulkan -- they read directly from the GPU framebuffer.

### NVENC Encoding
After capture, frames are encoded using NVIDIA's hardware H.264/HEVC encoder (NVENC), which is a separate chip on the GPU with near-zero impact on game performance.

**We already use NVENC** via FFmpeg's `h264_nvenc` encoder. This part of our stack is correct.

### Can We Use ShadowPlay's Capture?
**No.** ShadowPlay's capture APIs (NVFBC/NVIFR) are not available to third-party applications on consumer GPUs. NVIDIA restricts them to:
- NVIDIA's own software (GeForce Experience / ShadowPlay)
- GRID/Tesla/Quadro professional GPUs
- Partners with explicit NVIDIA licensing (e.g., Valve for Steam Remote Play)

### Verdict
**Not available.** NVFBC/NVIFR are locked to professional GPUs and NVIDIA's own software. We can use NVENC for encoding (which we already do), but not for capture.

---

## 9. NVIDIA NVFBC (Detailed)

### API Details
- Captures the entire desktop framebuffer at the GPU level
- Zero CPU involvement, extremely low latency
- Can output to system memory, CUDA, or GPU texture
- Supports H.264/HEVC encoding via NvEncode in the same pipeline

### Consumer GPU Restriction
NVIDIA explicitly blocks NVFBC on GeForce GPUs:
- Official SDK only supports GRID, Tesla, Quadro X2000+
- An unofficial community patch exists to remove this restriction
- Using the patch **violates NVIDIA's license agreement**
- The patch could break with any driver update

### Even If Available
NVFBC captures the **entire framebuffer** (full desktop), not specific windows. NVIFR can capture specific windows, but has the same consumer GPU restriction.

### Verdict
**Not viable for commercial use.** License restrictions, consumer GPU blocking, and it captures full desktop anyway.

---

## 10. Python Libraries Comparison

### DXcam
```
pip install dxcam
```
- **Backend:** DXGI Desktop Duplication
- **Window-specific:** No. Display-level only with region crop.
- **Fullscreen games:** Yes (DX11/12 capture works)
- **Performance:** 240+ fps at 1080p
- **Privacy:** Captures full display, crop to region coordinates as workaround
- **Output:** numpy arrays (HxWxC), integrate with OpenCV for video encoding
- **Maturity:** Well-maintained, updated 2026, CPython 3.10-3.14

### BetterCam
```
pip install bettercam
```
- Fork of DXcam with additional features
- Same DXGI backend, same limitations
- Supports region capture: `camera.grab(region=(left, top, right, bottom))`
- 240+ fps capable

### windows-capture
```
pip install windows-capture
```
- **Backend:** Windows Graphics Capture API (WGC)
- **Window-specific:** YES -- by window name
- **Fullscreen games:** Borderless windowed only (perfect for Marathon)
- **Performance:** Excellent (GPU texture sharing)
- **Privacy:** Captures ONLY the target window
- **Output:** numpy arrays via event callbacks
- **Maturity:** Active development, Rust core with Python bindings

### wincam
```
pip install wincam
```
- **Backend:** WGC via Direct3D11CaptureFramePool
- **Window-specific:** YES -- by HWND
- **Performance:** <5ms latency per frame
- **Video encoding:** Built-in H.264 GPU encoding
- **Privacy:** Captures ONLY the target window
- **Requirements:** Python 3.10+, Windows 10 19041+, x64 only

### mss (python-mss)
```
pip install mss
```
- **Backend:** GDI-based
- **Window-specific:** No (full screen or region)
- **Performance:** ~75 fps (3x slower than DXcam)
- **Privacy:** Full screen capture with region crop
- **Note:** Known issues with fullscreen game capture

### pyautogui
- Too slow for real-time capture
- GDI-based, same black screen issues
- Not suitable for game recording

---

## Recommended Architecture

### Primary: WGC via `windows-capture` or `wincam`

```
Marathon Window (HWND)
       |
       v
WGC API (GPU texture sharing, window-specific)
       |
       v
Python (windows-capture library)
       |
       v
numpy frames -> FFmpeg pipe (stdin) -> h264_nvenc -> MP4 file
```

**Privacy:** Only Marathon's window content is ever captured. No desktop, no notifications, no other windows.

**Performance Pipeline:**
1. WGC shares GPU textures of Marathon's window (near-zero overhead)
2. Python receives frames as numpy arrays
3. Pipe raw frames to FFmpeg for NVENC encoding
4. FFmpeg writes H.264 MP4 with hardware encoding

### Fallback: DXGI + Dynamic Crop via DXcam

If WGC has issues with Marathon specifically:
```
DXGI Desktop Duplication (full display)
       |
       v
DXcam with region=(game_left, game_top, game_right, game_bottom)
       |
       v
numpy frames -> FFmpeg pipe -> h264_nvenc -> MP4
```

**Privacy mitigation:**
- Use `win32gui.GetWindowRect()` to get Marathon's exact coordinates
- Pass as region to DXcam
- Risk: if another window overlaps Marathon's area, it gets captured
- Mitigation: check if Marathon is the foreground window before each frame

### Keep: NVENC Encoding
Our current h264_nvenc encoding is optimal. Keep the same encoder settings regardless of capture method.

---

## Migration Path from Current Implementation

### Current (`capture.py`)
```
ddagrab (full desktop) -> h264_nvenc -> MP4
```

### Target
```
WGC (Marathon window only) -> h264_nvenc -> MP4
```

### Changes Required
1. **Replace ddagrab capture** with `windows-capture` or `wincam` Python library
2. **Find Marathon window** by process name or window title
3. **Pipe frames** from Python to FFmpeg for NVENC encoding (or use wincam's built-in encoder)
4. **Keep** existing OCR detection, state machine, and processing pipeline
5. **Keep** existing NVENC encoding settings (p4 preset, ll tune, vbr, cq 23)

### Detection Pipeline Change
Current: `ddagrab -> hwdownload -> JPEG pipe -> OCR`
New: `WGC window frames (numpy) -> JPEG encode in Python -> OCR`

This actually simplifies the detection pipeline since we get numpy arrays directly instead of parsing a JPEG stream from FFmpeg.

---

## Anti-Cheat Summary

Marathon uses **BattlEye** (kernel-level anti-cheat). Impact on capture methods:

| Method | BattlEye Risk | Notes |
|--------|--------------|-------|
| WGC (Windows Graphics Capture) | **None** | OS-level API, no injection |
| DXGI Desktop Duplication | **None** | OS-level API, no injection |
| FFmpeg gdigrab | **None** | OS-level API, no injection |
| OBS Game Capture | **Low** | OBS is whitelisted, but custom hooks are not |
| Custom DLL injection | **HIGH** | Will trigger BattlEye. Permanent ban risk. |
| BitBlt/PrintWindow | **None** | OS-level API, no injection |
| NVFBC | **None** | GPU-level API, no injection |

**WGC and DXGI are both completely safe** -- they use standard Windows APIs with no process injection.

---

## Final Recommendation

**Use Windows Graphics Capture (WGC) via the `windows-capture` Python library.**

Reasons:
1. **Privacy-safe:** Captures ONLY the Marathon window, never the desktop
2. **Marathon compatible:** Marathon is DX12 borderless windowed -- WGC works perfectly
3. **No anti-cheat risk:** Standard Windows API, no DLL injection
4. **High performance:** GPU texture sharing, minimal overhead
5. **Easy Python integration:** `pip install windows-capture`, event-driven API
6. **Simpler than current approach:** No FFmpeg subprocess for capture (only for encoding)

The only downside vs. our current ddagrab approach is that WGC returns frames to Python (requiring a pipe to FFmpeg for encoding) rather than FFmpeg handling everything. However, `wincam` includes built-in H.264 GPU encoding that could eliminate the FFmpeg dependency for recording entirely.

---

## Sources

- [OBS Forum: WGC vs DXGI Desktop Duplication](https://obsproject.com/forum/threads/windows-graphics-capture-vs-dxgi-desktop-duplication.149320/)
- [OBS PR: Windows Graphics Capture support](https://github.com/obsproject/obs-studio/pull/2208)
- [Game Capture & Window Capture (Ryan's Blog)](https://ryanai.dev/en/blog/pc-window-capture)
- [windows-capture (GitHub)](https://github.com/NiiightmareXD/windows-capture)
- [windows-capture (PyPI)](https://pypi.org/project/windows-capture/)
- [wincam (GitHub)](https://github.com/lovettchris/wincam)
- [DXcam (GitHub)](https://github.com/ra1nty/DXcam)
- [BetterCam (GitHub)](https://github.com/RootKit-Org/BetterCam)
- [ddagrab FFmpeg docs](https://ayosec.github.io/ffmpeg-filters-docs/7.1/Sources/Video/ddagrab.html)
- [NVIDIA Capture SDK](https://developer.nvidia.com/capture-sdk)
- [NVFBC on GeForce (NVIDIA Forums)](https://forums.developer.nvidia.com/t/nvfbc-on-geforce/54460)
- [OBS Game Capture source](https://github.com/obsproject/obs-studio/blob/master/plugins/win-capture/game-capture.c)
- [OBS Capture Hook Certificate](https://obsproject.com/kb/capture-hook-certificate-update)
- [BattlEye blocking OBS (OBS Forum)](https://obsproject.com/forum/threads/battleeye-blocking-obs-graphics-capturehook-dll-fix-needed.32904/)
- [Marathon Anti-Cheat Details (KeenGamer)](https://www.keengamer.com/articles/news/marathon-anti-cheat-and-security-details-permabans-fog-of-war-and-dedicated-servers/)
- [Marathon Best PC Settings (GameRant)](https://gamerant.com/marathon-best-pc-graphics-settings-optimization-guide/)
- [Borderless Fullscreen not an option (Marathon Help)](https://help.marathonthegame.com/hc/en-us/community/posts/46705192567444-Borderless-Fullscreen-not-an-option)
- [D3DShot (GitHub)](https://github.com/SerpentAI/D3DShot)
- [python-winsdk WGC interop](https://python-winsdk.readthedocs.io/en/latest/api/windows/graphics.capture.interop.html)
- [Win32CaptureSample (Microsoft)](https://github.com/robmikh/Win32CaptureSample)
- [DXGI Desktop Duplication API (Microsoft)](https://learn.microsoft.com/en-us/windows/win32/direct3ddxgi/desktop-dup-api)
- [Microsoft: DXGI Flip Model](https://learn.microsoft.com/en-us/windows/win32/direct3ddxgi/for-best-performance--use-dxgi-flip-model)
- [PCWorld: Fullscreen vs Borderless](https://www.pcworld.com/article/2618229/fullscreen-vs-borderless-why-i-stopped-tripping-on-the-gaming-mode-question.html)
- [OBS Vulkan Capture](https://github.com/obsproject/obs-studio/blob/master/plugins/win-capture/graphics-hook/vulkan-capture.c)
- [FFmpeg gdigrab HWND patch](https://patchwork.ffmpeg.org/project/ffmpeg/patch/20231217172932.60614-2-lena@nihil.gay/)
- [Medal.tv Advanced Window Capture](https://support.medal.tv/support/solutions/articles/48001171330-what-is-advanced-window-capture-)
