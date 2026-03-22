use std::io::{self, BufRead, Write};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Instant;

use serde::{Deserialize, Serialize};
use windows_capture::capture::{Context, GraphicsCaptureApiHandler};
use windows_capture::encoder::{
    AudioSettingsBuilder, ContainerSettingsBuilder, VideoEncoder, VideoSettingsBuilder,
    VideoSettingsSubType,
};
use windows_capture::frame::Frame;
use windows_capture::graphics_capture_api::InternalCaptureControl;
use windows_capture::settings::{
    ColorFormat, CursorCaptureSettings, DirtyRegionSettings, DrawBorderSettings,
    MinimumUpdateIntervalSettings, SecondaryWindowSettings, Settings,
};
use windows_capture::window::Window;

use windows::Win32::Graphics::Direct3D11::*;
use windows::Win32::Graphics::Dxgi::Common::DXGI_SAMPLE_DESC;

// ---------------------------------------------------------------------------
// IPC messages
// ---------------------------------------------------------------------------

#[derive(Deserialize)]
#[serde(tag = "cmd")]
enum Command {
    #[serde(rename = "start")]
    Start { path: String, bitrate: Option<u32>, encoder: Option<String>, fps: Option<u32> },
    #[serde(rename = "stop")]
    Stop,
    #[serde(rename = "screenshot")]
    Screenshot { path: String },
    #[serde(rename = "quit")]
    Quit,
}

#[derive(Serialize)]
#[serde(tag = "event")]
enum Event {
    #[serde(rename = "ready")]
    Ready {
        window: String,
        width: u32,
        height: u32,
    },
    #[serde(rename = "recording_started")]
    RecordingStarted { path: String },
    #[serde(rename = "recording_stopped")]
    RecordingStopped {
        path: String,
        duration: f64,
        frames: u64,
    },
    #[serde(rename = "frame")]
    Frame { jpeg_base64: String },
    #[serde(rename = "screenshot_saved")]
    ScreenshotSaved { path: String },
    #[serde(rename = "error")]
    Error { message: String },
}

fn emit(event: &Event) {
    let json = serde_json::to_string(event).unwrap();
    let stdout = io::stdout();
    let mut out = stdout.lock();
    let _ = writeln!(out, "{}", json);
    let _ = out.flush();
}

// ---------------------------------------------------------------------------
// Shared state between IPC thread and capture callback
// ---------------------------------------------------------------------------

struct OcrFrameData {
    raw: Vec<u8>,
    width: usize,
    height: usize,
    row_pitch: usize,
}

struct SharedState {
    /// Window title for ready event
    window_title: Mutex<String>,
    /// When true, the encoder should be created/active
    should_record: AtomicBool,
    /// Path for the next recording
    record_path: Mutex<Option<String>>,
    /// Bitrate for the next recording
    record_bitrate: Mutex<Option<u32>>,
    /// Encoder type for the next recording ("hevc" or "h264")
    record_encoder: Mutex<Option<String>>,
    /// FPS for the next recording
    record_fps: Mutex<Option<u32>>,
    /// When true, the capture should shut down
    should_quit: AtomicBool,
    /// Request a screenshot save
    screenshot_path: Mutex<Option<String>>,
    /// Total encoded frames (for reporting)
    encoded_frames: AtomicU64,
    /// OCR frame buffer — callback copies raw pixels here, bg thread processes
    ocr_pending: Mutex<Option<OcrFrameData>>,
    ocr_notify: std::sync::Condvar,
}

// ---------------------------------------------------------------------------
// Double-buffered staging pool — zero-stall GPU→CPU readback
// ---------------------------------------------------------------------------

struct StagingPool {
    staging: [Option<ID3D11Texture2D>; 2],
    current: usize,
    ready: [bool; 2],
    device: Option<ID3D11Device>,
    context: Option<ID3D11DeviceContext>,
    width: u32,
    height: u32,
}

impl StagingPool {
    fn new() -> Self {
        Self {
            staging: [None, None],
            current: 0,
            ready: [false, false],
            device: None,
            context: None,
            width: 0,
            height: 0,
        }
    }

