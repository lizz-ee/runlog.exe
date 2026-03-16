/**
 * Recording Manager — Continuous screen recording via FFmpeg.
 *
 * Uses DXGI Desktop Duplication (ddagrab) with NVENC GPU encoding for
 * zero-cost 60 FPS recording. Maintains a rolling 3-minute buffer of
 * 30-second segments and extracts 1 JPEG keyframe per second for the
 * detection system.
 *
 * Clips can be extracted from the buffer on demand without re-encoding.
 */

const { spawn, execSync, execFile } = require('child_process')
const path = require('path')
const fs = require('fs')
const { app } = require('electron')

const isDev = !app.isPackaged

// Buffer config
const SEGMENT_DURATION = 30        // seconds per segment
const BUFFER_DURATION = 180        // 3 minutes rolling buffer
const CLEANUP_INTERVAL = 10000     // cleanup every 10s
const MARATHON_CHECK_INTERVAL = 5000 // check if Marathon running every 5s
const MARATHON_STOP_DELAY = 30000  // wait 30s before stopping if Marathon exits

class RecordingManager {
  constructor(config, onStatus) {
    this.config = {
      segmentsDir: config.segmentsDir,
      keyframesDir: config.keyframesDir,
      clipsDir: config.clipsDir,
    }
    this.onStatus = onStatus || (() => {})
    this.ffmpegProcess = null
    this.ffmpegPath = null
    this.encoder = null
    this.captureMethod = null
    this.isRecording = false
    this.cleanupTimer = null
    this.marathonTimer = null
    this._stopTimeout = null
    this._resolution = null
  }

  /**
   * Start the recording manager. Begins monitoring for Marathon.
   */
  async start() {
    // Find FFmpeg
    this.ffmpegPath = this._findFFmpeg()
    if (!this.ffmpegPath) {
      this.onStatus('error', 'FFmpeg not found')
      return false
    }
    this.onStatus('ready', `FFmpeg: ${this.ffmpegPath}`)

    // Detect encoder
    this.encoder = await this._detectEncoder()
    this.onStatus('ready', `Encoder: ${this.encoder}`)

    // Detect capture method
    this.captureMethod = await this._detectCaptureMethod()
    this.onStatus('ready', `Capture: ${this.captureMethod}`)

    // Detect screen resolution
    this._resolution = this._getScreenResolution()
    this.onStatus('ready', `Resolution: ${this._resolution.w}x${this._resolution.h}`)

    // Create directories
    for (const dir of Object.values(this.config)) {
      fs.mkdirSync(dir, { recursive: true })
    }

    // Start Marathon monitoring loop
    this._startMarathonMonitor()
    this.onStatus('monitoring', 'Waiting for Marathon...')

    return true
  }

  /**
   * Stop everything — recording and monitoring.
   */
  stop() {
    if (this.marathonTimer) {
      clearInterval(this.marathonTimer)
      this.marathonTimer = null
    }
    if (this._stopTimeout) {
      clearTimeout(this._stopTimeout)
      this._stopTimeout = null
    }
    this._stopFFmpeg()
    this.onStatus('stopped', 'Recording manager stopped')
  }

  isActive() {
    return this.isRecording
  }

  getStatus() {
    return {
      active: this.isRecording,
      encoder: this.encoder,
      captureMethod: this.captureMethod,
      resolution: this._resolution,
      segmentsDir: this.config.segmentsDir,
      keyframesDir: this.config.keyframesDir,
      clipsDir: this.config.clipsDir,
    }
  }

  /**
   * Get path to the most recent keyframe JPEG.
   */
  getLatestKeyframe() {
    try {
      const files = fs.readdirSync(this.config.keyframesDir)
        .filter(f => f.endsWith('.jpg'))
        .sort()
      if (files.length === 0) return null
      return path.join(this.config.keyframesDir, files[files.length - 1])
    } catch {
      return null
    }
  }

