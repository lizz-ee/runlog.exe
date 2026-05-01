/**
 * Backend Manager — Spawns and manages the Python FastAPI backend.
 *
 * Handles:
 * - Finding Python on the system
 * - Spawning the backend process
 * - Health check polling until ready
 * - Clean shutdown (Windows process tree kill)
 * - User data directory management
 */

const { spawn, execSync } = require('child_process')
const path = require('path')
const fs = require('fs')
const http = require('http')
const { app } = require('electron')

const isDev = !app.isPackaged

// Log to file for debugging packaged app issues — with rotation
const LOG_FILE = path.join(app.getPath('userData'), 'backend-manager.log')
const LOG_MAX_BYTES = 5 * 1024 * 1024 // 5MB max before rotation
const LOG_KEEP = 3 // keep 3 rotated files

function _rotateLogIfNeeded() {
  try {
    if (!fs.existsSync(LOG_FILE)) return
    const stat = fs.statSync(LOG_FILE)
    if (stat.size < LOG_MAX_BYTES) return
    // Rotate: .log.2 -> .log.3, .log.1 -> .log.2, .log -> .log.1
    for (let i = LOG_KEEP - 1; i >= 1; i--) {
      const src = `${LOG_FILE}.${i}`
      const dst = `${LOG_FILE}.${i + 1}`
      if (fs.existsSync(src)) fs.renameSync(src, dst)
    }
    fs.renameSync(LOG_FILE, `${LOG_FILE}.1`)
    // Delete oldest if over limit
    const oldest = `${LOG_FILE}.${LOG_KEEP + 1}`
    if (fs.existsSync(oldest)) fs.unlinkSync(oldest)
  } catch {}
}
_rotateLogIfNeeded()

