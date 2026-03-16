/**
 * Screen Watcher — Automatic game state detection for Marathon.
 *
 * Captures small screen regions at regular intervals, sends to the
 * Python detection API, and manages a state machine for run lifecycle.
 *
 * States: IDLE → LOBBY → IN_RUN → RUN_ENDED → RESULTS → COOLDOWN → LOBBY
 */

const http = require('http')
const { exec } = require('child_process')

const API_BASE = 'http://localhost:8000'

// Capture regions as % of screen (will be scaled to actual resolution)
const REGIONS = {
  full: null, // full screenshot
  center_banner: { x: 0.28, y: 0.55, w: 0.44, h: 0.11 },
  bottom_center: { x: 0.30, y: 0.78, w: 0.40, h: 0.12 },
  top_right: { x: 0.70, y: 0.00, w: 0.30, h: 0.05 },
}

const STATES = {
  IDLE: 'IDLE',
  LOBBY: 'LOBBY',
  IN_RUN: 'IN_RUN',
  RUN_ENDED: 'RUN_ENDED',
  RESULTS: 'RESULTS',
  COOLDOWN: 'COOLDOWN',
}

class ScreenWatcher {
  constructor(onEvent) {
    this.onEvent = onEvent // callback for state changes
    this.state = STATES.IDLE
    this.enabled = false
    this.loopTimer = null
    this.cooldownTimer = null
    this.resultsTimer = null

    // Run context — accumulates data across states
    this.runContext = {
      mapName: null,
      spawnZone: null,
      shellName: null,
      survived: null,
      screenshots: [],
      startedAt: null,
    }

    // Tracking
    this.lastDetection = null
    this.lastDetectionTime = 0
    this.captureCount = 0

    // Screenshot module (lazy loaded)
    this._screenshot = null
  }

  async start() {
    if (this.enabled) return
    this.enabled = true
    this.state = STATES.IDLE
    console.log('[watcher] Screen watcher started')
    this._emitEvent('watcher_started')
    this._loop()
  }

  stop() {
    this.enabled = false
    if (this.loopTimer) clearTimeout(this.loopTimer)
    if (this.cooldownTimer) clearTimeout(this.cooldownTimer)
    if (this.resultsTimer) clearTimeout(this.resultsTimer)
    this.loopTimer = null
    this.state = STATES.IDLE
    console.log('[watcher] Screen watcher stopped')
    this._emitEvent('watcher_stopped')
  }

  getStatus() {
    return {
      enabled: this.enabled,
      state: this.state,
      runContext: this.runContext,
      captureCount: this.captureCount,
      lastDetection: this.lastDetection,
    }
  }

  // ── Main loop ──────────────────────────────────────────────────────

  async _loop() {
    if (!this.enabled) return

    try {
      // Check if Marathon is the foreground window
      const marathonFocused = await this._isMarathonFocused()

      if (!marathonFocused) {
        if (this.state !== STATES.IDLE) {
          this.state = STATES.IDLE
          this._emitEvent('state_change', { state: STATES.IDLE })
        }
      } else {
        if (this.state === STATES.IDLE) {
          this.state = STATES.LOBBY
          this._emitEvent('state_change', { state: STATES.LOBBY })
        }
        await this._tick()
      }
    } catch (err) {
      console.error('[watcher] Loop error:', err.message)
    }

    // Schedule next tick based on state
    const interval = this._getInterval()
    this.loopTimer = setTimeout(() => this._loop(), interval)
  }

  _getInterval() {
    switch (this.state) {
      case STATES.IDLE: return 2000      // Check every 2s if Marathon is focused
      case STATES.LOBBY: return 1000     // 1Hz in lobby
      case STATES.IN_RUN: return 500     // 2Hz during gameplay
      case STATES.RUN_ENDED: return 500  // Fast to catch results
      case STATES.RESULTS: return 1000   // 1Hz capturing result tabs
      case STATES.COOLDOWN: return 2000  // Slow during cooldown
      default: return 1000
    }
  }

  // ── State-specific detection ───────────────────────────────────────

  async _tick() {
    switch (this.state) {
      case STATES.LOBBY:
        await this._checkLobby()
        break
      case STATES.IN_RUN:
        await this._checkInRun()
        break
      case STATES.RUN_ENDED:
        // Brief pause then transition to results
        this.state = STATES.RESULTS
        this.runContext.screenshots = []
        this._emitEvent('state_change', { state: STATES.RESULTS })
        // Start results capture timeout
        this.resultsTimer = setTimeout(() => this._finishResults(), 20000)
        break
      case STATES.RESULTS:
        await this._checkResults()
        break
    }
  }

  async _checkLobby() {
    const imgBuffer = await this._captureScreen()
    if (!imgBuffer) return

    const result = await this._detect(imgBuffer, 'full')
    if (!result) return

    if (result.detected === 'loading_screen') {
      console.log('[watcher] Loading screen detected — run starting')
      this.state = STATES.IN_RUN
      this.runContext = {
        mapName: null,
        spawnZone: null,
        shellName: null,
        survived: null,
        screenshots: [],
        startedAt: Date.now(),
      }
      this._emitEvent('loading_screen', { context: this.runContext })
      this._emitEvent('state_change', { state: STATES.IN_RUN })
    } else if (result.detected === 'ready_up') {
      console.log('[watcher] Ready up screen detected')
      // Capture full screenshot for Claude to parse pre-run info
      this._emitEvent('ready_up', { screenshot: imgBuffer })
    }
  }