  /**
   * Extract a clip from the rolling buffer segments.
   * @param {number} eventTimestamp - When the event occurred (ms since epoch)
   * @param {number} beforeSec - Seconds before event to include
   * @param {number} afterSec - Seconds after event to include
   * @param {object} metadata - Event info (event type, etc.)
   * @returns {object|null} Clip info or null if failed
   */
  async saveClip(eventTimestamp, beforeSec = 20, afterSec = 5, metadata = {}) {
    const clipStart = eventTimestamp - (beforeSec * 1000)
    const clipEnd = eventTimestamp + (afterSec * 1000)

    // Find segments that overlap with clip time range
    const segments = this._getSegmentsInRange(clipStart, clipEnd)
    if (segments.length === 0) {
      console.log('[recording] No segments found for clip range')
      return null
    }

    // Create concat file
    const concatListPath = path.join(this.config.segmentsDir, '_concat.txt')
    const concatContent = segments.map(s => `file '${s.replace(/\\/g, '/')}'`).join('\n')
    fs.writeFileSync(concatListPath, concatContent)

    // Calculate seek offset
    const firstSegTime = this._parseSegmentTimestamp(segments[0])
    const offsetSec = Math.max(0, (clipStart - firstSegTime) / 1000)
    const durationSec = beforeSec + afterSec

    const eventType = metadata.event || 'event'
    const clipFilename = `clip_${eventType}_${Date.now()}.mp4`
    const clipPath = path.join(this.config.clipsDir, clipFilename)

    try {
      await this._execFFmpeg([
        '-f', 'concat', '-safe', '0',
        '-i', concatListPath,
        '-ss', String(offsetSec),
        '-t', String(durationSec),
        '-c', 'copy',
        '-movflags', '+faststart',
        clipPath,
      ])

      fs.unlinkSync(concatListPath)

      const stat = fs.statSync(clipPath)
      console.log(`[recording] Clip saved: ${clipFilename} (${(stat.size / 1024 / 1024).toFixed(1)}MB)`)

      return {
        path: clipPath,
        filename: clipFilename,
        duration: durationSec,
        fileSize: stat.size,
        eventType,
      }
    } catch (err) {
      console.error('[recording] Clip extraction failed:', err.message)
      try { fs.unlinkSync(concatListPath) } catch {}
      return null
    }
  }

  // ── FFmpeg Process Management ──────────────────────────────────────

  _startFFmpeg() {
    if (this.isRecording) return

    const { w, h } = this._resolution
    const segmentsDir = this.config.segmentsDir
    const keyframesDir = this.config.keyframesDir

    // Build FFmpeg args based on capture method
    let inputArgs
    if (this.captureMethod === 'ddagrab') {
      inputArgs = [
        '-f', 'lavfi',
        '-i', `ddagrab=framerate=60:output_idx=0`,
      ]
    } else {
      inputArgs = [
        '-f', 'gdigrab',
        '-framerate', '60',
        '-video_size', `${w}x${h}`,
        '-i', 'desktop',
      ]
    }

    // Encoder args
    let encoderArgs
    if (this.encoder === 'h264_nvenc') {
      encoderArgs = [
        '-c:v', 'h264_nvenc',
        '-preset', 'p4',
        '-tune', 'll',
        '-rc', 'vbr',
        '-cq', '23',
        '-b:v', '15M',
        '-maxrate', '20M',
        '-bufsize', '30M',
      ]
    } else {
      encoderArgs = [
        '-c:v', 'libx264',
        '-preset', 'ultrafast',
        '-tune', 'zerolatency',
        '-crf', '23',
      ]
    }

    // Keyframe interval: 1 per second at 60fps
    const gopArgs = ['-g', '60', '-keyint_min', '60']

    // Full command: split input → segments + keyframes
    const segPattern = path.join(segmentsDir, 'seg_%Y%m%d_%H%M%S.mp4').replace(/\\/g, '/')
    const kfPattern = path.join(keyframesDir, 'kf_%04d.jpg').replace(/\\/g, '/')

    const args = [
      '-y',
      '-hide_banner',
      '-loglevel', 'warning',
      ...inputArgs,
      '-filter_complex', '[0:v]split=2[seg][kf]',
      // Output 1: segmented video
      '-map', '[seg]',
      ...encoderArgs,
      ...gopArgs,
      '-f', 'segment',
      '-segment_time', String(SEGMENT_DURATION),
      '-segment_format', 'mp4',
      '-reset_timestamps', '1',
      '-strftime', '1',
      segPattern,
      // Output 2: keyframe JPEGs (1 per second)
      '-map', '[kf]',
      '-vf', 'fps=1',
      '-c:v', 'mjpeg',
      '-q:v', '5',
      '-f', 'image2',
      '-update', '1',
      path.join(keyframesDir, 'latest.jpg').replace(/\\/g, '/'),
    ]

    console.log(`[recording] Starting FFmpeg: ${this.encoder} @ ${w}x${h} 60fps`)
    console.log(`[recording] Segments: ${segmentsDir}`)
    console.log(`[recording] Keyframes: ${keyframesDir}`)

    this.ffmpegProcess = spawn(this.ffmpegPath, args, {
      stdio: ['pipe', 'pipe', 'pipe'],
      windowsHide: true,
    })

    this.ffmpegProcess.stdout.on('data', (data) => {
      console.log(`[ffmpeg] ${data.toString().trim()}`)
    })

    this.ffmpegProcess.stderr.on('data', (data) => {
      const msg = data.toString().trim()
      if (msg && !msg.startsWith('frame=')) {
        console.log(`[ffmpeg] ${msg}`)
      }
    })

    this.ffmpegProcess.on('exit', (code) => {
      console.log(`[recording] FFmpeg exited with code ${code}`)
      this.isRecording = false
      this.ffmpegProcess = null
      if (code !== 0 && code !== null) {
        this.onStatus('error', `FFmpeg exited with code ${code}`)
      }
    })

    this.ffmpegProcess.on('error', (err) => {
      console.error('[recording] FFmpeg error:', err.message)
      this.isRecording = false
      this.ffmpegProcess = null
      this.onStatus('error', `FFmpeg error: ${err.message}`)
    })

    this.isRecording = true
    this.onStatus('recording', `Recording @ ${w}x${h} 60fps (${this.encoder})`)

    // Start cleanup timer
    if (this.cleanupTimer) clearInterval(this.cleanupTimer)
    this.cleanupTimer = setInterval(() => this._cleanup(), CLEANUP_INTERVAL)
  }

