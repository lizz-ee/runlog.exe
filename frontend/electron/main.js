const { app, BrowserWindow, Tray, Menu, Notification, nativeImage, ipcMain } = require('electron')
const path = require('path')
const { BackendManager } = require('./backend-manager')
const { RecordingManager } = require('./recording-manager')

const isDev = !app.isPackaged

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

function sendToRenderer(channel, data) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send(channel, data)
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
          <p>Could not start the Python backend. Make sure Python 3.12+ is installed.</p>
        </body></html>
      `)}`)
    }
  }

  // Start recording manager (monitors Marathon, controls capture)
  recordingManager = new RecordingManager((status, message) => {
    console.log(`[recording] ${status}: ${message}`)
    sendToRenderer('recording-status', { status, message })

    // Show notifications for key events
    if (status === 'recording_started') {
      showNotification('RunLog', 'Recording started — READY UP detected')
    } else if (status === 'recording_stopped') {
      showNotification('RunLog', 'Recording stopped — processing run...')
    } else if (status === 'active') {
      showNotification('RunLog', 'Marathon detected — watching for READY UP')
    }
  })
  recordingManager.start()

  console.log('=== RunLog ===')
  console.log('  Auto-capture active')
  console.log('  Recording starts when Marathon detected + READY UP screen')
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
ipcMain.on('window-close', () => mainWindow?.hide())
ipcMain.on('get-api-base-url', (event) => {
  event.returnValue = isDev ? '' : 'http://127.0.0.1:8000'
})
