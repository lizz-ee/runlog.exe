const { app, BrowserWindow, Tray, Menu, Notification, nativeImage, ipcMain } = require('electron')
const path = require('path')
const fs = require('fs')
const http = require('http')
const { SteamScreenshotWatcher } = require('./steam-watcher')
const { ScreenWatcher } = require('./screen-watcher')
const { BackendManager } = require('./backend-manager')
const { RecordingManager } = require('./recording-manager')

const isDev = !app.isPackaged
const API_BASE = 'http://127.0.0.1:8000'

let backendManager = null
let recordingManager = null

// Marathon Steam App ID
const MARATHON_APP_ID = '3065800'

let mainWindow = null
let tray = null
let steamWatcher = null
let screenWatcher = null

// ── Screenshot capture ──────────────────────────────────────────────

async function captureScreen() {
  try {
    const screenshot = require('screenshot-desktop')
    const imgBuffer = await screenshot({ format: 'png' })
    return imgBuffer
  } catch (err) {
    console.error('Screenshot failed:', err)
    return null
  }
}

function uploadScreenshot(buffer, endpoint) {
  return new Promise((resolve, reject) => {
    const boundary = '----RunLog' + Date.now()
    const filename = `capture_${Date.now()}.png`

    const fieldName = endpoint === '/api/screenshot/parse' ? 'files' : 'file'
    const header = `--${boundary}\r\nContent-Disposition: form-data; name="${fieldName}"; filename="${filename}"\r\nContent-Type: image/png\r\n\r\n`
    const footer = `\r\n--${boundary}--\r\n`

    const bodyParts = [Buffer.from(header), buffer, Buffer.from(footer)]
    const body = Buffer.concat(bodyParts)

    const url = new URL(API_BASE + endpoint)
    const options = {
      hostname: url.hostname,
      port: url.port,
      path: url.pathname,
      method: 'POST',
      headers: {
        'Content-Type': `multipart/form-data; boundary=${boundary}`,
        'Content-Length': body.length,
      },
    }

    const req = http.request(options, (res) => {
      let data = ''
      res.on('data', (chunk) => { data += chunk })
      res.on('end', () => {
        try {
          resolve(JSON.parse(data))
        } catch {
          reject(new Error(`Bad response: ${data.slice(0, 200)}`))
        }
      })
    })

    req.on('error', reject)
    req.write(body)
    req.end()
  })
}

function uploadFile(filePath, endpoint) {
  return new Promise((resolve, reject) => {
    const buffer = fs.readFileSync(filePath)
    const ext = path.extname(filePath).toLowerCase().slice(1) || 'png'
    const mimeType = `image/${ext === 'jpg' ? 'jpeg' : ext}`
    const filename = path.basename(filePath)

    const boundary = '----RunLog' + Date.now()
    const fieldName = endpoint === '/api/screenshot/parse' ? 'files' : 'file'
    const header = `--${boundary}\r\nContent-Disposition: form-data; name="${fieldName}"; filename="${filename}"\r\nContent-Type: ${mimeType}\r\n\r\n`
    const footer = `\r\n--${boundary}--\r\n`

    const body = Buffer.concat([Buffer.from(header), buffer, Buffer.from(footer)])

    const url = new URL(API_BASE + endpoint)
    const options = {
      hostname: url.hostname,
      port: url.port,
      path: url.pathname,
      method: 'POST',
      headers: {
        'Content-Type': `multipart/form-data; boundary=${boundary}`,
        'Content-Length': body.length,
      },
    }

    const req = http.request(options, (res) => {
      let data = ''
      res.on('data', (chunk) => { data += chunk })
      res.on('end', () => {
        try {
          resolve(JSON.parse(data))
        } catch {
          reject(new Error(`Bad response: ${data.slice(0, 200)}`))
        }
      })
    })

    req.on('error', reject)
    req.write(body)
    req.end()
  })
}

function showNotification(title, body) {
  if (Notification.isSupported()) {
    new Notification({ title, body, silent: true }).show()
  }
}

function sendToRenderer(channel, data) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send(channel, data)
  }
}

// ── Hotkey handlers ─────────────────────────────────────────────────

async function handleRunScreenshot() {
  showNotification('RunLog', 'Capturing results screenshot...')

  const buffer = await captureScreen()
  if (!buffer) {
    showNotification('RunLog', 'Screenshot capture failed')
    return
  }

  try {
    const parsed = await uploadScreenshot(buffer, '/api/screenshot/parse')
    const status = parsed.survived ? 'EXTRACTED' : 'KIA'
    const kills = (parsed.combatant_eliminations || 0) + (parsed.runner_eliminations || 0)
    showNotification('RunLog - Run Captured', `${status} | ${kills} kills | ${parsed.loot_value_total || 0} loot`)
    sendToRenderer('screenshot-parsed', { type: 'run', data: parsed, timestamp: Date.now() })
  } catch (err) {
    console.error('Upload failed:', err)
    showNotification('RunLog', `Parse failed: ${err.message}`)
  }
}

