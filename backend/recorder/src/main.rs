use std::io::{self, BufRead, Write};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::mpsc;
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
/// can be visible for only a few seconds, so the recording path must sample
/// faster than the shortest expected banner lifetime.
const OCR_RECORD_INTERVAL_MULTIPLIER: u64 = 6;
/// Initial JPEG buffer capacity
const JPEG_BUF_CAPACITY: usize = 64 * 1024;
/// JPEG encoding quality (1-100). Used for OCR region crops and the preview
/// frame; kept high so winocr reads small HUD text cleanly (JPEG artifacts at
/// lower Q hurt thin glyphs). Override per-run with RUNLOG_OCR_QUALITY.
const JPEG_QUALITY: u8 = 95;
/// JPEG quality for full-resolution screenshot saves
const SCREENSHOT_JPEG_QUALITY: u8 = 90;

// Detection runs on the small region crops; full preview frames only feed the
// UI (polled every 2s) and screenshot saves, so they ship on a slow cadence.
// Python can request a fresh one at any time with the `frame_now` command.
/// Full-frame cadence in OCR ticks while in menus (~2s at the 0.5s tick)
const FULL_FRAME_EVERY_MENU_TICKS: u64 = 4;
/// Full-frame cadence in OCR ticks while recording (~6s at the 3s tick)
const FULL_FRAME_EVERY_RECORD_TICKS: u64 = 2;

// ---------------------------------------------------------------------------
// OCR scan regions — must match backend/app/detection/ocr.py
//
// Cropping at the source means the per-tick CPU work (mapped-memory copy,
// BGRA→RGB conversion, JPEG encode, base64, IPC) touches ~18% of the frame
// instead of all of it. The deploy region doubles as the postgame/center
// region on the Python side.
// ---------------------------------------------------------------------------

struct RegionDef {
    name: &'static str,
    x1: f32,
    y1: f32,
    x2: f32,
    y2: f32,
}

const OCR_REGIONS: [RegionDef; 4] = [
    // OCR.LOBBY — bottom center, PREPARE/READY_UP buttons
    RegionDef { name: "lobby", x1: 0.33, y1: 0.72, x2: 0.67, y2: 0.89 },
    // OCR.DEPLOY — center screen, deployment loading screen (also postgame banner)
    RegionDef { name: "deploy", x1: 0.35, y1: 0.38, x2: 0.65, y2: 0.65 },
    // OCR.ENDGAME — upper center, //RUN_COMPLETE banner
    RegionDef { name: "endgame", x1: 0.28, y1: 0.12, x2: 0.72, y2: 0.22 },
    // OCR.KILLFEED — upper left, "[Player] eliminated [Target]" feed (below the
    // timer pill). Scanned during runs to log combat timestamps for Phase 2.
    RegionDef { name: "killfeed", x1: 0.01, y1: 0.15, x2: 0.30, y2: 0.38 },
];

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
    #[serde(rename = "frame_now")]
    FrameNow,
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
    #[serde(rename = "regions")]
    Regions {
        seq: u64,
        lobby: String,
        deploy: String,
        endgame: String,
        killfeed: String,
    },
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

/// Tightly packed (or pitched) BGRA pixels handed to the worker thread.
struct RawImage {
    raw: Vec<u8>,
    width: usize,
    height: usize,
    row_pitch: usize,
}