    /// Initialize device/context from the frame texture (first call only),
    /// and recreate staging textures if resolution changed.
    fn ensure_staging(&mut self, frame_texture: &ID3D11Texture2D) {
        if self.device.is_none() {
            unsafe {
                let device: ID3D11Device = frame_texture.GetDevice().unwrap();
                let context: ID3D11DeviceContext = device.GetImmediateContext().unwrap();
                self.context = Some(context);
                self.device = Some(device);
            }
        }

        let mut desc = D3D11_TEXTURE2D_DESC::default();
        unsafe { frame_texture.GetDesc(&mut desc) };

        // Recreate staging textures if resolution changed
        if desc.Width != self.width || desc.Height != self.height {
            self.width = desc.Width;
            self.height = desc.Height;
            let staging_desc = D3D11_TEXTURE2D_DESC {
                Width: desc.Width,
                Height: desc.Height,
                MipLevels: 1,
                ArraySize: 1,
                Format: desc.Format,
                SampleDesc: DXGI_SAMPLE_DESC { Count: 1, Quality: 0 },
                Usage: D3D11_USAGE_STAGING,
                BindFlags: 0,
                CPUAccessFlags: D3D11_CPU_ACCESS_READ.0 as u32,
                MiscFlags: 0,
            };
            for i in 0..2 {
                let mut tex = None;
                let result = unsafe {
                    self.device.as_ref().unwrap()
                        .CreateTexture2D(&staging_desc, None, Some(&mut tex))
                };
                match result {
                    Ok(_) => {
                        self.staging[i] = tex;
                        self.ready[i] = false;
                    }
                    Err(e) => {
                        eprintln!("[recorder] Failed to create staging texture {}: {}", i, e);
                        self.staging[i] = None;
                        self.ready[i] = false;
                    }
                }
            }
            eprintln!("[recorder] Staging pool created: {}x{} (2 buffers)", desc.Width, desc.Height);
        }
    }

    /// Issue async CopyResource for the current frame, return the previously-copied data.
    /// Returns None on the first call (no previous data yet).
    fn copy_and_read(&mut self, frame_texture: &ID3D11Texture2D) -> Option<OcrFrameData> {
        self.ensure_staging(frame_texture);
        let ctx = self.context.as_ref().unwrap();

        let read_idx = self.current;       // Read from this (previous copy, already complete)
        let write_idx = 1 - self.current;  // Write to this (new async copy)

        // 1. Read the OLD staging buffer — copy was issued ~3s ago, Map returns instantly
        let result = if self.ready[read_idx] {
            let staging = match self.staging[read_idx].as_ref() {
                Some(s) => s,
                None => return None,
            };
            let mut mapped = D3D11_MAPPED_SUBRESOURCE::default();
            let hr = unsafe {
                ctx.Map(staging, 0, D3D11_MAP_READ, 0, Some(&mut mapped))
            };
            if hr.is_ok() {
                let row_pitch = mapped.RowPitch as usize;
                let total_bytes = row_pitch * self.height as usize;
                let data = unsafe {
                    std::slice::from_raw_parts(mapped.pData as *const u8, total_bytes)
                };
                let raw = data.to_vec();
                unsafe { ctx.Unmap(staging, 0) };
                self.ready[read_idx] = false;
                Some(OcrFrameData {
                    raw,
                    width: self.width as usize,
                    height: self.height as usize,
                    row_pitch,
                })
            } else {
                None
            }
        } else {
            None // First call — no previous data yet
        };

        // 2. Issue ASYNC CopyResource to the other staging buffer (non-blocking)
        let staging_dst = match self.staging[write_idx].as_ref() {
            Some(s) => s,
            None => return result,  // Can't copy, just return what we read
        };
        unsafe { ctx.CopyResource(staging_dst, frame_texture) };
        self.ready[write_idx] = true;

        // 3. Swap buffers for next call
        self.current = write_idx;

        result
    }
}

// ---------------------------------------------------------------------------
// Capture handler
// ---------------------------------------------------------------------------