async function handleSpawnScreenshot() {
  showNotification('RunLog', 'Capturing spawn screenshot...')

  const buffer = await captureScreen()
  if (!buffer) {
    showNotification('RunLog', 'Screenshot capture failed')
    return
  }

  try {
    const parsed = await uploadScreenshot(buffer, '/api/spawns/parse')
    const loc = parsed.spawn_location || parsed.spawn_region || 'Unknown'
    const map = parsed.map_name || 'Unknown map'
    showNotification('RunLog - Spawn Logged', `${map} - ${loc}`)
    sendToRenderer('screenshot-parsed', { type: 'spawn', data: parsed, timestamp: Date.now() })
  } catch (err) {
    console.error('Upload failed:', err)
    showNotification('RunLog', `Parse failed: ${err.message}`)
  }
}

// ── Steam screenshot auto-detection ─────────────────────────────────

function startSteamWatcher() {
  steamWatcher = new SteamScreenshotWatcher(async (filePath, appId) => {
    console.log(`Steam screenshot detected: ${filePath} (app: ${appId})`)
    showNotification('RunLog', `Steam screenshot detected — parsing...`)

    try {
      // Try parsing as run results first (most common use case)
      const parsed = await uploadFile(filePath, '/api/screenshot/parse')

      // If it looks like a results screen (has kills or survived data), treat as run
      if (parsed.survived !== null || parsed.kills > 0 || parsed.loot_value_total > 0) {
        const status = parsed.survived ? 'EXTRACTED' : 'KIA'
        const kills = (parsed.combatant_eliminations || 0) + (parsed.runner_eliminations || 0)
        showNotification('RunLog - Steam Capture', `${status} | ${kills} kills | ${parsed.loot_value_total || 0} loot`)
        sendToRenderer('screenshot-parsed', { type: 'run', data: parsed, timestamp: Date.now() })
      } else {
        // Might be a spawn/map screenshot — try spawn parser
        try {
          const spawnParsed = await uploadFile(filePath, '/api/spawns/parse')
          const loc = spawnParsed.spawn_location || spawnParsed.spawn_region || 'Unknown'
          showNotification('RunLog - Steam Capture', `Spawn: ${spawnParsed.map_name || 'Unknown'} - ${loc}`)
          sendToRenderer('screenshot-parsed', { type: 'spawn', data: spawnParsed, timestamp: Date.now() })
        } catch {
          showNotification('RunLog', 'Screenshot captured but could not parse content')
          sendToRenderer('screenshot-parsed', { type: 'run', data: parsed, timestamp: Date.now() })
        }
      }
    } catch (err) {
      console.error('Steam screenshot parse failed:', err)
      showNotification('RunLog', `Parse failed: ${err.message}`)
    }
  })

  const started = steamWatcher.start()
  if (started) {
    const paths = steamWatcher.getPaths()
    const marathonPath = paths.find(p => p.appId === MARATHON_APP_ID)
    if (marathonPath) {
      console.log(`Steam watcher: Watching Marathon screenshots at ${marathonPath.path}`)
      showNotification('RunLog', `Watching Steam screenshots for Marathon`)
    } else {
      console.log(`Steam watcher: Watching ${paths.length} screenshot folder(s) — Marathon folder not found yet`)
    }
  } else {
    console.log('Steam watcher: Could not find any Steam screenshot folders')
  }
}

// ── Auto-capture screen watcher ──────────────────────────────────────

function startScreenWatcher() {
  screenWatcher = new ScreenWatcher((event) => {
    console.log(`[auto-capture] ${event.type}`, event.state || event.detected || '')

    // Forward all events to renderer
    sendToRenderer('auto-capture-event', event)

    // Handle specific events
    switch (event.type) {
      case 'state_change':
        updateTrayMenu()
        break

      case 'run_ended':
        const outcome = event.survived ? 'EXFILTRATED' : 'ELIMINATED'
        showNotification('RunLog', `${outcome} — capturing results...`)
        // Save clip from recording buffer
        if (recordingManager && recordingManager.isActive()) {
          recordingManager.saveClip(Date.now(), 20, 5, {
            event: event.survived ? 'exfil' : 'death',
          }).then(clip => {
            if (clip) {
              showNotification('RunLog', `Clip saved: ${clip.eventType} (${clip.duration}s)`)
              sendToRenderer('clip-saved', clip)
            }
          }).catch(err => console.error('[clip] Save failed:', err.message))
        }
        break

      case 'results_ready':
        handleAutoResults(event)
        break

      case 'ready_up':
        showNotification('RunLog', 'Ready up detected — capturing loadout...')
        handleReadyUpCapture(event)
        break

      case 'loading_screen':
        showNotification('RunLog', 'Loading into match...')
        break
    }
  })

  screenWatcher.start()
  console.log('[auto-capture] Screen watcher started')
}

