const { app, BrowserWindow, Tray, Menu, Notification, nativeImage, ipcMain, dialog } = require('electron')
const path = require('path')
const fs = require('fs')
const http = require('http')
const { BackendManager } = require('./backend-manager')
const { RecordingManager } = require('./recording-manager')

const isDev = !app.isPackaged

// ── Window state persistence ─────────────────────────────────────────
const stateFile = path.join(app.getPath('userData'), 'window-state.json')

function loadWindowState() {
  try {
    return JSON.parse(fs.readFileSync(stateFile, 'utf-8'))
  } catch { return null }
}

function saveWindowState() {
  if (!mainWindow || mainWindow.isDestroyed()) return
  const bounds = mainWindow.getBounds()
  const isMaximized = mainWindow.isMaximized()
  fs.writeFileSync(stateFile, JSON.stringify({ ...bounds, isMaximized }))
}

let mainWindow = null
let tray = null
let backendManager = null
let recordingManager = null

// ── Helpers ────────────────────────────────────────────────────────

function showNotification(title, body) {
  if (Notification.isSupported()) {
    new Notification({ title, body, silent: true }).show()
  }
}

function checkProcessingActive() {
  return new Promise((resolve) => {
    const req = http.get('http://127.0.0.1:8000/api/capture/status', (res) => {
      let data = ''
      res.on('data', (chunk) => { data += chunk })
      res.on('end', () => {
        try {
          const status = JSON.parse(data)
          const items = status.processing_items || []
          const active = items.filter(i =>
            !['done', 'error', 'queued'].includes(i.status)
          )
          resolve(active.length)
        } catch { resolve(0) }
      })
    })
    req.on('error', () => resolve(0))
    req.setTimeout(2000, () => { req.destroy(); resolve(0) })
  })
}

async function confirmQuitIfProcessing() {
  const activeCount = await checkProcessingActive()
  if (activeCount > 0 && mainWindow && !mainWindow.isDestroyed()) {
    const { response } = await dialog.showMessageBox(mainWindow, {
      type: 'warning',
      buttons: ['Cancel', 'Close Anyway'],
      defaultId: 0,
      cancelId: 0,
      title: 'Processing Active',
      message: `${activeCount} video${activeCount > 1 ? 's are' : ' is'} still being processed by Sonnet.`,
      detail: 'Closing now will cancel the analysis. The recording will be auto-resumed next time you open RunLog.',
    })
    return response === 1 // "Close Anyway"
  }
  return true // nothing processing, safe to quit
}

function sendToRenderer(channel, data) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send(channel, data)
  }
}

// ── Window ──────────────────────────────────────────────────────────

function createWindow() {
  const saved = loadWindowState()
  mainWindow = new BrowserWindow({
    width: saved?.width || 1400,
    height: saved?.height || 900,
    x: saved?.x,
    y: saved?.y,
    minWidth: 900,
    minHeight: 600,
    backgroundColor: '#0a0a0f',
    frame: false,
    icon: path.join(__dirname, 'icon.ico'),
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      webSecurity: false,
      preload: path.join(__dirname, 'preload.js'),
    },
  })
  if (saved?.isMaximized) mainWindow.maximize()

  // Save position/size on move and resize
  mainWindow.on('resize', saveWindowState)
  mainWindow.on('move', saveWindowState)
  mainWindow.on('maximize', saveWindowState)
  mainWindow.on('unmaximize', saveWindowState)

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
      click: async () => {
        const canQuit = await confirmQuitIfProcessing()
        if (!canQuit) return
        app.isQuitting = true
        if (recordingManager) recordingManager.stop()
        if (backendManager) backendManager.stop()
        app.quit()
      },
    },
  ])

  tray.setContextMenu(contextMenu)
  tray.on('double-click', () => mainWindow.show())
}

// ── Single instance lock ─────────────────────────────────────────────

const gotTheLock = app.requestSingleInstanceLock()
if (!gotTheLock) {
  app.quit()
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      mainWindow.show()
      if (mainWindow.isMinimized()) mainWindow.restore()
      mainWindow.focus()
    }
  })
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
          <p>Could not start the Python backend. Make sure Python 3.12+ is installed.</p>
        </body></html>
      `)}`)
    }
  }

  // Start recording manager (monitors Marathon, controls capture)
  // Delay startup so frontend finishes initial data load first —
  // WGC + OCR model loading + resume queue all compete for resources on launch
  const startRecordingManager = () => {
    recordingManager = new RecordingManager((status, message) => {
      console.log(`[recording] ${status}: ${message}`)
      sendToRenderer('recording-status', { status, message })

      // Show notifications for key events
      if (status === 'recording_started') {
        showNotification('RunLog', 'Recording started — READY UP detected')
      } else if (status === 'recording_stopped') {
        showNotification('RunLog', 'Recording stopped — sending to Sonnet...')
      } else if (status === 'run_processed') {
        showNotification('RunLog', `Run analyzed — ${message}`)
      } else if (status === 'active') {
        showNotification('RunLog', 'Marathon detected — watching for READY UP')
      }
    })
    recordingManager.start()
    console.log('=== RunLog ===')
    console.log('  Auto-capture active')
    console.log('  Recording starts when Marathon detected + READY UP screen')
  }

  if (!isDev) {
    // Production: only start if backend is up, delay 5s for frontend to finish loading
    if (backendManager && await backendManager._healthCheck()) {
      setTimeout(startRecordingManager, 5000)
    } else {
      console.log('[recording] Backend not ready, skipping recording manager')
    }
  } else {
    // Dev: start immediately (backend managed manually)
    startRecordingManager()
  }
})

app.on('will-quit', () => {
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
ipcMain.on('window-close', async () => {
  const activeCount = await checkProcessingActive()
  if (activeCount > 0 && mainWindow && !mainWindow.isDestroyed()) {
    const { response } = await dialog.showMessageBox(mainWindow, {
      type: 'question',
      buttons: ['Minimize to Tray', 'Close Anyway'],
      defaultId: 0,
      cancelId: 0,
      title: 'Processing Active',
      message: `${activeCount} video${activeCount > 1 ? 's are' : ' is'} still being processed.`,
      detail: 'Minimizing to tray will keep processing running in the background.',
    })
    if (response === 0) {
      mainWindow.hide()
    } else {
      app.isQuitting = true
      if (recordingManager) recordingManager.stop()
      if (backendManager) backendManager.stop()
      app.quit()
    }
  } else {
    mainWindow?.hide()
  }
})
ipcMain.on('get-api-base-url', (event) => {
  event.returnValue = isDev ? '' : 'http://127.0.0.1:8000'
})