struct Recorder {
    state: Arc<SharedState>,
    encoder: Option<VideoEncoder>,
    recording_path: Option<String>,
    recording_start: Option<Instant>,
    frame_count: u64,
    width: u32,
    height: u32,
    /// Send OCR frames every N capture frames
    ocr_interval: u64,
    /// Double-buffered staging for zero-stall OCR during recording
    staging_pool: StagingPool,
}

impl GraphicsCaptureApiHandler for Recorder {
    type Flags = Arc<SharedState>;
    type Error = Box<dyn std::error::Error + Send + Sync>;

    fn new(ctx: Context<Self::Flags>) -> Result<Self, Self::Error> {
        Ok(Self {
            state: ctx.flags,
            encoder: None,
            recording_path: None,
            recording_start: None,
            frame_count: 0,
            width: 0,
            height: 0,
            ocr_interval: 15, // ~0.25s at 60fps in menus, stretched during recording
            staging_pool: StagingPool::new(),
        })
    }

    fn on_frame_arrived(
        &mut self,
        frame: &mut Frame<'_>,
        capture_control: InternalCaptureControl,
    ) -> Result<(), Self::Error> {
        self.frame_count += 1;

        // Emit ready with real resolution on first frame
        if self.width == 0 {
            self.width = frame.width();
            self.height = frame.height();
            let title = self.state.window_title.lock().unwrap().clone();
            emit(&Event::Ready {
                window: title,
                width: self.width,
                height: self.height,
            });
        }
        self.width = frame.width();
        self.height = frame.height();

        // Check quit
        if self.state.should_quit.load(Ordering::Relaxed) {
            // Stop any active recording
            if let Some(encoder) = self.encoder.take() {
                let _ = encoder.finish();
                self.emit_recording_stopped();
            }
            capture_control.stop();
            return Ok(());
        }

        // Handle screenshot request
        {
            let mut ss_path = self.state.screenshot_path.lock().unwrap();
            if let Some(path) = ss_path.take() {
                drop(ss_path);
                match frame.save_as_image(&path, windows_capture::frame::ImageFormat::Jpeg) {
                    Ok(_) => emit(&Event::ScreenshotSaved { path }),
                    Err(e) => emit(&Event::Error {
                        message: format!("Screenshot failed: {}", e),
                    }),
                }
            }
        }

        // Handle start recording
        if self.state.should_record.load(Ordering::Relaxed) && self.encoder.is_none() {
            let path = self.state.record_path.lock().unwrap().take();
            let bitrate = self.state.record_bitrate.lock().unwrap().take();
            let encoder_type = self.state.record_encoder.lock().unwrap().take();
            let fps = self.state.record_fps.lock().unwrap().take();
            if let Some(path) = path {
                let br = bitrate.unwrap_or(50_000_000); // 50Mbps default
                let sub_type = match encoder_type.as_deref() {
                    Some("h264") => VideoSettingsSubType::H264,
                    _ => VideoSettingsSubType::HEVC,  // default to HEVC
                };
                let frame_rate = fps.unwrap_or(60);
                match VideoEncoder::new(
                    VideoSettingsBuilder::new(self.width, self.height)
                        .sub_type(sub_type)
                        .bitrate(br)
                        .frame_rate(frame_rate),
                    AudioSettingsBuilder::default().disabled(true),
                    ContainerSettingsBuilder::default(),
                    &path,
                ) {
                    Ok(enc) => {
                        self.encoder = Some(enc);
                        self.recording_path = Some(path.clone());
                        self.recording_start = Some(Instant::now());
                        self.state.encoded_frames.store(0, Ordering::Relaxed);
                        emit(&Event::RecordingStarted { path });
                    }
                    Err(e) => {
                        emit(&Event::Error {
                            message: format!("Encoder init failed: {}", e),
                        });
                        self.state.should_record.store(false, Ordering::Relaxed);
                    }
                }
            }
        }

        // Handle stop recording
        if !self.state.should_record.load(Ordering::Relaxed) && self.encoder.is_some() {
            if let Some(encoder) = self.encoder.take() {
                let _ = encoder.finish();
                self.emit_recording_stopped();
            }
        }

        // Encode frame (zero-copy GPU path)
        if let Some(ref mut encoder) = self.encoder {
            match encoder.send_frame(frame) {
                Ok(_) => {
                    self.state.encoded_frames.fetch_add(1, Ordering::Relaxed);
                }
                Err(e) => {
                    emit(&Event::Error {
                        message: format!("Encode error: {}", e),
                    });
                }
            }
        }

        // OCR frame: fast in menus (~0.25s), slow during recording (~3s)
        let is_recording = self.encoder.is_some();
        let interval = if is_recording {
            self.ocr_interval * 12  // ~3s during recording (just need endgame)
        } else {
            self.ocr_interval       // ~0.25s in menus (responsive detection)
        };
        if self.frame_count % interval == 0 {
            if is_recording {
                // Zero-stall path: double-buffered staging (data is one interval old)
                self.send_ocr_frame_staged(frame);
            } else {
                // Direct path: frame.buffer() — fast and responsive, GPU not under load
                self.send_ocr_frame(frame);
            }
        }

        Ok(())
    }

