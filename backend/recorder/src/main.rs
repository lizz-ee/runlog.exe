use std::fs::File;
use std::io::{self, BufRead, BufWriter, Seek, SeekFrom, Write};
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


// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/// OCR frame interval in capture frames (~0.5s at 60fps in menus)
/// winocr is ~16ms so 2fps is more than enough for state transitions
const OCR_FRAME_INTERVAL: u64 = 30;
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
    Start { path: String, bitrate: Option<u32>, encoder: Option<String>, fps: Option<u32> },
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

// ---------------------------------------------------------------------------
// WAV file writer — writes PCM int16 audio directly to disk
// ---------------------------------------------------------------------------

struct WavWriter {
    writer: BufWriter<File>,
    data_bytes: u32,
    sample_rate: u32,
    channels: u16,
}

impl WavWriter {
    fn new(path: &str, sample_rate: u32, channels: u16) -> std::io::Result<Self> {
        let file = File::create(path)?;
        let mut writer = BufWriter::new(file);
        // Write placeholder header — finalized on close
        Self::write_header(&mut writer, sample_rate, channels, 0)?;
        Ok(Self { writer, data_bytes: 0, sample_rate, channels })
    }

    fn write_samples(&mut self, pcm: &[u8]) -> std::io::Result<()> {
        self.writer.write_all(pcm)?;
        self.data_bytes += pcm.len() as u32;
        Ok(())
    }

    fn finish(mut self) -> std::io::Result<()> {
        self.writer.flush()?;
        // Seek back and rewrite header with correct sizes
        self.writer.seek(SeekFrom::Start(0))?;
        Self::write_header(&mut self.writer, self.sample_rate, self.channels, self.data_bytes)?;
        self.writer.flush()?;
        Ok(())
    }

