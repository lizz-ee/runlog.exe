const { app, BrowserWindow, Tray, Menu, Notification, nativeImage, ipcMain } = require('electron')
const path = require('path')
const { ScreenWatcher } = require('./screen-watcher')
const { BackendManager } = require('./backend-manager')
const { RecordingManager } = require('./recording-manager')

const isDev = !app.isPackaged

let mainWindow = null
let tray = null
let backendManager = null
let recordingManager = null
let screenWatcher = null

// ── Helpers ────────────────────────────────────────────────────────

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

// ── Auto-capture screen watcher ──────────────────────────────────

function startScreenWatcher() {
  screenWatcher = new ScreenWatcher((event) => {
    console.log(`[auto-capture] ${event.type}`, event.state || event.detected || '')
    sendToRenderer('auto-capture-event', event)

    switch (event.type) {
      case 'run_ended':
        const outcome = event.survived ? 'EXFILTRATED' : 'ELIMINATED'
        showNotification('RunLog', `${outcome} — capturing results...`)
        // Save clip from recording buffer
        if (recordingManager && recordingManager.isActive()) {
          recordingManager.saveClip(20, 5, {
            event: event.survived ? 'exfil' : 'death',
          }).then(clip => {
            if (clip) {
              showNotification('RunLog', `Clip saved: ${clip.filename}`)
              sendToRenderer('clip-saved', clip)
            }
          }).catch(err => console.error('[clip] Save failed:', err.message))
        }
        break

      case 'loading_screen':
        showNotification('RunLog', 'Loading into match...')
        break

      case 'run_auto_logged':
        handleAutoLog(event)
        break
    }
  })

  screenWatcher.start()
  console.log('[auto-capture] Screen watcher started')
}

// ── Auto-log run to database ──────────────────────────────────────

async function handleAutoLog(event) {
  const { run } = event
  if (!run) return

  console.log('[auto-log] Logging run:', JSON.stringify(run).slice(0, 200))

  try {
    const body = JSON.stringify({
      runner_id: 5, // Triage (default shell)
      map_name: run.map_name,
      survived: run.survived,
      kills: run.kills || 0,
      combatant_eliminations: run.combatant_eliminations || 0,
      runner_eliminations: run.runner_eliminations || 0,
      deaths: run.deaths || 0,
      assists: run.assists || 0,
      crew_revives: run.crew_revives || 0,
      loot_value_total: run.loot_value_total || 0,
      duration_seconds: run.duration_seconds || null,
      primary_weapon: run.primary_weapon || null,
      secondary_weapon: run.secondary_weapon || null,
      killed_by: run.killed_by || null,
      killed_by_damage: run.killed_by_damage || null,
      squad_size: run.squad_size || 1,
      notes: run.notes || null,
    })

    const http = require('http')
    const req = http.request({
      hostname: '127.0.0.1',
      port: 8000,
      path: '/api/runs/',
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(body),
      },
    }, (res) => {
      let data = ''
      res.on('data', chunk => data += chunk)
      res.on('end', () => {
        try {
          const result = JSON.parse(data)
          const outcome = run.survived ? 'EXFILTRATED' : 'ELIMINATED'
          const kills = (run.combatant_eliminations || 0) + (run.runner_eliminations || 0)
          showNotification('RunLog', `Run logged: ${outcome} | ${kills} kills | $${run.loot_value_total || 0}`)
          console.log(`[auto-log] Run saved: id=${result.id}`)
          sendToRenderer('run-auto-logged', result)
        } catch (e) {
          console.error('[auto-log] Parse response error:', e.message)
        }
      })
    })

    req.on('error', (err) => {
      console.error('[auto-log] POST failed:', err.message)
      showNotification('RunLog', `Failed to log run: ${err.message}`)
    })

    req.write(body)
    req.end()
  } catch (err) {
    console.error('[auto-log] Error:', err.message)
  }
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
    icon: path.join(__dirname, 'icon.ico'),
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js'),
    },
  })

  if (isDev) {
    mainWindow.loadURL('http://localhost:5173')
  }

  mainWindow.on('close', (e) => {
    if (!app.isQuitting) {
      e.preventDefault()
      mainWindow.hide()
    }
  })
}

// ── Tray ────────────────────────────────────────────────────────────

function createTray() {
  const icon = nativeImage.createFromPath(path.join(__dirname, 'icon.png'))

  tray = new Tray(icon)
  tray.setToolTip('RunLog')

  const contextMenu = Menu.buildFromTemplate([
    { label: 'Show RunLog', click: () => mainWindow.show() },
    { type: 'separator' },
    {
      label: 'Quit',
      click: () => {
        app.isQuitting = true
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

  // Start backend
  backendManager = new BackendManager((status, message) => {
    console.log(`[backend-manager] ${status}: ${message}`)
    sendToRenderer('backend-status', { status, message })
  })

  if (!isDev) {
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

  // Start recording manager (capture engine via API)
  recordingManager = new RecordingManager({}, (status, message) => {
    console.log(`[recording] ${status}: ${message}`)
    sendToRenderer('recording-status', { status, message })
  })
  recordingManager.start()

  // Start auto-capture screen watcher
  startScreenWatcher()

  console.log('=== RunLog ===')
  console.log('  Auto-capture active')
  console.log('  Recording starts when Marathon is detected')
})

app.on('will-quit', () => {
  if (screenWatcher) screenWatcher.stop()
  if (recordingManager) recordingManager.stop()
  if (backendManager) backendManager.stop()
})

app.on('window-all-closed', () => {})

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow()
  else mainWindow.show()
})

// ── IPC ─────────────────────────────────────────────────────────────

ipcMain.on('window-minimize', () => mainWindow?.minimize())
ipcMain.on('window-maximize', () => {
  if (mainWindow?.isMaximized()) mainWindow.unmaximize()
  else mainWindow?.maximize()
})
ipcMain.on('window-close', () => mainWindow?.hide())
ipcMain.on('get-api-base-url', (event) => {
  event.returnValue = isDev ? '' : 'http://127.0.0.1:8000'
})
