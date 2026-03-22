/**
 * Recording Manager — Monitors for Marathon and controls the auto-capture system.
 *
 * Simple responsibilities:
 * - Detect Marathon.exe running → POST /api/capture/start
 * - Detect Marathon.exe closed → POST /api/capture/stop
 * - Poll capture status and emit to renderer
 */

const http = require('http')

class RecordingManager {
  constructor(onStatus) {
    this.onStatus = onStatus || (() => {})
    this.isCapturing = false
    this.wasRecording = false
    this.marathonTimer = null
    this.statusTimer = null
  }

  start() {
    this._startMarathonMonitor()
    this.onStatus('monitoring', 'Waiting for Marathon...')
  }

  stop() {
    if (this.marathonTimer) clearInterval(this.marathonTimer)
    if (this.statusTimer) clearInterval(this.statusTimer)
    this.marathonTimer = null
    this.statusTimer = null
    this._stopCapture()
  }

  isActive() {
    return this.isCapturing
  }

  // ── Marathon monitoring ────────────────────────────────────────────

  _startMarathonMonitor() {
    if (this.marathonTimer) clearInterval(this.marathonTimer)
    this.marathonTimer = setInterval(async () => {
      const running = await this._isMarathonRunning()

      if (running && !this.isCapturing) {
        console.log('[recording] Marathon detected — starting capture')
        await this._startCapture()
      } else if (!running && this.isCapturing) {
        console.log('[recording] Marathon closed — stopping capture')
        this._stopCapture()
      }
    }, 5000)
  }

  async _startCapture() {
    try {
      await this._apiPost('/api/capture/start')
      this.isCapturing = true
      this.onStatus('active', 'Auto-capture running')

      // TODO: Consider SSE via http module for real-time updates instead of polling
      // Poll status every 3 seconds — detect recording start/stop and processing
      this.lastRunId = null
      if (this.statusTimer) clearInterval(this.statusTimer)
      this.statusTimer = setInterval(async () => {
        try {
          const status = await this._apiGet('/api/capture/status')

          // Detect recording state changes
          if (status.recording && !this.wasRecording) {
            this.onStatus('recording_started', 'Recording run...')
          } else if (!status.recording && this.wasRecording) {
            this.onStatus('recording_stopped', 'Run recording saved')
          }
          this.wasRecording = status.recording

          // Detect when Sonnet finishes processing a run
          if (status.last_result && status.last_result.run_id && status.last_result.run_id !== this.lastRunId) {
            this.lastRunId = status.last_result.run_id
            const a = status.last_result.analysis
            if (a) {
              const outcome = a.survived ? 'EXTRACTED' : 'KIA'
              const clips = status.last_result.clips ? status.last_result.clips.length : 0
              this.onStatus('run_processed', `${outcome} | ${a.kills || 0} kills | ${clips} clips | ${a.map_name || 'Unknown'}`)
            }
          }

          this.onStatus('status', JSON.stringify(status))
        } catch {}
      }, 3000)
    } catch (err) {
      console.error('[recording] Start failed:', err.message)
    }
  }

  async _stopCapture() {
    if (this.statusTimer) {
      clearInterval(this.statusTimer)
      this.statusTimer = null
    }
    try {
      await this._apiPost('/api/capture/stop')
    } catch {}
    this.isCapturing = false
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
      http.get(`http://127.0.0.1:8000${path}`, { timeout: 5000 }, (res) => {
        let data = ''
        res.on('data', chunk => data += chunk)
        res.on('end', () => {
          try { resolve(JSON.parse(data)) }
          catch { reject(new Error('Bad response')) }
        })
      }).on('error', reject)
    })
  }

  _apiPost(path) {
    return new Promise((resolve, reject) => {
      const req = http.request({
        hostname: '127.0.0.1', port: 8000, path, method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Content-Length': 2 },
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
      req.write('{}')
      req.end()
    })
  }
}

module.exports = { RecordingManager }
