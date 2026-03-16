/**
 * Screen Watcher — Automatic game state detection for Marathon.
 *
 * Captures small screen regions at regular intervals, sends to the
 * Python detection API, and manages a state machine for run lifecycle.
 *
 * States: IDLE → LOBBY → IN_RUN → RUN_ENDED → RESULTS → COOLDOWN → LOBBY
 */

const http = require('http')
const fs = require('fs')
const path = require('path')
const { exec } = require('child_process')

const API_BASE = 'http://127.0.0.1:8000'

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

    // Keyframes directory (set by main.js from recording manager)
    this._keyframesDir = null
    // OCR throttle — max once every 3 seconds normally, 1 second during rapid mode
    this._lastOcrTime = 0
    this._ocrCooldown = 3000
    this._rapidOcrUntil = 0
  }

  setKeyframesDir(dir) {
    this._keyframesDir = dir
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
      const marathonFocused = await this._isMarathonRunning()

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

    // Fast local check first
    const result = await this._detect(imgBuffer, 'full')
    if (!result) return

    if (result.detected === 'loading_screen') {
      console.log('[watcher] Loading screen detected — run starting')
      this.state = STATES.IN_RUN
      this._readyUpFired = false
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
      return
    }

    // Screen changed but not a banner/loading — ask Claude what it is (non-blocking)
    if (result.detected === 'unknown_change' && !this._claudeInFlight) {
      this._claudeInFlight = true
      console.log('[watcher] Screen changed — asking Claude...')
      this._detectFull(imgBuffer).then(fullResult => {
        this._claudeInFlight = false
        if (!fullResult) return

        console.log(`[watcher] Claude says: ${fullResult.game_state}`)
        this._emitEvent('claude_detected', { state: fullResult.game_state, data: fullResult })

        if (fullResult.game_state === 'ready_up' || fullResult.game_state === 'deploying') {
          if (!this._readyUpFired) {
            this._readyUpFired = true
            this.runContext.mapName = fullResult.map_name
            this.runContext.shellName = fullResult.shell_name
            this.runContext.preRunData = fullResult
            this._emitEvent('ready_up', { screenshot: imgBuffer, data: fullResult })
          }
        } else if (fullResult.game_state === 'loading') {
          this.state = STATES.IN_RUN
          this._readyUpFired = false
          this.runContext = {
            mapName: fullResult.map_name,
            spawnZone: null,
            shellName: fullResult.shell_name,
            survived: null,
            screenshots: [],
            startedAt: Date.now(),
          }
          this._emitEvent('loading_screen', { context: this.runContext })
          this._emitEvent('state_change', { state: STATES.IN_RUN })
        }
      }).catch(() => { this._claudeInFlight = false })
    }
  }

  async _checkInRun() {
    const imgBuffer = await this._captureScreen()
    if (!imgBuffer) return

    // Fast local check for banners
    const result = await this._detect(imgBuffer, 'full')
    if (!result) return

    if (result.detected === 'exfiltrated') {
      console.log('[watcher] EXFILTRATED detected!')
      this.runContext.survived = true
      this.state = STATES.RUN_ENDED
      this._enterRapidOcr()
      this._emitEvent('run_ended', { survived: true })
      this._emitEvent('state_change', { state: STATES.RUN_ENDED })
    } else if (result.detected === 'eliminated') {
      console.log('[watcher] ELIMINATED detected!')
      this.runContext.survived = false
      this.state = STATES.RUN_ENDED
      this._enterRapidOcr()
      this._emitEvent('run_ended', { survived: false })
      this._emitEvent('state_change', { state: STATES.RUN_ENDED })
    } else if (result.detected === 'unknown_change' && !this._claudeInFlight) {
      // Screen changed significantly during run — check with Claude
      // (could be run_complete death screen, or we missed the banner)
      this._claudeInFlight = true
      const fullResult = await this._detectFull(imgBuffer)
      this._claudeInFlight = false
      if (!fullResult) return

      console.log(`[watcher] Claude says: ${fullResult.game_state}`)

      if (fullResult.game_state === 'gameplay' && fullResult.zone_name) {
        // Capture zone name for spawn tracking
        if (!this.runContext.spawnZone) {
          this.runContext.spawnZone = fullResult.zone_name
          this.runContext.compassBearing = fullResult.compass_bearing
          this._emitEvent('zone_detected', { zone: fullResult.zone_name })
        }
      } else if (fullResult.game_state === 'run_complete') {
        this.runContext.survived = false
        this.runContext.killedBy = fullResult.killed_by
        this.state = STATES.RUN_ENDED
        this._emitEvent('run_ended', { survived: false, data: fullResult })
        this._emitEvent('state_change', { state: STATES.RUN_ENDED })
      } else if (fullResult.game_state === 'exfiltrated' || fullResult.game_state === 'stats_screen'
                 || fullResult.game_state === 'loadout_screen' || fullResult.game_state === 'progress_screen') {
        // Hit results directly
        this.runContext.screenshots.push({ type: fullResult.game_state, buffer: imgBuffer, data: fullResult })
        if (this.state !== STATES.RESULTS) {
          this.state = STATES.RESULTS
          this._emitEvent('state_change', { state: STATES.RESULTS })
          this.resultsTimer = setTimeout(() => this._finishResults(), 20000)
        }
      }
    }
  }

  async _checkResults() {
    const imgBuffer = await this._captureScreen()
    if (!imgBuffer) return

    const result = await this._detect(imgBuffer, 'full')
    if (!result) return

    // Skip if no screen change
    if (result.detected === 'no_change') return

    if (result.detected === 'unknown_change' && !this._claudeInFlight) {
      this._claudeInFlight = true
      const fullResult = await this._detectFull(imgBuffer)
      this._claudeInFlight = false
      if (!fullResult) return

      console.log(`[watcher] Results - Claude says: ${fullResult.game_state}`)

      if (['stats_screen', 'loadout_screen', 'progress_screen', 'exfiltrated', 'eliminated'].includes(fullResult.game_state)) {
        // New results tab — check if we already have this type
        const existing = this.runContext.screenshots.find(s => s.type === fullResult.game_state)
        if (!existing) {
          this.runContext.screenshots.push({ type: fullResult.game_state, buffer: imgBuffer, data: fullResult })
          this._emitEvent('tab_captured', { tab: fullResult.game_state, data: fullResult })
        }
      } else if (['lobby', 'prepare', 'select_zone'].includes(fullResult.game_state)) {
        // Left results — finish with what we have
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
      this._readyUpFired = false
      this._emitEvent('state_change', { state: STATES.LOBBY })
      console.log('[watcher] Cooldown ended, back to lobby')
    }, 15000) // 15s cooldown
  }

  // ── Utilities ──────────────────────────────────────────────────────

  async _captureScreen() {
    try {
      const buffer = await this._fetchFrame()
      if (buffer) {
        this.captureCount++
        return buffer
      }
      return null
    } catch {
      return null
    }
  }

  _fetchFrame() {
    return new Promise((resolve) => {
      const req = http.get('http://127.0.0.1:8000/api/capture/frame', { timeout: 2000 }, (res) => {
        if (res.statusCode !== 200) return resolve(null)
        const chunks = []
        res.on('data', chunk => chunks.push(chunk))
        res.on('end', () => resolve(Buffer.concat(chunks)))
      })
      req.on('error', () => resolve(null))
      req.on('timeout', () => { req.destroy(); resolve(null) })
    })
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

  _enterRapidOcr() {
    // Enable rapid OCR for next 30 seconds (for results screens)
    this._rapidOcrUntil = Date.now() + 30000
    console.log('[watcher] Rapid OCR mode ON for 30 seconds')
  }

  async _detectFull(imageBuffer) {
    // Throttle: 5s normally, 1s during rapid mode (results capture)
    const now = Date.now()
    const cooldown = now < this._rapidOcrUntil ? 1000 : this._ocrCooldown
    if (now - this._lastOcrTime < cooldown) {
      return null
    }
    this._lastOcrTime = now

    return new Promise((resolve) => {
      const boundary = '----DetectFull' + Date.now()
      const header = `--${boundary}\r\nContent-Disposition: form-data; name="file"; filename="capture.png"\r\nContent-Type: image/png\r\n\r\n`
      const footer = `\r\n--${boundary}--\r\n`

      const body = Buffer.concat([
        Buffer.from(header),
        imageBuffer,
        Buffer.from(footer),
      ])

      const url = new URL(API_BASE + '/api/detect/check-full')
      const req = http.request({
        hostname: url.hostname,
        port: url.port,
        path: url.pathname,
        method: 'POST',
        headers: {
          'Content-Type': `multipart/form-data; boundary=${boundary}`,
          'Content-Length': body.length,
        },
        timeout: 30000, // Claude Vision can take a while
      }, (res) => {
        let data = ''
        res.on('data', chunk => data += chunk)
        res.on('end', () => {
          try {
            resolve(JSON.parse(data))
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

  _isMarathonRunning() {
    return new Promise((resolve) => {
      exec(
        'tasklist /FI "IMAGENAME eq Marathon.exe" /NH',
        { timeout: 3000 },
        (err, stdout) => {
          if (err) return resolve(false)
          resolve(stdout.toLowerCase().includes('marathon.exe'))
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
