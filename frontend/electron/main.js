const { app, BrowserWindow, Tray, Menu, Notification, nativeImage, ipcMain, dialog, powerSaveBlocker } = require('electron')
const path = require('path')
const fs = require('fs')

// Prevent Windows from throttling/suspending this app when backgrounded
const powerBlockerId = powerSaveBlocker.start('prevent-app-suspension')
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
let overlayWindow = null
let tray = null
let backendManager = null
let recordingManager = null

// ── Helpers ────────────────────────────────────────────────────────

// ── Overlay settings ──────────────────────────────────────────────
const overlaySettingsFile = path.join(app.getPath('userData'), 'overlay-settings.json')

function loadOverlaySettings() {
  try {
    return JSON.parse(fs.readFileSync(overlaySettingsFile, 'utf-8'))
  } catch { return { enabled: true, corner: 'top-left' } }
}

function saveOverlaySettings(settings) {
  try { fs.writeFileSync(overlaySettingsFile, JSON.stringify(settings)) } catch {}
}

function getOverlayPosition(corner) {
  const { screen } = require('electron')
  const display = screen.getPrimaryDisplay()
  const { width, height } = display.size  // Always use full screen size
  const w = 260, h = 30
  const bottomY = height - h
  switch (corner) {
    case 'top-right': return { x: width - w, y: 0 }
    case 'top-center': return { x: Math.round((width - w) / 2), y: 0 }
    case 'bottom-left': return { x: 0, y: bottomY }
    case 'bottom-center': return { x: Math.round((width - w) / 2), y: bottomY }
    case 'bottom-right': return { x: width - w, y: bottomY }
    default: return { x: 0, y: 0 } // top-left
  }
}

function createOverlay() {
  const settings = loadOverlaySettings()
  if (!settings.enabled) return
  if (overlayWindow) return
  const pos = (settings.customX != null && settings.customY != null)
    ? { x: settings.customX, y: settings.customY }
    : getOverlayPosition(settings.corner || 'top-left')
  overlayWindow = new BrowserWindow({
    width: 260,
    height: 30,
    x: pos.x,
    y: pos.y,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    skipTaskbar: true,
    focusable: false,
    resizable: false,
    hasShadow: false,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      backgroundThrottling: false,
    },
  })
  overlayWindow.setIgnoreMouseEvents(true)
  overlayWindow.setAlwaysOnTop(true, 'screen-saver')  // Highest z-level — stays above fullscreen games
  overlayWindow.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true })

  const overlayHTML = `<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&display=swap');
* { margin: 0; padding: 0; box-sizing: border-box; }
body { background: transparent; overflow: hidden; user-select: none; -webkit-app-region: no-drag; }
#bar { background: rgba(5,5,8,0.88); border-bottom: 1px solid rgba(200,255,0,0.15);
       border-right: 1px solid rgba(200,255,0,0.08);
       padding: 0 10px; font: 700 11px 'JetBrains Mono', monospace; letter-spacing: 0.18em;
       color: rgba(200,255,0,0.5); display: flex; align-items: center; gap: 0; height: 30px;
       position: relative; overflow: hidden; }
#bar::after { content: ''; position: absolute; bottom: 0; left: 0; right: 0; height: 1px;
              background: linear-gradient(90deg, rgba(200,255,0,0.3), transparent 60%); }
#sym { color: rgba(200,255,0,0.25); margin-right: 6px; font-size: 12px; }
#main { color: rgba(200,255,0,0.6); }
#sep { color: rgba(200,255,0,0.15); margin: 0 6px; }
#aux { color: rgba(200,255,0,0.25); font-size: 9px; letter-spacing: 0.25em; }
#bar.rec { border-color: rgba(255,60,60,0.3); }
#bar.rec::after { background: linear-gradient(90deg, rgba(255,60,60,0.4), transparent 60%); }
#bar.rec #sym { color: rgba(255,60,60,0.7); animation: pulse 1.2s infinite; }
#bar.rec #main { color: rgba(255,60,60,0.75); }
#bar.rec #aux { color: rgba(255,60,60,0.25); }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.2} }
</style></head><body>
<div id="bar">
  <span id="sym">&#x25C8;</span>
  <span id="main">RUNLOG.EXE</span>
  <span id="sep">&#x2500;&#x2500;</span>
  <span id="aux">INIT</span>
</div>
<script>
window.updateOverlay = function(s, d) {
  var bar = document.getElementById('bar');
  var sym = document.getElementById('sym');
  var main = document.getElementById('main');
  var aux = document.getElementById('aux');
  if (s === 'recording') {
    bar.className = 'rec';
    sym.innerHTML = '&#x25A0;';
    var parts = (d||'').split('|');
    main.textContent = 'REC ' + parts[0];
    aux.textContent = parts[1] || 'CAPTURE::LOCK';
  } else {
    bar.className = '';
    sym.innerHTML = '&#x25C8;';
    if (d && d !== 'WATCHING') {
      main.textContent = 'DET: ' + d;
      aux.textContent = '4K.WGC';
    } else {
      main.textContent = 'RUNLOG.EXE';
      aux.textContent = 'SCAN.ACTIVE';
    }
  }
};
</script></body></html>`

  overlayWindow.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(overlayHTML))
  overlayWindow.on('closed', () => { overlayWindow = null })
}