function _sanitizeLogLine(msg) {
  // Redact player gamertags from OCR output (pattern: word#1234)
  return msg.replace(/\b\w+#\d{4,}\b/g, '[REDACTED]')
}

function logToFile(msg) {
  const sanitized = _sanitizeLogLine(msg)
  const line = `[${new Date().toISOString()}] ${sanitized}\n`
  try { fs.appendFileSync(LOG_FILE, line) } catch {}
  console.log(msg)
}
// Port is configurable via settings.json "api_port" field, defaults to 8000
function _getApiPort() {
  try {
    const settingsPath = path.join(app.getPath('userData'), 'settings.json')
    if (fs.existsSync(settingsPath)) {
      const cfg = JSON.parse(fs.readFileSync(settingsPath, 'utf-8'))
      if (cfg.api_port && Number.isInteger(cfg.api_port) && cfg.api_port > 0 && cfg.api_port < 65536) {
        return cfg.api_port
      }
    }
  } catch {}
  return 8000
}
const API_PORT = _getApiPort()
const HEALTH_URL = `http://127.0.0.1:${API_PORT}/`
const HEALTH_TIMEOUT = 120000 // 120s max wait (slow systems, antivirus scanning)
const HEALTH_INTERVAL = 1000 // poll every 1s

class BackendManager {
  constructor(onStatus) {
    this.onStatus = onStatus || (() => {})
    this.process = null
    this.pythonPath = null
    this.backendPath = null
    this.userDataPath = null
  }

  /**
   * Start the Python backend. Returns a promise that resolves when healthy.
   */
  async start() {
    // In production, kill any stale backend from a previous run using saved PID file
    this._pidFile = path.join(app.getPath('userData'), 'backend.pid')
    if (!isDev) {
      try {
        if (fs.existsSync(this._pidFile)) {
          const stalePid = parseInt(fs.readFileSync(this._pidFile, 'utf-8').trim(), 10)
          if (stalePid > 0) {
            logToFile(`[backend] Killing stale backend PID ${stalePid}`)
            execSync(`taskkill /pid ${stalePid} /T /F`, { timeout: 5000 })
          }
          fs.unlinkSync(this._pidFile)
        }
      } catch {}
    }

    // Check if backend is already running (dev mode)
    const alreadyUp = await this._healthCheck()
    if (alreadyUp) {
      this.onStatus('ready', 'Backend already running')
      return true
    }

    if (isDev) {
      this.onStatus('error', 'Backend not running — start it manually with: cd backend && python run.py')
      return false
    }

    // Find Python
    this.pythonPath = this._findPython()
    if (!this.pythonPath) {
      this.onStatus('error', 'Python not found. Please install Python 3.12+')
      return false
    }
    this.onStatus('starting', `Found Python: ${this.pythonPath}`)

    // Resolve paths
    this.backendPath = path.join(process.resourcesPath, 'backend')
    this.userDataPath = path.join(app.getPath('userData'), 'marathon', 'data')

    // Ensure user data directory exists
    fs.mkdirSync(this.userDataPath, { recursive: true })
    fs.mkdirSync(path.join(this.userDataPath, 'media_uploads'), { recursive: true })

    // Check if port is already in use
    const alreadyRunning = await this._healthCheck()
    if (alreadyRunning) {
      this.onStatus('ready', 'Backend already running on port ' + API_PORT)
      return true
    }

    // Spawn Python backend
    const env = {
      ...process.env,
      DATABASE_URL: `sqlite:///${path.join(this.userDataPath, 'runlog.db').replace(/\\/g, '/')}`,
      MEDIA_UPLOAD_DIR: path.join(this.userDataPath, 'media_uploads'),
      RUNLOG_PORT: String(API_PORT),
      PYTHONUNBUFFERED: '1',
    }

    logToFile(`[backend] isDev: ${isDev}`)
    logToFile(`[backend] app.isPackaged: ${app.isPackaged}`)
    logToFile(`[backend] resourcesPath: ${process.resourcesPath}`)
    logToFile(`[backend] Backend path: ${this.backendPath}`)
    logToFile(`[backend] User data path: ${this.userDataPath}`)
    logToFile(`[backend] Python: ${this.pythonPath}`)
    logToFile(`[backend] run.py exists: ${fs.existsSync(path.join(this.backendPath, 'run.py'))}`)

    this.onStatus('starting', 'Spawning backend process...')
    this.process = spawn(this.pythonPath, ['run.py'], {
      cwd: this.backendPath,
      env,
      stdio: ['pipe', 'pipe', 'pipe'],
      windowsHide: true,
    })

    // Save PID for stale process cleanup on next launch
    try { fs.writeFileSync(this._pidFile, String(this.process.pid)) } catch {}

    this.process.stdout.on('data', (data) => {
      logToFile(`[backend stdout] ${data.toString().trim()}`)
    })

    this.process.stderr.on('data', (data) => {
      logToFile(`[backend stderr] ${data.toString().trim()}`)
    })

    this.process.on('exit', (code) => {
      logToFile(`[backend] Process exited with code ${code}`)
      if (code !== 0 && code !== null) {
        this.onStatus('error', `Backend exited with code ${code}`)
      }
      this.process = null
    })

    this.process.on('error', (err) => {
      logToFile(`[backend] Process error: ${err.message}`)
      this.onStatus('error', `Failed to start backend: ${err.message}`)
      this.process = null
    })

    // Wait for health check
    this.onStatus('starting', 'Waiting for backend to be ready...')
    const healthy = await this._waitForHealth()
    if (healthy) {
      this.onStatus('ready', 'Backend is ready')
      return true
    } else {
      this.onStatus('error', 'Backend failed to start within timeout')
      this.stop()
      return false
    }
  }

  /**
   * Stop the backend process and all children.
   */
  stop() {
    if (!this.process) return

    const pid = this.process.pid
    logToFile(`[backend] Stopping process tree (PID: ${pid})`)

    try {
      // Windows: kill entire process tree
      if (process.platform === 'win32') {
        execSync(`taskkill /pid ${pid} /T /F`, { timeout: 5000 })
      } else {
        this.process.kill('SIGTERM')
      }
    } catch (err) {
      logToFile(`[backend] Kill error: ${err.message}`)
    }

    this.process = null
    try { if (this._pidFile) fs.unlinkSync(this._pidFile) } catch {}
    this.onStatus('stopped', 'Backend stopped')
  }

  isRunning() {
    return this.process !== null && this.process.exitCode === null
  }

  /**
   * Find a working Python installation.
   */
  _findPython() {
    const candidates = []

    // 1. Check installer-saved path (most reliable — installer already verified it)
    const savedPath = path.join(process.env.APPDATA || '', 'runlog', 'python-path')
    try {
      const saved = fs.readFileSync(savedPath, 'utf8').trim()
      if (saved && fs.existsSync(saved)) {
        logToFile(`[backend] Using installer-saved Python: ${saved}`)
        candidates.push(saved)
      }
    } catch {}

    // 2. PATH-based candidates
    candidates.push('python', 'python3')

    if (process.platform === 'win32') {
      // 3. Common install locations
      const userHome = process.env.USERPROFILE || process.env.HOME || ''
      for (const ver of ['313', '312', '311']) {
        candidates.push(
          `C:\\Python${ver}\\python.exe`,
          path.join(userHome, `AppData\\Local\\Programs\\Python\\Python${ver}\\python.exe`),
        )
      }
      // 4. Microsoft Store Python
      candidates.push(
        path.join(userHome, 'AppData\\Local\\Microsoft\\WindowsApps\\python3.exe'),
        path.join(userHome, 'AppData\\Local\\Microsoft\\WindowsApps\\python.exe'),
      )

      // 5. py launcher — resolves all install types, returns the real path
      try {
        const real = execSync('py -3 -c "import sys; print(sys.executable)"', {
          timeout: 5000,
          stdio: ['pipe', 'pipe', 'pipe'],
        }).toString().trim()
        if (real && fs.existsSync(real)) {
          logToFile(`[backend] py launcher resolved: ${real}`)
          candidates.push(real)
        }
      } catch {}
    }

    for (const cmd of candidates) {
      try {
        const result = execSync(`"${cmd}" --version`, {
          timeout: 5000,
          stdio: ['pipe', 'pipe', 'pipe'],
        })
        const version = result.toString().trim()
        logToFile(`[backend] Found: ${cmd} (${version})`)
        return cmd
      } catch {}
    }

    return null
  }

  /**
   * Single health check — returns true if backend responds.
   */
  _healthCheck() {
    return new Promise((resolve) => {
      const req = http.get(HEALTH_URL, { timeout: 2000 }, (res) => {
        logToFile(`[health] Response: ${res.statusCode}`)
        resolve(res.statusCode === 200)
      })
      req.on('error', (err) => {
        logToFile(`[health] Error: ${err.message}`)
        resolve(false)
      })
      req.on('timeout', () => {
        logToFile('[health] Timeout')
        req.destroy()
        resolve(false)
      })
    })
  }

  /**
   * Poll health check until success or timeout.
   */
  _waitForHealth() {
    return new Promise((resolve) => {
      const start = Date.now()
      const check = async () => {
        if (Date.now() - start > HEALTH_TIMEOUT) {
          resolve(false)
          return
        }
        const alive = await this._healthCheck()
        if (alive) {
          resolve(true)
        } else {
          setTimeout(check, HEALTH_INTERVAL)
        }
      }
      check()
    })
  }
}

module.exports = { BackendManager, API_PORT }