/// Work shipped from the capture callback to the worker thread. All JPEG
/// encoding, base64, and file I/O happens off the capture hot path.
enum OcrJob {
    Frames {
        /// Downscale factor for OCR/preview output (2 for 4K capture, else 1)
        scale: usize,
        full: Option<RawImage>,
        regions: Vec<(&'static str, RawImage)>,
    },
    SaveScreenshot {
        path: String,
        image: RawImage,
    },
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
    /// Shorten the OCR interval during recording (after RUN_COMPLETE)
    ocr_fast: AtomicBool,
    /// One-shot request for a fresh full preview frame
    frame_now: AtomicBool,
    /// Channel to the OCR/encode worker thread
    ocr_tx: Mutex<mpsc::Sender<OcrJob>>,
    /// OCR frame interval (capture frames) — env RUNLOG_OCR_INTERVAL
    ocr_interval_cfg: u64,
    /// OCR JPEG quality (1-100) — env RUNLOG_OCR_QUALITY
    ocr_jpeg_quality: u8,
}

// ---------------------------------------------------------------------------
// Double-buffered staging pool — zero-stall GPU→CPU readback
//
// We never call frame.buffer() (synchronous CopyResource + Map) on the
// periodic OCR path — not in menus and not while recording — because the
// stall it causes is shared with the game's GPU pipeline. Instead we issue an
// async CopyResource into one staging texture and, on the next OCR interval,
// Map/read the OTHER staging texture whose copy has long since completed.
// Data is one interval old (0.5s in menus, ~3s while recording) — fine for
// state detection. While mapped, we copy out only the bytes the pipeline
// needs: the three OCR scan regions and, on full-frame ticks, a packed full
// copy — not the whole pitched 4K surface every tick.
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