    fn on_closed(&mut self) -> Result<(), Self::Error> {
        if let Some(encoder) = self.encoder.take() {
            let _ = encoder.finish();
            self.emit_recording_stopped();
        }
        Ok(())
    }
}

impl Recorder {
    fn emit_recording_stopped(&mut self) {
        let duration = self
            .recording_start
            .map(|s| s.elapsed().as_secs_f64())
            .unwrap_or(0.0);
        let frames = self.state.encoded_frames.load(Ordering::Relaxed);
        let path = self.recording_path.take().unwrap_or_default();
        emit(&Event::RecordingStopped {
            path,
            duration,
            frames,
        });
        self.recording_start = None;
    }

    /// Direct OCR frame capture — used in menus when GPU is not under load.
    /// Calls frame.buffer() which does synchronous CopyResource + Map.
    fn send_ocr_frame(&mut self, frame: &mut Frame<'_>) {
        let mut buffer = match frame.buffer() {
            Ok(b) => b,
            Err(_) => return,
        };

        let w = buffer.width() as usize;
        let h = buffer.height() as usize;
        let row_pitch = buffer.row_pitch() as usize;
        let raw: Vec<u8> = buffer.as_raw_buffer().to_vec();
        drop(buffer);

        // Hand off to background OCR thread — non-blocking
        {
            let mut pending = self.state.ocr_pending.lock().unwrap();
            *pending = Some(OcrFrameData { raw, width: w, height: h, row_pitch });
        }
        self.state.ocr_notify.notify_one();
    }

    /// Zero-stall OCR frame capture — used during recording to avoid GPU pipeline stalls.
    /// Uses double-buffered staging: reads the PREVIOUS frame (copy already complete),
    /// then issues an async CopyResource for the current frame.
    fn send_ocr_frame_staged(&mut self, frame: &mut Frame<'_>) {
        let frame_texture = unsafe { frame.as_raw_texture() };

        if let Some(ocr_data) = self.staging_pool.copy_and_read(frame_texture) {
            let mut pending = self.state.ocr_pending.lock().unwrap();
            *pending = Some(ocr_data);
            drop(pending);
            self.state.ocr_notify.notify_one();
        }
        // First call returns None — no previous data yet. That's fine,
        // the next interval (~3s later) will return the first frame.
    }
}

// ---------------------------------------------------------------------------
// Window finder
// ---------------------------------------------------------------------------

fn find_marathon_window() -> Option<Window> {
    let windows = Window::enumerate().ok()?;
    // Log what we see on first call for debugging
    static LOGGED: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);
    if !LOGGED.swap(true, std::sync::atomic::Ordering::Relaxed) {
        for w in &windows {
            let name = w.process_name().unwrap_or_default();
            let title = w.title().unwrap_or_default();
            if !title.is_empty() {
                eprintln!("[recorder] Window: process={} title={}", name, title);
            }
        }
    }
    // Match by process name or window title — exclude our own app (runlog)
    windows.into_iter().find(|w| {
        let name = w.process_name().unwrap_or_default().to_lowercase();
        let title = w.title().unwrap_or_default().to_lowercase();
        // Skip our own windows
        if name.contains("runlog") || title.contains("runlog") || title.contains("marathon-runlog") {
            return false;
        }
        name.contains("marathon") || title == "marathon"
    })
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