async function handleReadyUpCapture(event) {
  if (!event.screenshot) return
  try {
    const parsed = await uploadScreenshot(event.screenshot, '/api/screenshot/parse')
    console.log('[auto-capture] Ready-up parsed:', JSON.stringify(parsed).slice(0, 200))
    // Store pre-run info in the screen watcher's context
    if (screenWatcher) {
      const ctx = screenWatcher.getStatus().runContext
      if (ctx) {
        ctx.shellName = parsed.shell_name || parsed.runner || null
        ctx.mapName = parsed.map_name || null
        ctx.preRunData = parsed
      }
    }
    showNotification('RunLog', `Loadout captured: ${parsed.map_name || 'Unknown map'}`)
    sendToRenderer('screenshot-parsed', { type: 'ready_up', data: parsed, timestamp: Date.now(), auto: true })
  } catch (err) {
    console.error('[auto-capture] Ready-up parse failed:', err.message)
  }
}

async function handleAutoResults(event) {
  const { context, screenshotCount } = event
  if (screenshotCount === 0) {
    console.log('[auto-capture] No screenshots captured for results')
    return
  }

  showNotification('RunLog', `Parsing ${screenshotCount} result screenshot(s)...`)

  // Upload each captured screenshot to Claude for parsing
  for (const ss of context.screenshots) {
    try {
      const parsed = await uploadScreenshot(ss.buffer, '/api/screenshot/parse')
      const status = parsed.survived ? 'EXFILTRATED' : 'KIA'
      const kills = (parsed.combatant_eliminations || 0) + (parsed.runner_eliminations || 0)
      showNotification('RunLog - Auto Capture', `${status} | ${kills} kills | $${parsed.loot_value_total || 0}`)
      sendToRenderer('screenshot-parsed', { type: 'run', data: parsed, timestamp: Date.now(), auto: true })
    } catch (err) {
      console.error('[auto-capture] Parse failed:', err.message)
    }
  }
}

function updateTrayMenu() {
  if (!tray || !screenWatcher) return
  const status = screenWatcher.getStatus()
  const stateLabel = {
    IDLE: 'Idle (Marathon not focused)',
    LOBBY: 'Watching lobby...',
    IN_RUN: 'In run — monitoring...',
    RUN_ENDED: 'Run ended — capturing...',
    RESULTS: 'Capturing results...',
    COOLDOWN: 'Cooldown...',
  }[status.state] || status.state

  const contextMenu = Menu.buildFromTemplate([
    { label: 'Show RunLog', click: () => mainWindow.show() },
    { type: 'separator' },
    {
      label: 'Quit',
      click: () => {
        app.isQuitting = true
        if (steamWatcher) steamWatcher.stop()
        if (screenWatcher) screenWatcher.stop()
        if (recordingManager) recordingManager.stop()
        if (backendManager) backendManager.stop()
        app.quit()
      },
    },
  ])

  tray.setContextMenu(contextMenu)
}

// ── Window ──────────────────────────────────────────────────────────

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 900,
    minHeight: 600,
    backgroundColor: '#0a0a0f',
    frame: false,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js'),
    },
  })

  // In dev mode, load Vite dev server immediately
  // In production, the app lifecycle handler manages loading (backend first)
  if (isDev) {
    mainWindow.loadURL('http://localhost:5173')
  }

  // Minimize to tray instead of closing
  mainWindow.on('close', (e) => {
    if (!app.isQuitting) {
      e.preventDefault()
      mainWindow.hide()
    }
  })
}

// ── Tray ────────────────────────────────────────────────────────────

function createTray() {
  const icon = nativeImage.createFromBuffer(
    Buffer.from(
      'iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAARklEQVQ4T2P8z8Dwn4EIwMjAwMBEjAYGBgYGFmI0MDAwMBAyACRANBBrAMkuINoAkl1AtAEku4BoA0h2AcZoYCBkOzYAAFraEBGVSXgEAAAAAElFTkSuQmCC',
      'base64'
    )
  )

  tray = new Tray(icon)
  tray.setToolTip('RunLog')

  const contextMenu = Menu.buildFromTemplate([
    { label: 'Show RunLog', click: () => mainWindow.show() },
    { type: 'separator' },
    {
      label: 'Quit',
      click: () => {
        app.isQuitting = true
        if (steamWatcher) steamWatcher.stop()
        if (screenWatcher) screenWatcher.stop()
        if (recordingManager) recordingManager.stop()
        if (backendManager) backendManager.stop()
        app.quit()
      },
    },
  ])

  tray.setContextMenu(contextMenu)
  tray.on('double-click', () => mainWindow.show())
}