    /// Read the previously copied staging texture (async copy long since
    /// complete — no stall), extracting only the OCR regions plus an optional
    /// packed full frame, then issue the async copy for the current frame.
    fn copy_and_extract(
        &mut self,
        frame_texture: &ID3D11Texture2D,
        want_full: bool,
    ) -> Option<(Option<RawImage>, Vec<(&'static str, RawImage)>)> {
        self.ensure_staging(frame_texture);
        let ctx = self.context.as_ref()?;

        let read_idx = self.current;
        let write_idx = 1 - self.current;

        let mut result = None;
        if self.ready[read_idx] {
            if let Some(staging) = self.staging[read_idx].as_ref() {
                let mut mapped = D3D11_MAPPED_SUBRESOURCE::default();
                let hr = unsafe { ctx.Map(staging, 0, D3D11_MAP_READ, 0, Some(&mut mapped)) };
                if hr.is_ok() {
                    if mapped.pData.is_null() {
                        eprintln!("[recorder] Map returned null pointer");
                    } else {
                        let row_pitch = mapped.RowPitch as usize;
                        let w = self.width as usize;
                        let h = self.height as usize;
                        match row_pitch.checked_mul(h) {
                            Some(total_bytes) if row_pitch >= w * 4 => {
                                let data = unsafe {
                                    std::slice::from_raw_parts(mapped.pData as *const u8, total_bytes)
                                };
                                let mut regions = Vec::with_capacity(OCR_REGIONS.len());
                                for def in &OCR_REGIONS {
                                    if let Some(img) = extract_region(data, row_pitch, w, h, def) {
                                        regions.push((def.name, img));
                                    }
                                }
                                let full = if want_full {
                                    extract_full(data, row_pitch, w, h)
                                } else {
                                    None
                                };
                                result = Some((full, regions));
                            }
                            _ => {
                                eprintln!(
                                    "[recorder] Bad staging dimensions: pitch={} {}x{}",
                                    row_pitch, w, h
                                );
                            }
                        }
                    }
                    unsafe { ctx.Unmap(staging, 0) };
                    self.ready[read_idx] = false;
                }
            }
        }

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

/// Copy one scan region out of a mapped (pitched) BGRA surface into a tightly
/// packed buffer. Per-row memcpy — no per-pixel work on the capture thread.
fn extract_region(data: &[u8], row_pitch: usize, w: usize, h: usize, def: &RegionDef) -> Option<RawImage> {
    let x1 = ((w as f32 * def.x1) as usize).min(w);
    let x2 = ((w as f32 * def.x2) as usize).min(w);
    let y1 = ((h as f32 * def.y1) as usize).min(h);
    let y2 = ((h as f32 * def.y2) as usize).min(h);
    if x2 <= x1 || y2 <= y1 {
        return None;
    }
    let rw = x2 - x1;
    let rh = y2 - y1;
    let mut raw = Vec::with_capacity(rw * rh * 4);
    for y in y1..y2 {
        let start = y * row_pitch + x1 * 4;
        let end = start + rw * 4;
        if end > data.len() {
            return None;
        }
        raw.extend_from_slice(&data[start..end]);
    }
    Some(RawImage { raw, width: rw, height: rh, row_pitch: rw * 4 })
}

/// Copy a full mapped surface into a tightly packed buffer (pitch stripped).
fn extract_full(data: &[u8], row_pitch: usize, w: usize, h: usize) -> Option<RawImage> {
    let mut raw = Vec::with_capacity(w * h * 4);
    for y in 0..h {
        let start = y * row_pitch;
        let end = start + w * 4;
        if end > data.len() {
            return None;
        }
        raw.extend_from_slice(&data[start..end]);
    }
    Some(RawImage { raw, width: w, height: h, row_pitch: w * 4 })
}

/// Synchronous full-frame readback. Stalls the GPU pipeline briefly, so this
/// is reserved for explicit one-shot requests (screenshots, frame_now) that
/// fire on loading/stats screens — never on the periodic detection path.
fn read_frame_raw(frame: &mut Frame<'_>) -> Option<RawImage> {
    let mut buffer = match frame.buffer() {
        Ok(b) => b,
        Err(e) => {
            eprintln!("[recorder] frame.buffer() failed: {}", e);
            return None;
        }
    };
    let width = buffer.width() as usize;
    let height = buffer.height() as usize;
    let row_pitch = buffer.row_pitch() as usize;
    let raw = buffer.as_raw_buffer().to_vec();
    Some(RawImage { raw, width, height, row_pitch })
}

/// BGRA → RGB with optional integer downscale, then JPEG encode.
/// Bounds are validated once up front so the row loops need no per-pixel checks.
fn bgra_to_jpeg(img: &RawImage, scale: usize, quality: u8) -> Option<Vec<u8>> {
    let scale = scale.max(1);
    let ow = img.width / scale;
    let oh = img.height / scale;
    if ow == 0 || oh == 0 {
        return None;
    }
    let last_row_start = (oh - 1) * scale * img.row_pitch;
    if img.row_pitch < img.width * 4 || last_row_start + img.width * 4 > img.raw.len() {
        eprintln!(
            "[recorder] Frame buffer too small: {}x{} pitch={} len={}",
            img.width, img.height, img.row_pitch, img.raw.len()
        );
        return None;
    }

    let mut rgb = vec![0u8; ow * oh * 3];
    for y in 0..oh {
        let src = &img.raw[y * scale * img.row_pitch..][..img.width * 4];
        let dst = &mut rgb[y * ow * 3..][..ow * 3];
        for x in 0..ow {
            let si = x * scale * 4; // BGRA
            let di = x * 3;
            dst[di] = src[si + 2]; // R
            dst[di + 1] = src[si + 1]; // G
            dst[di + 2] = src[si]; // B
        }
    }

    let mut jpeg_buf = Vec::with_capacity(JPEG_BUF_CAPACITY);
    let mut encoder = image::codecs::jpeg::JpegEncoder::new_with_quality(&mut jpeg_buf, quality);
    encoder
        .encode(&rgb, ow as u32, oh as u32, image::ExtendedColorType::Rgb8)
        .ok()?;
    Some(jpeg_buf)
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
    staged_tick: u64,
    /// Consecutive send_frame errors. Used to coalesce the error event so a
    /// persistently failing encoder cannot storm stdout at the frame rate from
    /// inside the capture callback (which would stall frame delivery).
    encode_errors: u64,
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
            staged_tick: 0,
            encode_errors: 0,
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

        let ocr_scale: usize = if self.width >= 3000 { 2 } else { 1 };

        // Screenshot request — raw readback here, JPEG encode + file write on
        // the worker thread (encoding 4K on this callback would stall frame
        // delivery to the video encoder).
        {
            let path_opt = self.state.screenshot_path.lock().unwrap().take();
            if let Some(path) = path_opt {
                match read_frame_raw(frame) {
                    Some(image) => self.queue_job(OcrJob::SaveScreenshot { path, image }),
                    None => emit(&Event::Error {
                        message: "Screenshot failed: could not read frame".into(),
                    }),
                }
            }
        }

        // On-demand fresh full preview frame (Python requests these when a
        // detection hit needs a screenshot — loading/stats screens, never
        // mid-combat). One synchronous readback, encode on the worker thread.
        if self.state.frame_now.swap(false, Ordering::AcqRel) {
            if let Some(img) = read_frame_raw(frame) {
                self.queue_job(OcrJob::Frames {
                    scale: ocr_scale,
                    full: Some(img),
                    regions: Vec::new(),
                });
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
                    self.encode_errors = 0;
                    let n = self.state.encoded_frames.fetch_add(1, Ordering::Relaxed) + 1;
                    if n <= 3 || n % 300 == 0 {
                        eprintln!("[recorder] Frame {} encoded OK ({}x{})", n, frame.width(), frame.height());
                    }
                }
                Err(e) => {
                    self.encode_errors += 1;
                    if frames_before < 5 {
                        eprintln!("[recorder] send_frame FAILED at frame {}: {}", frames_before, e);
                    }
                    // Coalesce: surface only the FIRST error of a failure run to
                    // Python (plus a throttled stderr heartbeat). Emitting on
                    // every frame would flood stdout from the capture hot path at
                    // the frame rate while the encoder is already broken.
                    if self.encode_errors == 1 {
                        emit(&Event::Error {
                            message: format!("Encode error: {}", e),
                        });
                    } else if self.encode_errors % 300 == 0 {
                        eprintln!("[recorder] send_frame still failing after {} consecutive frames: {}", self.encode_errors, e);
                    }
                }
            }
        }

        // OCR capture — always async double-buffered staging, so the GPU
        // pipeline is never stalled by detection, in menus or in game:
        //   - Menus (no encoder): every ocr_interval (~0.5s)
        //   - Recording: every 6*ocr_interval (~3s)
        //   - After RUN_COMPLETE (ocr_fast): every ocr_interval, full frame each tick
        let is_recording = self.encoder.is_some();
        let ocr_fast = self.state.ocr_fast.load(Ordering::Relaxed);
        let interval = if is_recording && !ocr_fast {
            self.ocr_interval.saturating_mul(OCR_RECORD_INTERVAL_MULTIPLIER)
        } else {
            self.ocr_interval
        };
        if interval > 0 && self.frame_count % interval == 0 {
            let want_full = if ocr_fast {
                true
            } else if is_recording {
                self.staged_tick % FULL_FRAME_EVERY_RECORD_TICKS == 0
            } else {
                self.staged_tick % FULL_FRAME_EVERY_MENU_TICKS == 0
            };
            self.staged_tick += 1;
            let frame_texture = unsafe { frame.as_raw_texture() };
            if let Some((full, regions)) = self.staging_pool.copy_and_extract(frame_texture, want_full) {
                self.queue_job(OcrJob::Frames { scale: ocr_scale, full, regions });
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

    fn queue_job(&self, job: OcrJob) {
        if let Ok(tx) = self.state.ocr_tx.lock() {
            let _ = tx.send(job);
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

/// Configure the recorder PROCESS scheduling: NORMAL priority class (NOT high —
/// we never want the recorder to starve the game) plus EcoQoS / power throttling
/// DISABLED so the capture+encode pipeline is never parked on an E-core or
/// clocked down mid-recording. (Despite the legacy name, this never set HIGH.)
fn configure_process_priority() {
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

/// Drop the OCR/encode worker below normal priority — its JPEG bursts must
/// never preempt the game, the capture callback, or the video encoder.
fn set_ocr_thread_priority() {
    use std::ffi::c_void;

    #[link(name = "kernel32")]
    extern "system" {
        fn GetCurrentThread() -> *mut c_void;
        fn SetThreadPriority(hThread: *mut c_void, nPriority: i32) -> i32;
    }

    const THREAD_PRIORITY_BELOW_NORMAL: i32 = -1;

    unsafe {
        if SetThreadPriority(GetCurrentThread(), THREAD_PRIORITY_BELOW_NORMAL) != 0 {
            eprintln!("[recorder] OCR thread priority: BELOW_NORMAL");
        }
    }
}

/// Nudge the WGC message-pump / capture thread (this thread, which blocks in
/// Recorder::start) just above the game's base priority so a busy system cannot
/// preempt frame delivery between WGC callbacks. Insurance for CPU contention
/// only — it does nothing for GPU/NVENC saturation, where send_frame blocks on
/// the GPU regardless of thread priority.
fn set_capture_thread_above_normal() {
    use std::ffi::c_void;

    #[link(name = "kernel32")]
    extern "system" {
        fn GetCurrentThread() -> *mut c_void;
        fn SetThreadPriority(hThread: *mut c_void, nPriority: i32) -> i32;
    }

    const THREAD_PRIORITY_ABOVE_NORMAL: i32 = 1;

    unsafe {
        if SetThreadPriority(GetCurrentThread(), THREAD_PRIORITY_ABOVE_NORMAL) != 0 {
            eprintln!("[recorder] Capture/pump thread priority: ABOVE_NORMAL");
        }
    }
}

fn main() {
    eprintln!("[recorder] runlog-recorder starting...");

    configure_process_priority();

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

    let (ocr_tx, ocr_rx) = mpsc::channel::<OcrJob>();

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
        frame_now: AtomicBool::new(false),
        ocr_tx: Mutex::new(ocr_tx),
        ocr_interval_cfg,
        ocr_jpeg_quality,
    });

    // OCR/encode worker thread — all BGRA→RGB conversion, JPEG encode, base64,
    // and screenshot file writes happen here, never on the capture callback.
    let ocr_state = Arc::clone(&state);
    std::thread::spawn(move || {
        set_ocr_thread_priority();
        let quality = ocr_state.ocr_jpeg_quality;
        let mut seq: u64 = 0;
        loop {
            let job = match ocr_rx.recv_timeout(Duration::from_secs(1)) {
                Ok(j) => j,
                Err(mpsc::RecvTimeoutError::Timeout) => {
                    if ocr_state.should_quit.load(Ordering::Acquire) {
                        return;
                    }
                    continue;
                }
                Err(mpsc::RecvTimeoutError::Disconnected) => return,
            };
            use base64::Engine;
            match job {
                OcrJob::Frames { scale, full, regions } => {
                    if !regions.is_empty() {
                        let mut lobby = String::new();
                        let mut deploy = String::new();
                        let mut endgame = String::new();
                        let mut killfeed = String::new();
                        for (name, img) in &regions {
                            if let Some(jpeg) = bgra_to_jpeg(img, scale, quality) {
                                let b64 = base64::engine::general_purpose::STANDARD.encode(&jpeg);
                                match *name {
                                    "lobby" => lobby = b64,
                                    "deploy" => deploy = b64,
                                    "endgame" => endgame = b64,
                                    "killfeed" => killfeed = b64,
                                    _ => {}
                                }
                            }
                        }
                        if !(lobby.is_empty() && deploy.is_empty() && endgame.is_empty()) {
                            seq += 1;
                            emit(&Event::Regions { seq, lobby, deploy, endgame, killfeed });
                        }
                    }
                    if let Some(img) = full {
                        if let Some(jpeg) = bgra_to_jpeg(&img, scale, quality) {
                            let b64 = base64::engine::general_purpose::STANDARD.encode(&jpeg);
                            emit(&Event::Frame { jpeg_base64: b64 });
                        }
                    }
                }
                OcrJob::SaveScreenshot { path, image } => {
                    match bgra_to_jpeg(&image, 1, SCREENSHOT_JPEG_QUALITY) {
                        Some(jpeg) => match std::fs::write(&path, &jpeg) {
                            Ok(_) => emit(&Event::ScreenshotSaved { path }),
                            Err(e) => emit(&Event::Error {
                                message: format!("Screenshot save failed: {}", e),
                            }),
                        },
                        None => emit(&Event::Error {
                            message: "Screenshot encode failed".into(),
                        }),
                    }
                }
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
                Ok(Command::FrameNow) => {
                    ipc_state.frame_now.store(true, Ordering::Release);
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

    // This thread becomes the WGC message pump / capture thread inside start().
    set_capture_thread_above_normal();

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