function updateOverlay(state, detail) {
  if (!overlayWindow) return
  overlayWindow.webContents.executeJavaScript(
    `window.updateOverlay && window.updateOverlay('${state}', '${(detail || '').replace(/'/g, "\\'")}')`,
  ).catch(() => {})
}

function showNotification(title, body) {
  // Replaced by overlay — no more Windows popups
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
      webSecurity: true,
      preload: path.join(__dirname, 'preload.js'),
      backgroundThrottling: false,  // Keep OCR/detection running at full speed when alt-tabbed
    },
  })
  if (saved?.isMaximized) mainWindow.maximize()

  // Create overlay on startup
  createOverlay()

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
        .tl { top: 1rem; left: 1rem; border-width: 1px 0 0 1px; }
        .tr { top: 1rem; right: 1rem; border-width: 1px 1px 0 0; }
        .bl { bottom: 1rem; left: 1rem; border-width: 0 0 1px 1px; }
        .br { bottom: 1rem; right: 1rem; border-width: 0 1px 1px 0; }

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

      // Update overlay for key events (create on first event if not already)
      if (!overlayWindow) createOverlay()
      if (status === 'recording_started') {
        updateOverlay('recording', '')
      } else if (status === 'recording_stopped') {
        updateOverlay('active', 'PROCESSING')
      } else if (status === 'run_processed') {
        updateOverlay('active', 'COMPLETE')
        // Hide overlay after 5s
        setTimeout(() => updateOverlay('active', 'WATCHING'), 5000)
      } else if (status === 'active') {
        createOverlay()
        updateOverlay('active', 'WATCHING')
      }
    })
    recordingManager.start()
    console.log('=== runlog.exe ===')
    console.log('  Auto-capture active')
    console.log('  Recording starts when deployment screen detected')
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
ipcMain.on('overlay-update', (_event, state, detail) => {
  updateOverlay(state, detail)
})
ipcMain.on('overlay-toggle', (_event, enabled) => {
  const settings = loadOverlaySettings()
  settings.enabled = enabled
  saveOverlaySettings(settings)
  if (enabled) {
    createOverlay()
    updateOverlay('active', 'WATCHING')
  } else if (overlayWindow) {
    overlayWindow.close()
    overlayWindow = null
  }
})
ipcMain.on('overlay-set-corner', (_event, corner) => {
  const settings = loadOverlaySettings()
  settings.corner = corner
  delete settings.customX
  delete settings.customY
  saveOverlaySettings(settings)
  if (overlayWindow) {
    const pos = getOverlayPosition(corner)
    overlayWindow.setBounds({ x: pos.x, y: pos.y, width: 260, height: 30 })
  }
})
ipcMain.on('overlay-nudge', (_event, direction) => {
  if (!overlayWindow) return
  const { screen } = require('electron')
  const display = screen.getPrimaryDisplay()
  const { width, height } = display.size
  const bounds = overlayWindow.getBounds()
  const step = 10
  let { x, y } = bounds
  if (direction === 'up') y = Math.max(0, y - step)
  if (direction === 'down') y = Math.min(height - bounds.height, y + step)
  if (direction === 'left') x = Math.max(0, x - step)
  if (direction === 'right') x = Math.min(width - bounds.width, x + step)
  overlayWindow.setBounds({ x, y, width: bounds.width, height: bounds.height })
  // Save custom position
  const settings = loadOverlaySettings()
  settings.customX = x
  settings.customY = y
  saveOverlaySettings(settings)
})
ipcMain.handle('overlay-get-settings', () => loadOverlaySettings())

ipcMain.on('open-file', (_event, filePath) => {
  const { shell } = require('electron')
  if (filePath && fs.existsSync(filePath)) {
    shell.openPath(filePath)
  }
})