  _stopFFmpeg() {
    if (this.cleanupTimer) {
      clearInterval(this.cleanupTimer)
      this.cleanupTimer = null
    }

    if (!this.ffmpegProcess) return

    console.log('[recording] Stopping FFmpeg...')
    try {
      // Send 'q' to FFmpeg stdin for graceful shutdown
      this.ffmpegProcess.stdin.write('q')
      // Give it 3 seconds to finish, then force kill
      setTimeout(() => {
        if (this.ffmpegProcess) {
          try {
            const pid = this.ffmpegProcess.pid
            execSync(`taskkill /pid ${pid} /T /F`, { timeout: 5000 })
          } catch {}
          this.ffmpegProcess = null
        }
      }, 3000)
    } catch {
      if (this.ffmpegProcess) {
        try { this.ffmpegProcess.kill() } catch {}
        this.ffmpegProcess = null
      }
    }

    this.isRecording = false
    this.onStatus('stopped', 'Recording stopped')
  }

  // ── Marathon Monitoring ────────────────────────────────────────────

  _startMarathonMonitor() {
    this.marathonTimer = setInterval(async () => {
      const running = await this._isMarathonRunning()

      if (running && !this.isRecording) {
        console.log('[recording] Marathon detected — starting recording')
        if (this._stopTimeout) {
          clearTimeout(this._stopTimeout)
          this._stopTimeout = null
        }
        this._startFFmpeg()
      } else if (!running && this.isRecording) {
        if (!this._stopTimeout) {
          console.log('[recording] Marathon closed — stopping in 30s...')
          this._stopTimeout = setTimeout(() => {
            this._stopFFmpeg()
            this._stopTimeout = null
            this.onStatus('monitoring', 'Waiting for Marathon...')
          }, MARATHON_STOP_DELAY)
        }
      }
    }, MARATHON_CHECK_INTERVAL)
  }

  _isMarathonRunning() {
    return new Promise((resolve) => {
      const { exec } = require('child_process')
      exec('tasklist /FI "IMAGENAME eq Marathon.exe" /NH', { timeout: 3000 }, (err, stdout) => {
        if (err) return resolve(false)
        resolve(stdout.toLowerCase().includes('marathon.exe'))
      })
    })
  }

