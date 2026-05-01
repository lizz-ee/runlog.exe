use std::io::{self, BufRead, Write};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

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
// Constants
// ---------------------------------------------------------------------------

/// OCR frame interval in capture frames (~0.5s at 60fps in menus)
const OCR_FRAME_INTERVAL: u64 = 30;
/// Multiplier for OCR interval during recording (~3s at 60fps). RUN_COMPLETE
/// can be visible for only a few seconds, so the staged recording path must
/// sample faster than the shortest expected banner lifetime.
const OCR_RECORD_INTERVAL_MULTIPLIER: u64 = 6;
/// Initial JPEG buffer capacity
const JPEG_BUF_CAPACITY: usize = 64 * 1024;
/// JPEG encoding quality (1-100)
const JPEG_QUALITY: u8 = 85;

// ---------------------------------------------------------------------------
// IPC messages
// ---------------------------------------------------------------------------

#[derive(Deserialize)]
#[serde(tag = "cmd")]
enum Command {
    #[serde(rename = "start")]
    Start {
        path: String,
        bitrate: Option<u32>,
        encoder: Option<String>,
        fps: Option<u32>,
        /// When set, downscale to this height during encode. Width is derived
        /// from the live capture aspect ratio so ultrawide stays correct.
        target_height: Option<u32>,
    },
    #[serde(rename = "stop")]
    Stop,
    #[serde(rename = "screenshot")]
    Screenshot { path: String },
    #[serde(rename = "ocr_fast")]
    OcrFast { enabled: bool },
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
    let json = match serde_json::to_string(event) {
        Ok(j) => j,
        Err(e) => {
            eprintln!("[recorder] Failed to serialize event: {}", e);
            return;
        }
    };
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
    window_title: Mutex<String>,
    should_record: AtomicBool,
    record_path: Mutex<Option<String>>,
    record_bitrate: Mutex<Option<u32>>,
    record_encoder: Mutex<Option<String>>,
    record_fps: Mutex<Option<u32>>,
    /// Target output height (encoder downscales to this, width derived from
    /// live aspect ratio). None = encode at native capture resolution.
    record_target_height: Mutex<Option<u32>>,
    should_quit: AtomicBool,
    screenshot_path: Mutex<Option<String>>,
    encoded_frames: AtomicU64,
    /// Force fast direct OCR even during recording (after RUN_COMPLETE)
    ocr_fast: AtomicBool,
    ocr_pending: Mutex<Option<OcrFrameData>>,
    ocr_notify: std::sync::Condvar,
    /// OCR frame interval (capture frames) — env RUNLOG_OCR_INTERVAL
    ocr_interval_cfg: u64,
    /// OCR JPEG quality (1-100) — env RUNLOG_OCR_QUALITY
    ocr_jpeg_quality: u8,
}

// ---------------------------------------------------------------------------
// Double-buffered staging pool — zero-stall GPU→CPU readback
//
// During recording, we cannot call frame.buffer() (synchronous CopyResource +
// Map) on the hot path without stalling the GPU encoder pipeline. Instead we
// issue an async CopyResource into one staging texture and, on the next OCR
// interval, Map/read the OTHER staging texture whose copy has long since
// completed. Data is one interval old (~3s) — fine for state detection.
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

    fn ensure_staging(&mut self, frame_texture: &ID3D11Texture2D) {
        if self.device.is_none() {
            unsafe {
                let device: ID3D11Device = match frame_texture.GetDevice() {
                    Ok(d) => d,
                    Err(e) => {
                        eprintln!("[recorder] Failed to get D3D11 device: {}", e);
                        return;
                    }
                };
                match device.GetImmediateContext() {
                    Ok(ctx) => {
                        self.context = Some(ctx);
                        self.device = Some(device);
                    }
                    Err(e) => {
                        eprintln!("[recorder] Failed to get D3D11 context: {}", e);
                        return;
                    }
                }
            }
        }

        let mut desc = D3D11_TEXTURE2D_DESC::default();
        unsafe { frame_texture.GetDesc(&mut desc) };

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

    fn copy_and_read(&mut self, frame_texture: &ID3D11Texture2D) -> Option<OcrFrameData> {
        self.ensure_staging(frame_texture);
        let ctx = match self.context.as_ref() {
            Some(c) => c,
            None => return None,
        };

        let read_idx = self.current;
        let write_idx = 1 - self.current;

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
                let total_bytes = match row_pitch.checked_mul(self.height as usize) {
                    Some(t) => t,
                    None => {
                        eprintln!("[recorder] Buffer size overflow: {}x{}", row_pitch, self.height);
                        unsafe { ctx.Unmap(staging, 0) };
                        return None;
                    }
                };
                if mapped.pData.is_null() {
                    eprintln!("[recorder] Map returned null pointer");
                    unsafe { ctx.Unmap(staging, 0) };
                    return None;
                }
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
            None
        };

        let staging_dst = match self.staging[write_idx].as_ref() {
            Some(s) => s,
            None => return result,
        };
        unsafe { ctx.CopyResource(staging_dst, frame_texture) };
        self.ready[write_idx] = true;

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
    ocr_interval: u64,
    staging_pool: StagingPool,
}