fn set_high_priority() {
    use std::ffi::c_void;

    #[link(name = "kernel32")]
    extern "system" {
        fn GetCurrentProcess() -> *mut c_void;
        fn SetPriorityClass(hProcess: *mut c_void, dwPriorityClass: u32) -> i32;
        fn SetProcessInformation(hProcess: *mut c_void, class: u32, info: *const c_void, size: u32) -> i32;
    }

    const ABOVE_NORMAL_PRIORITY_CLASS: u32 = 0x00008000;
    const PROCESS_POWER_THROTTLING: u32 = 4;

    #[repr(C)]
    struct ProcessPowerThrottlingState {
        version: u32,
        control_mask: u32,
        state_mask: u32,
    }

    unsafe {
        let process = GetCurrentProcess();

        // Set process priority to Above Normal
        if SetPriorityClass(process, ABOVE_NORMAL_PRIORITY_CLASS) != 0 {
            eprintln!("[recorder] Process priority: ABOVE_NORMAL");
        }

        // Opt out of Windows 11 power throttling (both timer resolution and execution speed)
        let throttle = ProcessPowerThrottlingState {
            version: 1,
            control_mask: 0x1 | 0x2, // EXECUTION_SPEED | IGNORE_TIMER_RESOLUTION
            state_mask: 0,            // Disable both
        };
        let size = std::mem::size_of::<ProcessPowerThrottlingState>() as u32;
        if SetProcessInformation(process, PROCESS_POWER_THROTTLING, &throttle as *const _ as *const c_void, size) != 0 {
            eprintln!("[recorder] Power throttling: DISABLED");
        }
    }
}

fn set_gpu_priority() {
    // Set GPU scheduling priority to REALTIME — same as OBS
    // Prevents Windows from deprioritizing our GPU work when a fullscreen game is running

    #[link(name = "gdi32")]
    extern "system" {
        fn D3DKMTSetProcessSchedulingPriorityClass(
            hProcess: *mut std::ffi::c_void,
            priority: u32,
        ) -> i32;
    }

    #[link(name = "kernel32")]
    extern "system" {
        fn GetCurrentProcess() -> *mut std::ffi::c_void;
    }

    // D3DKMT_SCHEDULINGPRIORITYCLASS_REALTIME = 5
    const D3DKMT_SCHEDULINGPRIORITYCLASS_REALTIME: u32 = 5;

    unsafe {
        let process = GetCurrentProcess();
        let result = D3DKMTSetProcessSchedulingPriorityClass(
            process,
            D3DKMT_SCHEDULINGPRIORITYCLASS_REALTIME,
        );
        if result == 0 {
            eprintln!("[recorder] GPU priority: REALTIME");
        } else {
            eprintln!("[recorder] GPU priority: failed (code {})", result);
        }
    }
}