// ── App lifecycle ───────────────────────────────────────────────────

app.whenReady().then(async () => {
  createWindow()
  createTray()

  // Start backend (production only — dev runs it manually)
  backendManager = new BackendManager((status, message) => {
    console.log(`[backend-manager] ${status}: ${message}`)
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('backend-status', { status, message })
    }
  })

  if (!isDev) {
    // Show loading screen while backend starts
    mainWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(`
      <!DOCTYPE html>
      <html><head><style>
        body { margin: 0; background: #050508; color: #c8ff00; font-family: monospace;
               display: flex; align-items: center; justify-content: center; height: 100vh;
               flex-direction: column; }
        h1 { font-size: 24px; letter-spacing: 0.2em; margin-bottom: 8px; }
        p { color: #555; font-size: 12px; letter-spacing: 0.1em; }
        .dot { display: inline-block; animation: pulse 1.5s infinite; }
        @keyframes pulse { 0%,100% { opacity: 0.3; } 50% { opacity: 1; } }
      </style></head><body>
        <h1>RUNLOG</h1>
        <p>STARTING BACKEND<span class="dot">...</span></p>
      </body></html>
    `)}`)

    const started = await backendManager.start()
    if (started) {
      mainWindow.loadFile(path.join(__dirname, '../dist/index.html'))
    } else {
      mainWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(`
        <!DOCTYPE html>
        <html><head><style>
          body { margin: 0; background: #050508; color: #ff4444; font-family: monospace;
                 display: flex; align-items: center; justify-content: center; height: 100vh;
                 flex-direction: column; }
          h1 { font-size: 20px; letter-spacing: 0.2em; margin-bottom: 12px; }
          p { color: #888; font-size: 12px; max-width: 400px; text-align: center; line-height: 1.6; }
        </style></head><body>
          <h1>BACKEND ERROR</h1>
          <p>Could not start the Python backend. Make sure Python 3.12+ is installed and all dependencies are available.</p>
        </body></html>
      `)}`)
    }
  }

  // Start watching Steam screenshot folder
  startSteamWatcher()

  // Start recording manager (FFmpeg continuous capture)
  const userDataPath = app.getPath('userData')
  recordingManager = new RecordingManager({
    segmentsDir: path.join(userDataPath, 'recordings', 'segments'),
    keyframesDir: path.join(userDataPath, 'recordings', 'keyframes'),
    clipsDir: path.join(userDataPath, 'recordings', 'clips'),
  }, (status, message) => {
    console.log(`[recording] ${status}: ${message}`)
    sendToRenderer('recording-status', { status, message })
  })
  recordingManager.start()

  // Start auto-capture screen watcher (uses keyframes from recording manager)
  startScreenWatcher()
  if (screenWatcher && recordingManager) {
    screenWatcher.setKeyframesDir(path.join(userDataPath, 'recordings', 'keyframes'))
  }

  console.log('=== Marathon RunLog ===')
  console.log('Hotkeys:')
  console.log('  Ctrl+Shift+F5 → Capture run results')
  console.log('  Ctrl+Shift+F6 → Capture spawn location')
  console.log('  F12 (Steam)   → Auto-detected and parsed')
  console.log('  Auto-capture  → Watching for game states')
})

app.on('will-quit', () => {
  if (steamWatcher) steamWatcher.stop()
  if (screenWatcher) screenWatcher.stop()
  if (recordingManager) recordingManager.stop()
  if (backendManager) backendManager.stop()
})

app.on('window-all-closed', () => {
  // Don't quit — stay in tray
})

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow()
  else mainWindow.show()
})

// IPC: let renderer request a screenshot manually
ipcMain.handle('capture-run', handleRunScreenshot)
ipcMain.handle('capture-spawn', handleSpawnScreenshot)

// IPC: window controls
ipcMain.on('window-minimize', () => mainWindow?.minimize())
ipcMain.on('window-maximize', () => {
  if (mainWindow?.isMaximized()) mainWindow.unmaximize()
  else mainWindow?.maximize()
})
ipcMain.on('window-close', () => {
  if (mainWindow) {
    mainWindow.hide()
  }
})

// IPC: API base URL for renderer
ipcMain.on('get-api-base-url', (event) => {
  event.returnValue = isDev ? '' : 'http://127.0.0.1:8000'
})