impl GraphicsCaptureApiHandler for Recorder {
    type Flags = Arc<SharedState>;
    type Error = Box<dyn std::error::Error + Send + Sync>;

    fn new(ctx: Context<Self::Flags>) -> Result<Self, Self::Error> {
        let interval = ctx.flags.ocr_interval_cfg;
        Ok(Self {
            state: ctx.flags,
            encoder: None,
            recording_path: None,
            recording_start: None,
            frame_count: 0,
            width: 0,
            height: 0,
            ocr_interval: interval,
            staging_pool: StagingPool::new(),
        })
    }

    fn on_frame_arrived(
        &mut self,
        frame: &mut Frame<'_>,
        capture_control: InternalCaptureControl,
    ) -> Result<(), Self::Error> {
        self.frame_count += 1;

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

        if self.state.should_quit.load(Ordering::Acquire) {
            if let Some(encoder) = self.encoder.take() {
                let _ = encoder.finish();
                self.emit_recording_stopped();
            }
            capture_control.stop();
            return Ok(());
        }

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

        // Start recording
        if self.state.should_record.load(Ordering::Acquire) && self.encoder.is_none() {
            let path = self.state.record_path.lock().unwrap().take();
            let bitrate = self.state.record_bitrate.lock().unwrap().take();
            let encoder_type = self.state.record_encoder.lock().unwrap().take();
            let fps = self.state.record_fps.lock().unwrap().take();
            let target_h = self.state.record_target_height.lock().unwrap().take();
            if let Some(path) = path {
                let br = bitrate.unwrap_or(30_000_000).clamp(1_000_000, 300_000_000);
                let sub_type = match encoder_type.as_deref() {
                    Some("h264") => VideoSettingsSubType::H264,
                    _ => VideoSettingsSubType::HEVC,
                };
                let frame_rate = fps.unwrap_or(60).clamp(1, 240);

                // Compute encode dims. If a target height is requested and is
                // smaller than the live capture, MF will downscale during encode
                // and we preserve aspect ratio (rounded to even pixels — the H.264
                // / HEVC encoders require even dimensions).
                let (out_w, out_h) = match target_h {
                    Some(th) if th > 0 && th < self.height && self.height > 0 => {
                        let scaled_w = (self.width as u64 * th as u64 / self.height as u64) as u32;
                        ((scaled_w + 1) & !1, th & !1)
                    }
                    _ => (self.width, self.height),
                };

                match VideoEncoder::new(
                    VideoSettingsBuilder::new(out_w, out_h)
                        .sub_type(sub_type)
                        .bitrate(br)
                        .frame_rate(frame_rate),
                    AudioSettingsBuilder::default().disabled(true),
                    ContainerSettingsBuilder::default(),
                    &path,
                ) {
                    Ok(enc) => {
                        eprintln!("[recorder] Encoder created: capture={}x{} encode={}x{} {:?} {}bps {}fps",
                            self.width, self.height, out_w, out_h, sub_type, br, frame_rate);
                        self.encoder = Some(enc);
                        self.recording_path = Some(path.clone());
                        self.recording_start = Some(Instant::now());
                        self.state.encoded_frames.store(0, Ordering::Relaxed);
                        self.state.ocr_fast.store(false, Ordering::Relaxed);
                        emit(&Event::RecordingStarted { path });
                    }
                    Err(e) => {
                        eprintln!("[recorder] ENCODER INIT FAILED: {} (capture={}x{} encode={}x{} {:?} {}bps {}fps)",
                            e, self.width, self.height, out_w, out_h, sub_type, br, frame_rate);
                        emit(&Event::Error {
                            message: format!("Encoder init failed: {}", e),
                        });
                        self.state.should_record.store(false, Ordering::Release);
                    }
                }
            }
        }

        // Stop recording
        if !self.state.should_record.load(Ordering::Acquire) && self.encoder.is_some() {
            if let Some(encoder) = self.encoder.take() {
                let total = self.state.encoded_frames.load(Ordering::Relaxed);
                eprintln!("[recorder] Stopping encoder — {} frames total", total);
                match encoder.finish() {
                    Ok(_) => eprintln!("[recorder] Encoder finished OK"),
                    Err(e) => eprintln!("[recorder] Encoder finish FAILED: {}", e),
                }
                self.emit_recording_stopped();
            }
        }

        // Encode video frame (zero-copy GPU path)
        if let Some(ref mut encoder) = self.encoder {
            let frames_before = self.state.encoded_frames.load(Ordering::Relaxed);
            match encoder.send_frame(frame) {
                Ok(_) => {
                    let n = self.state.encoded_frames.fetch_add(1, Ordering::Relaxed) + 1;
                    if n <= 3 || n % 300 == 0 {
                        eprintln!("[recorder] Frame {} encoded OK ({}x{})", n, frame.width(), frame.height());
                    }
                }
                Err(e) => {
                    if frames_before < 5 {
                        eprintln!("[recorder] send_frame FAILED at frame {}: {}", frames_before, e);
                    }
                    emit(&Event::Error {
                        message: format!("Encode error: {}", e),
                    });
                }
            }
        }

        // OCR frame capture:
        //   - In menus (no encoder): direct frame.buffer() every ocr_interval (~0.5s)
        //   - During recording: async double-buffered staging every 6*ocr_interval (~3s)
        //   - After RUN_COMPLETE (ocr_fast on): direct path, fast interval
        let is_recording = self.encoder.is_some();
        let ocr_fast = self.state.ocr_fast.load(Ordering::Relaxed);
        let use_staged = is_recording && !ocr_fast;
        let interval = if use_staged {
            self.ocr_interval.saturating_mul(OCR_RECORD_INTERVAL_MULTIPLIER)
        } else {
            self.ocr_interval
        };
        if interval > 0 && self.frame_count % interval == 0 {
            if use_staged {
                self.send_ocr_frame_staged(frame);
            } else {
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
    /// frame.buffer() does a synchronous CopyResource + Map; fine when idle.
    fn send_ocr_frame(&mut self, frame: &mut Frame<'_>) {
        let mut buffer = match frame.buffer() {
            Ok(b) => b,
            Err(e) => {
                eprintln!("[recorder] frame.buffer() failed: {}", e);
                return;
            }
        };

        let w = buffer.width() as usize;
        let h = buffer.height() as usize;
        let row_pitch = buffer.row_pitch() as usize;
        let raw: Vec<u8> = buffer.as_raw_buffer().to_vec();
        drop(buffer);

        {
            let mut pending = self.state.ocr_pending.lock().unwrap();
            *pending = Some(OcrFrameData { raw, width: w, height: h, row_pitch });
        }
        self.state.ocr_notify.notify_one();
    }

    /// Zero-stall OCR during recording via double-buffered staging textures.
    /// Reads the previous frame's staging (copy long since complete) and
    /// issues an async CopyResource for the current frame. No GPU stall.
    fn send_ocr_frame_staged(&mut self, frame: &mut Frame<'_>) {
        let frame_texture = unsafe { frame.as_raw_texture() };

        if let Some(ocr_data) = self.staging_pool.copy_and_read(frame_texture) {
            {
                let mut pending = self.state.ocr_pending.lock().unwrap();
                *pending = Some(ocr_data);
            }
            self.state.ocr_notify.notify_one();
        }
    }
}

// ---------------------------------------------------------------------------
// Window finder
// ---------------------------------------------------------------------------

fn find_marathon_window() -> Option<Window> {
    let windows = Window::enumerate().ok()?;
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
    windows.into_iter().find(|w| {
        let name = w.process_name().unwrap_or_default().to_lowercase();
        let title = w.title().unwrap_or_default().to_lowercase();
        if name.contains("runlog") || title.contains("runlog") || title.contains("marathon-runlog") {
            return false;
        }
        name == "marathon" || name == "marathon.exe" || title == "marathon" || title.starts_with("marathon")
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

    const NORMAL_PRIORITY_CLASS: u32 = 0x00000020;
    const PROCESS_POWER_THROTTLING: u32 = 4;

    #[repr(C)]
    struct ProcessPowerThrottlingState {
        version: u32,
        control_mask: u32,
        state_mask: u32,
    }

    unsafe {
        let process = GetCurrentProcess();

        if SetPriorityClass(process, NORMAL_PRIORITY_CLASS) != 0 {
            eprintln!("[recorder] Process priority: NORMAL");
        }

        let throttle = ProcessPowerThrottlingState {
            version: 1,
            control_mask: 0x1 | 0x2,
            state_mask: 0,
        };
        let size = std::mem::size_of::<ProcessPowerThrottlingState>() as u32;
        if SetProcessInformation(process, PROCESS_POWER_THROTTLING, &throttle as *const _ as *const c_void, size) != 0 {
            eprintln!("[recorder] Power throttling: DISABLED");
        }
    }
}

fn main() {
    eprintln!("[recorder] runlog-recorder starting...");

    set_high_priority();

    let window = loop {
        if let Some(w) = find_marathon_window() {
            break w;
        }
        std::thread::sleep(std::time::Duration::from_secs(2));
        eprintln!("[recorder] Waiting for Marathon window...");
    };

    let title = window.title().unwrap_or_else(|_| "Marathon".into());
    eprintln!("[recorder] Found window: {}", title);

    let ocr_interval_cfg: u64 = std::env::var("RUNLOG_OCR_INTERVAL")
        .ok()
        .and_then(|s| s.parse().ok())
        .map(|n: u64| n.clamp(5, 600))
        .unwrap_or(OCR_FRAME_INTERVAL);
    let ocr_jpeg_quality: u8 = std::env::var("RUNLOG_OCR_QUALITY")
        .ok()
        .and_then(|s| s.parse().ok())
        .map(|n: u8| n.clamp(30, 100))
        .unwrap_or(JPEG_QUALITY);
    eprintln!("[recorder] OCR config: interval={} frames, jpeg_quality={}", ocr_interval_cfg, ocr_jpeg_quality);

    // Cap WGC delivery rate so we don't capture/encode more frames than we keep.
    // Without this, a 90fps game produces 90 captures/sec even though we only
    // write a 60fps file — wasted GPU work that competes with the game.
    let capture_fps: u32 = std::env::var("RUNLOG_CAPTURE_FPS")
        .ok()
        .and_then(|s| s.parse().ok())
        .map(|n: u32| n.clamp(15, 240))
        .unwrap_or(60);
    let min_update_interval = Duration::from_micros(1_000_000 / capture_fps as u64);
    eprintln!("[recorder] Capture rate cap: {}fps ({}us min interval)", capture_fps, min_update_interval.as_micros());

    let state = Arc::new(SharedState {
        window_title: Mutex::new(title.clone()),
        should_record: AtomicBool::new(false),
        record_path: Mutex::new(None),
        record_bitrate: Mutex::new(None),
        record_encoder: Mutex::new(None),
        record_fps: Mutex::new(None),
        record_target_height: Mutex::new(None),
        should_quit: AtomicBool::new(false),
        screenshot_path: Mutex::new(None),
        encoded_frames: AtomicU64::new(0),
        ocr_fast: AtomicBool::new(false),
        ocr_pending: Mutex::new(None),
        ocr_notify: std::sync::Condvar::new(),
        ocr_interval_cfg,
        ocr_jpeg_quality,
    });

    // OCR processing thread
    let ocr_state = Arc::clone(&state);
    std::thread::spawn(move || {
        loop {
            let frame_data = {
                let mut pending = ocr_state.ocr_pending.lock().unwrap();
                while pending.is_none() {
                    if ocr_state.should_quit.load(Ordering::Acquire) {
                        return;
                    }
                    pending = match ocr_state.ocr_notify.wait_timeout(pending, std::time::Duration::from_secs(1)) {
                        Ok((guard, _)) => guard,
                        Err(e) => {
                            eprintln!("[recorder] OCR mutex poisoned, exiting thread: {}", e);
                            return;
                        }
                    };
                }
                pending.take().unwrap()
            };

            if frame_data.row_pitch < frame_data.width * 4 {
                eprintln!("[recorder] Invalid row_pitch: {} < {} * 4", frame_data.row_pitch, frame_data.width);
                continue;
            }

            // Downscale 4K → 1920×1080 for OCR frames — reduces IPC bandwidth ~4x.
            let ocr_scale = if frame_data.width >= 3000 { 2 } else { 1 };
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
                    if si + 3 < frame_data.raw.len() && di + 2 < rgb_buf.len() {
                        rgb_buf[di] = frame_data.raw[si + 2]; // R
                        rgb_buf[di + 1] = frame_data.raw[si + 1]; // G
                        rgb_buf[di + 2] = frame_data.raw[si]; // B
                    }
                }
            }

            let mut jpeg_buf = Vec::with_capacity(JPEG_BUF_CAPACITY);
            let mut encoder = image::codecs::jpeg::JpegEncoder::new_with_quality(&mut jpeg_buf, ocr_state.ocr_jpeg_quality);
            if encoder.encode(&rgb_buf, ow as u32, oh as u32, image::ExtendedColorType::Rgb8).is_ok() {
                use base64::Engine;
                let b64 = base64::engine::general_purpose::STANDARD.encode(&jpeg_buf);
                emit(&Event::Frame { jpeg_base64: b64 });
            }
        }
    });

    // IPC thread
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
                Ok(Command::Start { path, bitrate, encoder, fps, target_height }) => {
                    *ipc_state.record_path.lock().unwrap() = Some(path);
                    *ipc_state.record_bitrate.lock().unwrap() = bitrate;
                    *ipc_state.record_encoder.lock().unwrap() = encoder;
                    *ipc_state.record_fps.lock().unwrap() = fps;
                    *ipc_state.record_target_height.lock().unwrap() = target_height;
                    ipc_state.should_record.store(true, Ordering::Release);
                }
                Ok(Command::Stop) => {
                    ipc_state.should_record.store(false, Ordering::Release);
                }
                Ok(Command::Screenshot { path }) => {
                    *ipc_state.screenshot_path.lock().unwrap() = Some(path);
                }
                Ok(Command::OcrFast { enabled }) => {
                    ipc_state.ocr_fast.store(enabled, Ordering::Relaxed);
                    eprintln!("[recorder] OCR fast mode: {}", if enabled { "ON" } else { "OFF" });
                }
                Ok(Command::Quit) => {
                    ipc_state.should_quit.store(true, Ordering::Release);
                    break;
                }
                Err(e) => {
                    eprintln!("[recorder] Bad command: {}: {}", line, e);
                }
            }
        }
        ipc_state.should_quit.store(true, Ordering::Release);
    });

    // Start capture (blocks this thread)
    let settings = Settings::new(
        window,
        CursorCaptureSettings::WithoutCursor,
        DrawBorderSettings::WithoutBorder,
        SecondaryWindowSettings::Default,
        MinimumUpdateIntervalSettings::Custom(min_update_interval),
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