fn main() {
    eprintln!("[recorder] runlog-recorder starting...");

    // Prevent Windows from throttling this process when in background
    set_high_priority();
    set_gpu_priority();

    // Wait for Marathon window
    let window = loop {
        if let Some(w) = find_marathon_window() {
            break w;
        }
        std::thread::sleep(std::time::Duration::from_secs(2));
        eprintln!("[recorder] Waiting for Marathon window...");
    };

    let title = window.title().unwrap_or_else(|_| "Marathon".into());
    eprintln!("[recorder] Found window: {}", title);

    // Shared state
    let state = Arc::new(SharedState {
        window_title: Mutex::new(title.clone()),
        should_record: AtomicBool::new(false),
        record_path: Mutex::new(None),
        record_bitrate: Mutex::new(None),
        record_encoder: Mutex::new(None),
        record_fps: Mutex::new(None),
        should_quit: AtomicBool::new(false),
        screenshot_path: Mutex::new(None),
        encoded_frames: AtomicU64::new(0),
        ocr_pending: Mutex::new(None),
        ocr_notify: std::sync::Condvar::new(),
    });

    // OCR processing thread — does the slow work off the capture callback
    let ocr_state = Arc::clone(&state);
    std::thread::spawn(move || {
        loop {
            // Wait for a frame to be available
            let frame_data = {
                let mut pending = ocr_state.ocr_pending.lock().unwrap();
                while pending.is_none() {
                    if ocr_state.should_quit.load(Ordering::Relaxed) {
                        return;
                    }
                    pending = ocr_state.ocr_notify.wait_timeout(pending, std::time::Duration::from_secs(1)).unwrap().0;
                }
                pending.take().unwrap()
            };

            // Full 4K resolution for OCR + screenshot quality
            let ocr_scale = 1;
            let ow = frame_data.width / ocr_scale;
            let oh = frame_data.height / ocr_scale;

            let mut rgb_buf = vec![0u8; ow * oh * 3];
            for y in 0..oh {
                let sy = y * ocr_scale;
                let row_start = sy * frame_data.row_pitch;
                for x in 0..ow {
                    let sx = x * ocr_scale;
                    let si = row_start + sx * 4; // BGRA
                    let di = (y * ow + x) * 3;
                    if si + 2 < frame_data.raw.len() && di + 2 < rgb_buf.len() {
                        rgb_buf[di] = frame_data.raw[si + 2]; // R
                        rgb_buf[di + 1] = frame_data.raw[si + 1]; // G
                        rgb_buf[di + 2] = frame_data.raw[si]; // B
                    }
                }
            }

            // JPEG encode + emit
            let mut jpeg_buf = Vec::with_capacity(64 * 1024);
            let mut encoder = image::codecs::jpeg::JpegEncoder::new_with_quality(&mut jpeg_buf, 85);
            if encoder.encode(&rgb_buf, ow as u32, oh as u32, image::ExtendedColorType::Rgb8).is_ok() {
                use base64::Engine;
                let b64 = base64::engine::general_purpose::STANDARD.encode(&jpeg_buf);
                emit(&Event::Frame { jpeg_base64: b64 });
            }
        }
    });

    // IPC thread — reads commands from stdin
    let ipc_state = Arc::clone(&state);
    std::thread::spawn(move || {
        let stdin = io::stdin();
        for line in stdin.lock().lines() {
            let line = match line {
                Ok(l) => l,
                Err(_) => break,
            };
            if line.trim().is_empty() {
                continue;
            }
            match serde_json::from_str::<Command>(&line) {
                Ok(Command::Start { path, bitrate, encoder, fps }) => {
                    *ipc_state.record_path.lock().unwrap() = Some(path);
                    *ipc_state.record_bitrate.lock().unwrap() = bitrate;
                    *ipc_state.record_encoder.lock().unwrap() = encoder;
                    *ipc_state.record_fps.lock().unwrap() = fps;
                    ipc_state.should_record.store(true, Ordering::Relaxed);
                }
                Ok(Command::Stop) => {
                    ipc_state.should_record.store(false, Ordering::Relaxed);
                }
                Ok(Command::Screenshot { path }) => {
                    *ipc_state.screenshot_path.lock().unwrap() = Some(path);
                }
                Ok(Command::Quit) => {
                    ipc_state.should_quit.store(true, Ordering::Relaxed);
                    break;
                }
                Err(e) => {
                    eprintln!("[recorder] Bad command: {}: {}", line, e);
                }
            }
        }
        // stdin closed — signal quit
        ipc_state.should_quit.store(true, Ordering::Relaxed);
    });

    // Ready event is emitted from on_frame_arrived after first frame (with real resolution)

    // Start capture (blocks this thread)
    let settings = Settings::new(
        window,
        CursorCaptureSettings::WithoutCursor,
        DrawBorderSettings::WithoutBorder,
        SecondaryWindowSettings::Default,
        MinimumUpdateIntervalSettings::Default,
        DirtyRegionSettings::Default,
        ColorFormat::Bgra8,
        Arc::clone(&state),
    );

    match Recorder::start(settings) {
        Ok(_) => eprintln!("[recorder] Capture ended normally"),
        Err(e) => {
            emit(&Event::Error {
                message: format!("Capture failed: {}", e),
            });
            eprintln!("[recorder] Capture error: {}", e);
        }
    }
}
