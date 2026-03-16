/**
 * Recording Manager — Controls the PyAV capture engine via REST API.
 *
 * The actual recording runs inside the Python backend as a thread.
 * This module just starts/stops it and requests clips via HTTP.
 * No FFmpeg subprocess, no file management, no cleanup timers.
 */

const http = require('http')
const { app } = require('electron')

const API_BASE = 'http://127.0.0.1:8000'

class RecordingManager {
  constructor(config, onStatus) {
    this.config = config || {}
    this.onStatus = onStatus || (() => {})
    this.isRecording = false
    this.marathonTimer = null
    this._stopTimeout = null
  }

  async start() {
    this._startMarathonMonitor()
    this.onStatus('monitoring', 'Waiting for Marathon...')
    return true
  }

  stop() {
    if (this.marathonTimer) {
      clearInterval(this.marathonTimer)
      this.marathonTimer = null
    }
    if (this._stopTimeout) {
      clearTimeout(this._stopTimeout)
      this._stopTimeout = null
    }
    this._stopCapture()
  }

  isActive() {
    return this.isRecording
  }

  async getStatus() {
    try {
      const data = await this._apiGet('/api/capture/status')
      return data
    } catch {
      return { active: false }
    }
  }

  async saveClip(beforeSec = 20, afterSec = 5, metadata = {}) {
    try {
      const data = await this._apiPost('/api/capture/clip', {
        seconds_before: beforeSec,
        seconds_after: afterSec,
        event: metadata.event || 'event',
      })
      if (data.filename) {
        console.log(`[recording] Clip saved: ${data.filename} (${data.size_mb}MB)`)
        this.onStatus('clip_saved', `Clip: ${data.filename}`)
      }
      return data
    } catch (err) {
      console.error('[recording] Clip save failed:', err.message)
      return null
    }
  }

  // ── Marathon monitoring ────────────────────────────────────────────

  _startMarathonMonitor() {
    this.marathonTimer = setInterval(async () => {
      const running = await this._isMarathonRunning()

      if (running && !this.isRecording) {
        if (this._stopTimeout) {
          clearTimeout(this._stopTimeout)
          this._stopTimeout = null
        }
        console.log('[recording] Marathon detected — starting capture')
        await this._startCapture()
      } else if (!running && this.isRecording) {
        if (!this._stopTimeout) {
          console.log('[recording] Marathon closed — stopping in 30s...')
          this._stopTimeout = setTimeout(() => {
            this._stopCapture()
            this._stopTimeout = null
            this.onStatus('monitoring', 'Waiting for Marathon...')
          }, 30000)
        }
      }
    }, 5000)
  }

  async _startCapture() {
    try {
      const data = await this._apiPost('/api/capture/start', {})
      this.isRecording = true
      this.onStatus('recording', 'Capture active')
      console.log('[recording] Capture started:', JSON.stringify(data))
    } catch (err) {
      console.error('[recording] Start failed:', err.message)
      this.onStatus('error', `Start failed: ${err.message}`)
    }
  }

  async _stopCapture() {
    try {
      await this._apiPost('/api/capture/stop', {})
    } catch {}
    this.isRecording = false
    this.onStatus('stopped', 'Capture stopped')
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

  // ── HTTP helpers ───────────────────────────────────────────────────

  _apiGet(path) {
    return new Promise((resolve, reject) => {
      http.get(`${API_BASE}${path}`, { timeout: 5000 }, (res) => {
        let data = ''
        res.on('data', chunk => data += chunk)
        res.on('end', () => {
          try { resolve(JSON.parse(data)) }
          catch { reject(new Error('Bad response')) }
        })
      }).on('error', reject)
    })
  }

  _apiPost(path, body) {
    return new Promise((resolve, reject) => {
      const bodyStr = JSON.stringify(body)
      const req = http.request({
        hostname: '127.0.0.1',
        port: 8000,
        path: path,
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Content-Length': Buffer.byteLength(bodyStr),
        },
        timeout: 10000,
      }, (res) => {
        let data = ''
        res.on('data', chunk => data += chunk)
        res.on('end', () => {
          try { resolve(JSON.parse(data)) }
          catch { reject(new Error('Bad response')) }
        })
      })
      req.on('error', reject)
      req.write(bodyStr)
      req.end()
    })
  }
}

module.exports = { RecordingManager }