  async _checkInRun() {
    const imgBuffer = await this._captureScreen()
    if (!imgBuffer) return

    const result = await this._detect(imgBuffer, 'full')
    if (!result) return

    if (result.detected === 'exfiltrated') {
      console.log('[watcher] EXFILTRATED detected!')
      this.runContext.survived = true
      this.state = STATES.RUN_ENDED
      this._emitEvent('run_ended', { survived: true })
      this._emitEvent('state_change', { state: STATES.RUN_ENDED })
    } else if (result.detected === 'eliminated') {
      console.log('[watcher] ELIMINATED detected!')
      this.runContext.survived = false
      this.state = STATES.RUN_ENDED
      this._emitEvent('run_ended', { survived: false })
      this._emitEvent('state_change', { state: STATES.RUN_ENDED })
    } else if (result.detected === 'stats_tab' || result.detected === 'loadout_tab') {
      // Jumped straight to results (missed the banner)
      console.log('[watcher] Results screen detected directly')
      this.state = STATES.RESULTS
      this.runContext.screenshots = []
      this._emitEvent('state_change', { state: STATES.RESULTS })
      this.resultsTimer = setTimeout(() => this._finishResults(), 20000)
      // Capture this screenshot
      this.runContext.screenshots.push({ type: result.detected, buffer: imgBuffer })
    }
  }

  async _checkResults() {
    const imgBuffer = await this._captureScreen()
    if (!imgBuffer) return

    const result = await this._detect(imgBuffer, 'full')
    if (!result) return

    if (result.detected === 'stats_tab' || result.detected === 'loadout_tab') {
      // Check if we already have this tab
      const existing = this.runContext.screenshots.find(s => s.type === result.detected)
      if (!existing) {
        console.log(`[watcher] Captured ${result.detected}`)
        this.runContext.screenshots.push({ type: result.detected, buffer: imgBuffer })
        this._emitEvent('tab_captured', { tab: result.detected })
      }

      // If we have both tabs, finish early
      const hasStats = this.runContext.screenshots.some(s => s.type === 'stats_tab')
      const hasLoadout = this.runContext.screenshots.some(s => s.type === 'loadout_tab')
      if (hasStats && hasLoadout) {
        this._finishResults()
      }
    } else if (result.detected === 'none' || result.detected === 'ready_up') {
      // Left the results screen — finish with what we have
      if (this.runContext.screenshots.length > 0) {
        this._finishResults()
      }
    }
  }

  _finishResults() {
    if (this.resultsTimer) {
      clearTimeout(this.resultsTimer)
      this.resultsTimer = null
    }

    if (this.state !== STATES.RESULTS && this.state !== STATES.RUN_ENDED) return

    const screenshotCount = this.runContext.screenshots.length
    console.log(`[watcher] Finishing results capture (${screenshotCount} screenshots)`)

    this._emitEvent('results_ready', {
      context: this.runContext,
      screenshotCount,
    })

    // Enter cooldown
    this.state = STATES.COOLDOWN
    this._emitEvent('state_change', { state: STATES.COOLDOWN })
    this.cooldownTimer = setTimeout(() => {
      this.state = STATES.LOBBY
      this._emitEvent('state_change', { state: STATES.LOBBY })
      console.log('[watcher] Cooldown ended, back to lobby')
    }, 15000) // 15s cooldown
  }

  // ── Utilities ──────────────────────────────────────────────────────

  async _captureScreen() {
    try {
      if (!this._screenshot) {
        this._screenshot = require('screenshot-desktop')
      }
      const buffer = await this._screenshot({ format: 'png' })
      this.captureCount++
      return buffer
    } catch (err) {
      console.error('[watcher] Capture failed:', err.message)
      return null
    }
  }

  async _detect(imageBuffer, region) {
    return new Promise((resolve) => {
      const boundary = '----Detect' + Date.now()
      const header = `--${boundary}\r\nContent-Disposition: form-data; name="file"; filename="capture.png"\r\nContent-Type: image/png\r\n\r\n`
      const regionField = `\r\n--${boundary}\r\nContent-Disposition: form-data; name="region"\r\n\r\n${region}`
      const footer = `\r\n--${boundary}--\r\n`

      const body = Buffer.concat([
        Buffer.from(header),
        imageBuffer,
        Buffer.from(regionField),
        Buffer.from(footer),
      ])

      const url = new URL(API_BASE + '/api/detect/check')
      const req = http.request({
        hostname: url.hostname,
        port: url.port,
        path: url.pathname,
        method: 'POST',
        headers: {
          'Content-Type': `multipart/form-data; boundary=${boundary}`,
          'Content-Length': body.length,
        },
        timeout: 5000,
      }, (res) => {
        let data = ''
        res.on('data', chunk => data += chunk)
        res.on('end', () => {
          try {
            const result = JSON.parse(data)
            this.lastDetection = result
            this.lastDetectionTime = Date.now()
            resolve(result)
          } catch {
            resolve(null)
          }
        })
      })

      req.on('error', () => resolve(null))
      req.on('timeout', () => { req.destroy(); resolve(null) })
      req.write(body)
      req.end()
    })
  }

  _isMarathonFocused() {
    return new Promise((resolve) => {
      exec(
        'powershell -command "try { (Get-Process -Name Marathon -ErrorAction Stop).MainWindowTitle } catch { \'\' }"',
        { timeout: 2000 },
        (err, stdout) => {
          if (err) return resolve(false)
          resolve(stdout.trim().length > 0)
        }
      )
    })
  }

  _emitEvent(type, data = {}) {
    if (this.onEvent) {
      this.onEvent({ type, timestamp: Date.now(), ...data })
    }
  }
}

module.exports = { ScreenWatcher, STATES }