  // ── Utilities ──────────────────────────────────────────────────────

  _findFFmpeg() {
    if (isDev) {
      try {
        return execSync('where ffmpeg', { timeout: 5000 }).toString().trim().split('\n')[0].trim()
      } catch { return null }
    }
    // Production: check bundled first
    const bundled = path.join(process.resourcesPath, 'ffmpeg', 'ffmpeg.exe')
    if (fs.existsSync(bundled)) return bundled
    // Fallback to PATH
    try {
      return execSync('where ffmpeg', { timeout: 5000 }).toString().trim().split('\n')[0].trim()
    } catch { return null }
  }

  async _detectEncoder() {
    return new Promise((resolve) => {
      execFile(this.ffmpegPath, ['-encoders'], { timeout: 5000 }, (err, stdout) => {
        if (!err && stdout.includes('h264_nvenc')) {
          resolve('h264_nvenc')
        } else {
          resolve('libx264')
        }
      })
    })
  }

  async _detectCaptureMethod() {
    return new Promise((resolve) => {
      execFile(this.ffmpegPath, ['-filters'], { timeout: 5000 }, (err, stdout) => {
        if (!err && stdout.includes('ddagrab')) {
          resolve('ddagrab')
        } else {
          resolve('gdigrab')
        }
      })
    })
  }

  _getScreenResolution() {
    try {
      const { screen } = require('electron')
      const primary = screen.getPrimaryDisplay()
      return { w: primary.size.width, h: primary.size.height }
    } catch {
      return { w: 1920, h: 1080 }
    }
  }

  _cleanup() {
    const now = Date.now()
    // Segments: keep last 3 minutes
    this._deleteOlderThan(this.config.segmentsDir, BUFFER_DURATION * 1000, '.mp4')
    // Keyframes: keep last 30 seconds (we use 'latest.jpg' so just clean numbered ones)
    this._deleteOlderThan(this.config.keyframesDir, 30000, '.jpg')
  }

  _deleteOlderThan(dir, maxAgeMs, ext) {
    try {
      const now = Date.now()
      for (const file of fs.readdirSync(dir)) {
        if (file.startsWith('_') || file === 'latest.jpg') continue
        if (ext && !file.endsWith(ext)) continue
        const filePath = path.join(dir, file)
        try {
          const stat = fs.statSync(filePath)
          if (now - stat.mtimeMs > maxAgeMs) {
            fs.unlinkSync(filePath)
          }
        } catch {}
      }
    } catch {}
  }

  _getSegmentsInRange(startMs, endMs) {
    try {
      const files = fs.readdirSync(this.config.segmentsDir)
        .filter(f => f.endsWith('.mp4') && f.startsWith('seg_'))
        .sort()
        .map(f => path.join(this.config.segmentsDir, f))

      // Include segments that could overlap with the time range
      // Each segment is SEGMENT_DURATION seconds long
      return files.filter(f => {
        const segTime = this._parseSegmentTimestamp(f)
        const segEnd = segTime + (SEGMENT_DURATION * 1000)
        return segEnd > startMs && segTime < endMs
      })
    } catch {
      return []
    }
  }

  _parseSegmentTimestamp(filepath) {
    // Parse timestamp from filename: seg_YYYYMMDD_HHMMSS.mp4
    const match = path.basename(filepath).match(/seg_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})/)
    if (!match) return 0
    const [, y, m, d, H, M, S] = match
    return new Date(`${y}-${m}-${d}T${H}:${M}:${S}`).getTime()
  }

  _execFFmpeg(args) {
    return new Promise((resolve, reject) => {
      const proc = spawn(this.ffmpegPath, ['-y', '-hide_banner', ...args], {
        stdio: ['pipe', 'pipe', 'pipe'],
        windowsHide: true,
      })
      let stderr = ''
      proc.stderr.on('data', d => stderr += d.toString())
      proc.on('exit', (code) => {
        if (code === 0) resolve()
        else reject(new Error(`FFmpeg exit ${code}: ${stderr.slice(-200)}`))
      })
      proc.on('error', reject)
    })
  }
}

module.exports = { RecordingManager }
