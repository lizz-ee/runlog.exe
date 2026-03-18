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
  tray.setToolTip('runlog.exe')

  const contextMenu = Menu.buildFromTemplate([
    { label: 'Show runlog.exe', click: () => mainWindow.show() },
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
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { background: #050508; color: #c8ff00; font-family: 'Consolas', 'Courier New', monospace;
               display: flex; align-items: center; justify-content: center; height: 100vh;
               flex-direction: column; -webkit-app-region: drag; overflow: hidden; position: relative; }

        /* Scanline overlay */
        body::before { content: ''; position: fixed; inset: 0; z-index: 10; pointer-events: none;
          background: repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(0,0,0,0.08) 2px, rgba(0,0,0,0.08) 4px); }

        /* Animated grid background */
        body::after { content: ''; position: fixed; inset: -50%; z-index: 0; pointer-events: none; opacity: 0.04;
          background-image: linear-gradient(#c8ff00 1px, transparent 1px), linear-gradient(90deg, #c8ff00 1px, transparent 1px);
          background-size: 40px 40px; animation: gridDrift 20s linear infinite; }
        @keyframes gridDrift { 0% { transform: translate(0,0) rotate(0deg); } 100% { transform: translate(40px,40px) rotate(0.5deg); } }

        .content { position: relative; z-index: 5; display: flex; flex-direction: column; align-items: center; }

        /* Glitch title */
        .title { font-size: 32px; font-weight: 900; letter-spacing: 0.3em; margin: 0; position: relative;
          text-shadow: 0 0 20px rgba(200,255,0,0.4), 0 0 60px rgba(200,255,0,0.15), 0 0 100px rgba(200,255,0,0.05);
          animation: glitch 4s infinite; }
        @keyframes glitch {
          0%, 94%, 100% { transform: translate(0); filter: none; }
          95% { transform: translate(-2px, 1px); filter: hue-rotate(90deg); }
          96% { transform: translate(2px, -1px); filter: hue-rotate(-90deg); }
          97% { transform: translate(0); filter: none; }
        }

        .sub { color: #c8ff0035; font-size: 9px; letter-spacing: 0.4em; margin-top: 4px; }

        /* Corner brackets */
        .corner { position: fixed; width: 30px; height: 30px; border-color: #c8ff0015; border-style: solid; z-index: 5; }
        .tl { top: 20px; left: 20px; border-width: 1px 0 0 1px; }
        .tr { top: 20px; right: 20px; border-width: 1px 1px 0 0; }
        .bl { bottom: 20px; left: 20px; border-width: 0 0 1px 1px; }
        .br { bottom: 20px; right: 20px; border-width: 0 1px 1px 0; }

        /* Hex decoration */
        .hex { position: fixed; font-size: 8px; color: #111; letter-spacing: 0.1em; z-index: 1; }
        .hex-tl { top: 24px; left: 56px; }
        .hex-br { bottom: 24px; right: 56px; }

        /* Animated scan line */
        .line-wrap { width: 240px; height: 1px; margin-top: 28px; position: relative; background: #c8ff0008; overflow: hidden; }
        .line-scan { position: absolute; top: 0; left: -50%; width: 50%; height: 100%;
          background: linear-gradient(90deg, transparent, #c8ff00, transparent);
          animation: scan 1.8s ease-in-out infinite; }
        @keyframes scan { 0% { left: -50%; } 100% { left: 100%; } }

        /* Vertical scan bar */
        .vscan { position: fixed; top: 0; left: 0; width: 100%; height: 2px; z-index: 8; pointer-events: none;
          background: linear-gradient(180deg, rgba(200,255,0,0.06), transparent);
          box-shadow: 0 0 20px rgba(200,255,0,0.03);
          animation: vscan 3s linear infinite; }
        @keyframes vscan { 0% { top: -2px; } 100% { top: 100%; } }

        /* Boot log */
        .boot { margin-top: 24px; text-align: left; width: 320px; }
        .boot-line { color: #282828; font-size: 10px; letter-spacing: 0.1em; line-height: 2;
          opacity: 0; animation: fadeSlide 0.4s forwards; }
        .boot-line .ok { color: #c8ff0050; }
        .boot-line.active { color: #c8ff0080; }
        .boot-line:nth-child(1) { animation-delay: 0.1s; }
        .boot-line:nth-child(2) { animation-delay: 0.4s; }
        .boot-line:nth-child(3) { animation-delay: 0.8s; }
        .boot-line:nth-child(4) { animation-delay: 1.2s; }
        .boot-line:nth-child(5) { animation-delay: 1.6s; }
        .boot-line:nth-child(6) { animation-delay: 2.0s; }
        @keyframes fadeSlide { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }

        .blink { animation: blink 0.7s step-end infinite; }
        @keyframes blink { 50% { opacity: 0; } }

        .ver { color: #151515; font-size: 8px; letter-spacing: 0.3em; position: fixed; bottom: 16px; }
      </style></head><body>
        <div class="corner tl"></div><div class="corner tr"></div>
        <div class="corner bl"></div><div class="corner br"></div>
        <div class="hex hex-tl">0x4D415241</div>
        <div class="hex hex-br">0x54484F4E</div>
        <div class="vscan"></div>

        <div class="content">
          <p class="title">RUNLOG.EXE</p>
          <p class="sub">MARATHON // EXTRACTION TRACKER</p>

          <div class="line-wrap"><div class="line-scan"></div></div>

          <div class="boot" id="boot"></div>
          <script>
            const lines = [
              { text: 'SYS.INIT', delay: 100, okDelay: 300 },
              { text: 'LOADING MODULES', delay: 500, okDelay: 400 },
              { text: 'SPAWNING BACKEND PROCESS', delay: 1000, okDelay: 600 },
              { text: 'CONNECTING TO FASTAPI', delay: 1700, okDelay: 500 },
              { text: 'INITIALIZING CAPTURE ENGINE', delay: 2300, okDelay: 700 },
            ];
            const boot = document.getElementById('boot');
            lines.forEach((l) => {
              const p = document.createElement('p');
              p.className = 'boot-line';
              p.style.animationDelay = l.delay + 'ms';
              p.innerHTML = '> ' + l.text;
              boot.appendChild(p);
              setTimeout(() => {
                p.innerHTML = '> ' + l.text + ' <span class="ok">[OK]</span>';
              }, l.delay + l.okDelay);
            });
            const standby = document.createElement('p');
            standby.className = 'boot-line active';
            standby.style.animationDelay = '3100ms';
            standby.innerHTML = '> STANDING BY<span class="blink">_</span>';
            boot.appendChild(standby);
          </script>
        </div>
        <p class="ver">v1.0.0 // LOCAL FIRST // NO TELEMETRY</p>
      </body></html>
    `)}`)

    const started = await backendManager.start()
    if (started) {
      mainWindow.loadFile(path.join(__dirname, '../dist/index.html'))
    } else {
      mainWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(`
        <!DOCTYPE html>
        <html><head><style>
          body { margin: 0; background: #050508; color: #ff4444; font-family: 'Consolas', 'Courier New', monospace;
                 display: flex; align-items: center; justify-content: center; height: 100vh;
                 flex-direction: column; -webkit-app-region: drag; }
          .title { font-size: 22px; font-weight: 900; letter-spacing: 0.25em; margin: 0; }
          .err { color: #ff4444; font-size: 11px; letter-spacing: 0.15em; margin-top: 16px; }
          p { color: #555; font-size: 11px; max-width: 400px; text-align: center; line-height: 1.8; letter-spacing: 0.05em; margin-top: 8px; }
        </style></head><body>
          <p class="title">RUNLOG.EXE</p>
          <p class="err">// BACKEND.ERROR</p>
          <p>Could not start the Python backend.<br>Make sure Python 3.12+ is installed and on PATH.</p>
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
        showNotification('runlog.exe', 'Recording started — READY UP detected')
      } else if (status === 'recording_stopped') {
        showNotification('runlog.exe', 'Recording stopped — sending to Sonnet...')
      } else if (status === 'run_processed') {
        showNotification('runlog.exe', `Run analyzed — ${message}`)
      } else if (status === 'active') {
        showNotification('runlog.exe', 'Marathon detected — watching for READY UP')
      }
    })
    recordingManager.start()
    console.log('=== runlog.exe ===')
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