    fn write_header(w: &mut impl Write, sample_rate: u32, channels: u16, data_bytes: u32) -> std::io::Result<()> {
        let bits_per_sample: u16 = 16;
        let block_align = channels * (bits_per_sample / 8);
        let byte_rate = sample_rate * block_align as u32;
        let file_size = 36 + data_bytes;
        w.write_all(b"RIFF")?;
        w.write_all(&file_size.to_le_bytes())?;
        w.write_all(b"WAVE")?;
        w.write_all(b"fmt ")?;
        w.write_all(&16u32.to_le_bytes())?;         // chunk size
        w.write_all(&1u16.to_le_bytes())?;           // PCM format
        w.write_all(&channels.to_le_bytes())?;
        w.write_all(&sample_rate.to_le_bytes())?;
        w.write_all(&byte_rate.to_le_bytes())?;
        w.write_all(&block_align.to_le_bytes())?;
        w.write_all(&bits_per_sample.to_le_bytes())?;
        w.write_all(b"data")?;
        w.write_all(&data_bytes.to_le_bytes())?;
        Ok(())
    }
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
    /// Force fast direct OCR even during recording (after RUN_COMPLETE)
    ocr_fast: AtomicBool,
    /// OCR frame buffer — callback copies raw pixels here, bg thread processes
    ocr_pending: Mutex<Option<OcrFrameData>>,
    ocr_notify: std::sync::Condvar,
    /// OCR thread health — set to false if the thread exits
    ocr_thread_alive: AtomicBool,
    /// WAV file writer — audio thread writes PCM directly to disk when recording
    wav_writer: Mutex<Option<WavWriter>>,
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
    /// Send OCR frames every N capture frames (menus only)
    ocr_interval: u64,
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
            ocr_interval: OCR_FRAME_INTERVAL, // ~0.5s at 60fps in menus
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
        if self.state.should_quit.load(Ordering::Acquire) {
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
        if self.state.should_record.load(Ordering::Acquire) && self.encoder.is_none() {
            let path = self.state.record_path.lock().unwrap().take();
            let bitrate = self.state.record_bitrate.lock().unwrap().take();
            let encoder_type = self.state.record_encoder.lock().unwrap().take();
            let fps = self.state.record_fps.lock().unwrap().take();
            if let Some(path) = path {
                let br = bitrate.unwrap_or(50_000_000).clamp(1_000_000, 300_000_000);
                let sub_type = match encoder_type.as_deref() {
                    Some("h264") => VideoSettingsSubType::H264,
                    _ => VideoSettingsSubType::HEVC,  // default to HEVC
                };
                let frame_rate = fps.unwrap_or(60).clamp(1, 240);

                // Video-only encoder — audio goes to separate WAV via WASAPI loopback
                let audio_settings = AudioSettingsBuilder::default().disabled(true);

                match VideoEncoder::new(
                    VideoSettingsBuilder::new(self.width, self.height)
                        .sub_type(sub_type)
                        .bitrate(br)
                        .frame_rate(frame_rate),
                    audio_settings,
                    ContainerSettingsBuilder::default(),
                    &path,
                ) {
                    Ok(enc) => {
                        eprintln!("[recorder] Encoder created: {}x{} {:?} {}bps {}fps",
                            self.width, self.height, sub_type, br, frame_rate);
                        self.encoder = Some(enc);
                        self.recording_path = Some(path.clone());
                        self.recording_start = Some(Instant::now());
                        self.state.encoded_frames.store(0, Ordering::Relaxed);
                        self.state.ocr_fast.store(false, Ordering::Relaxed);
                        // Open WAV file for audio capture alongside video
                        let wav_path = path.replace(".mp4", ".wav");
                        match WavWriter::new(&wav_path, 48000, 2) {
                            Ok(w) => {
                                *self.state.wav_writer.lock().unwrap() = Some(w);
                                eprintln!("[recorder] WAV audio: {}", wav_path);
                            }
                            Err(e) => eprintln!("[recorder] WAV open failed (no audio): {}", e),
                        }
                        emit(&Event::RecordingStarted { path });
                    }
                    Err(e) => {
                        eprintln!("[recorder] ENCODER INIT FAILED: {} ({}x{} {:?} {}bps {}fps)",
                            e, self.width, self.height, sub_type, br, frame_rate);
                        emit(&Event::Error {
                            message: format!("Encoder init failed: {}", e),
                        });
                        self.state.should_record.store(false, Ordering::Release);
                    }
                }
            }
        }

        // Handle stop recording
        if !self.state.should_record.load(Ordering::Acquire) && self.encoder.is_some() {
            if let Some(encoder) = self.encoder.take() {
                let total = self.state.encoded_frames.load(Ordering::Relaxed);
                eprintln!("[recorder] Stopping encoder — {} frames total", total);
                // Finalize WAV audio file
                if let Some(wav) = self.state.wav_writer.lock().unwrap().take() {
                    match wav.finish() {
                        Ok(_) => eprintln!("[recorder] WAV audio finalized"),
                        Err(e) => eprintln!("[recorder] WAV finalize failed: {}", e),
                    }
                }
                match encoder.finish() {
                    Ok(_) => eprintln!("[recorder] Encoder finished OK"),
                    Err(e) => eprintln!("[recorder] Encoder finish FAILED: {}", e),
                }
                self.emit_recording_stopped();
            }
        }

        // Encode video frame (audio goes to WAV via WASAPI thread)
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

        // OCR frames: menus only — during recording Python uses mss screenshots
        // so the recording pipeline has zero GPU readbacks beyond encoding.
        let is_recording = self.encoder.is_some();
        if !is_recording && self.frame_count % self.ocr_interval == 0 {
            self.send_ocr_frame(frame);
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

        // Hand off to background OCR thread — non-blocking
        {
            let mut pending = self.state.ocr_pending.lock().unwrap();
            *pending = Some(OcrFrameData { raw, width: w, height: h, row_pitch });
        }
        self.state.ocr_notify.notify_one();
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

    // NORMAL priority — encoding is handled on GPU, no need to compete with the game for CPU.
    // Power throttle opt-out stays: prevents Windows 11 efficiency mode from degrading frame timing.
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

        // Normal priority — GPU handles encoding, no need to compete with the game.
        if SetPriorityClass(process, NORMAL_PRIORITY_CLASS) != 0 {
            eprintln!("[recorder] Process priority: NORMAL");
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

// ---------------------------------------------------------------------------
// WASAPI loopback audio capture
// ---------------------------------------------------------------------------

/// Captures system audio (loopback from the default render device) and pushes
/// raw int16-stereo-48kHz PCM chunks into `state.pending_audio`.
/// The capture callback drains this queue before each video frame for A/V sync.
fn run_audio_capture(state: Arc<SharedState>) {
    use windows::Win32::Media::Audio::{
        IAudioCaptureClient, IAudioClient, IMMDeviceEnumerator, MMDeviceEnumerator,
        AUDCLNT_SHAREMODE_SHARED, AUDCLNT_STREAMFLAGS_LOOPBACK, eConsole, eRender,
    };
    use windows::Win32::System::Com::{
        CoCreateInstance, CoInitializeEx, CLSCTX_ALL, COINIT_MULTITHREADED,
    };

    unsafe {
        // Init COM for this thread — HRESULT<0 means failure (S_FALSE=1 is fine)
        let hr = CoInitializeEx(None, COINIT_MULTITHREADED);
        if hr.0 < 0 {
            eprintln!("[audio] CoInitializeEx failed: 0x{:08x}", hr.0 as u32);
            return;
        }

        // Guard: ensure CoUninitialize runs when this scope exits
        struct ComGuard;
        impl Drop for ComGuard {
            fn drop(&mut self) {
                unsafe {
                    windows::Win32::System::Com::CoUninitialize();
                }
            }
        }
        let _com_guard = ComGuard;

        // Get default render (output) device enumerator
        let enumerator: IMMDeviceEnumerator =
            match CoCreateInstance(&MMDeviceEnumerator, None, CLSCTX_ALL) {
                Ok(e) => e,
                Err(e) => {
                    eprintln!("[audio] CoCreateInstance(IMMDeviceEnumerator) failed: {}", e);
                    return;
                }
            };

        // Default render endpoint — this is where the game's audio plays out
        let device = match enumerator.GetDefaultAudioEndpoint(eRender, eConsole) {
            Ok(d) => d,
            Err(e) => {
                eprintln!("[audio] GetDefaultAudioEndpoint failed: {}", e);
                return;
            }
        };

        // Activate IAudioClient on the render endpoint
        let audio_client: IAudioClient = match device.Activate(CLSCTX_ALL, None) {
            Ok(c) => c,
            Err(e) => {
                eprintln!("[audio] IAudioClient activate failed: {}", e);
                return;
            }
        };

        // Get the endpoint's native mix format (shared mode must use this)
        let mix_fmt_ptr = match audio_client.GetMixFormat() {
            Ok(f) => f,
            Err(e) => {
                eprintln!("[audio] GetMixFormat failed: {}", e);
                return;
            }
        };

        let channels = (*mix_fmt_ptr).nChannels as usize;
        let bits = (*mix_fmt_ptr).wBitsPerSample;
        let sample_rate = (*mix_fmt_ptr).nSamplesPerSec;
        eprintln!("[audio] Mix format: {}ch  {}Hz  {}bit", channels, sample_rate, bits);

        // Initialize for loopback — shared mode, render endpoint, loopback flag
        let init_result = audio_client.Initialize(
            AUDCLNT_SHAREMODE_SHARED,
            AUDCLNT_STREAMFLAGS_LOOPBACK,
            2_000_000i64, // hnsBufferDuration: 200ms in 100ns units
            0i64,          // hnsPeriodicity: 0 = OS default for shared mode
            mix_fmt_ptr,
            None,
        );

        // Free COM-allocated mix format — must happen after Initialize call
        windows::Win32::System::Com::CoTaskMemFree(Some(mix_fmt_ptr as *const _ as *const std::ffi::c_void));

        if let Err(e) = init_result {
            eprintln!("[audio] IAudioClient::Initialize failed: {}", e);
            return;
        }

        let capture_client: IAudioCaptureClient = match audio_client.GetService() {
            Ok(c) => c,
            Err(e) => {
                eprintln!("[audio] GetService(IAudioCaptureClient) failed: {}", e);
                return;
            }
        };

        if let Err(e) = audio_client.Start() {
            eprintln!("[audio] IAudioClient::Start failed: {}", e);
            return;
        }

        eprintln!("[audio] WASAPI loopback capture started ({}ch {}Hz {}bit) — writing to WAV when recording", channels, sample_rate, bits);

        // AUDCLNT_BUFFERFLAGS_SILENT (0x2) — data is silence, skip it
        const SILENT: u32 = 0x2;

        loop {
            if state.should_quit.load(Ordering::Acquire) {
                break;
            }

            let recording = state.should_record.load(Ordering::Acquire);

            // Poll for available frames
            let packet_size = match capture_client.GetNextPacketSize() {
                Ok(s) => s,
                Err(e) => {
                    eprintln!("[audio] GetNextPacketSize failed: {}", e);
                    std::thread::sleep(std::time::Duration::from_millis(10));
                    continue;
                }
            };

            if packet_size == 0 {
                std::thread::sleep(std::time::Duration::from_millis(10));
                continue;
            }

            let mut data: *mut u8 = std::ptr::null_mut();
            let mut num_frames: u32 = 0;
            let mut flags: u32 = 0;
            let mut qpc_pos: u64 = 0;

            if let Err(e) = capture_client.GetBuffer(
                &mut data,
                &mut num_frames,
                &mut flags,
                None,
                Some(&mut qpc_pos),
            ) {
                eprintln!("[audio] GetBuffer failed: {}", e);
                continue;
            }

            if data.is_null() {
                let _ = capture_client.ReleaseBuffer(num_frames);
                continue;
            }

            if recording && (flags & SILENT) == 0 && num_frames > 0 {
                // qpc_pos is already in 100ns units (Windows converts for us)
                let num_samples = num_frames as usize * channels;

                let pcm: Vec<u8> = if bits == 32 {
                    // float32 → int16
                    let floats = std::slice::from_raw_parts(data as *const f32, num_samples);
                    let mut out = Vec::with_capacity(num_samples * 2);
                    for &f in floats {
                        let s = (f.clamp(-1.0, 1.0) * 32767.0) as i16;
                        out.extend_from_slice(&s.to_le_bytes());
                    }
                    out
                } else if bits == 16 {
                    // already int16 — copy raw bytes
                    std::slice::from_raw_parts(data, num_samples * 2).to_vec()
                } else {
                    Vec::new()
                };

                if !pcm.is_empty() {
                    if let Some(ref mut wav) = *state.wav_writer.lock().unwrap() {
                        if let Err(e) = wav.write_samples(&pcm) {
                            eprintln!("[audio] WAV write failed: {}", e);
                        }
                    }
                }
            }

            let _ = capture_client.ReleaseBuffer(num_frames);
        }

        let _ = audio_client.Stop();
        eprintln!("[audio] WASAPI loopback stopped");
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
        ocr_fast: AtomicBool::new(false),
        ocr_pending: Mutex::new(None),
        ocr_notify: std::sync::Condvar::new(),
        ocr_thread_alive: AtomicBool::new(true),
        wav_writer: Mutex::new(None),
    });

    // OCR processing thread — does the slow work off the capture callback
    let ocr_state = Arc::clone(&state);
    std::thread::spawn(move || {
        loop {
            // Wait for a frame to be available
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
                            ocr_state.ocr_thread_alive.store(false, Ordering::Relaxed);
                            return;
                        }
                    };
                }
                pending.take().unwrap()
            };

            // Validate row_pitch before processing
            if frame_data.row_pitch < frame_data.width * 4 {
                eprintln!("[recorder] Invalid row_pitch: {} < {} * 4", frame_data.row_pitch, frame_data.width);
                continue;
            }

            // Downscale 4K → 1920×1080 for OCR frames — reduces IPC bandwidth ~4x.
            // Python upscales individual crops further as needed before calling winocr.
            // At 1080p (width < 3000) no downscale needed, scale stays 1.
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

            // JPEG encode + emit
            let mut jpeg_buf = Vec::with_capacity(JPEG_BUF_CAPACITY);
            let mut encoder = image::codecs::jpeg::JpegEncoder::new_with_quality(&mut jpeg_buf, JPEG_QUALITY);
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
        // stdin closed — signal quit
        ipc_state.should_quit.store(true, Ordering::Release);
    });

    // Audio capture thread — WASAPI loopback from the default render device
    let audio_state = Arc::clone(&state);
    std::thread::spawn(move || {
        run_audio_capture(audio_state);
        eprintln!("[audio] Audio capture thread exited");
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
