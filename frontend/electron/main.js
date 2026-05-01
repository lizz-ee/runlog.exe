const { app, BrowserWindow, Tray, Menu, Notification, nativeImage, ipcMain, dialog, powerSaveBlocker, shell } = require('electron')
const path = require('path')
const fs = require('fs')

const http = require('http')
const { BackendManager, API_PORT } = require('./backend-manager')
const { RecordingManager } = require('./recording-manager')

// Auto-updater — uncomment when code signing + GitHub releases are configured
// const { initAutoUpdater } = require('./auto-updater')

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
let powerBlockerId = null

// ── Helpers ────────────────────────────────────────────────────────

function isTrustedAppUrl(rawUrl) {
  try {
    const url = new URL(rawUrl)
    if (isDev) {
      return (
        (url.hostname === 'localhost' || url.hostname === '127.0.0.1') &&
        url.port === '5173'
      )
    }
    return url.protocol === 'file:' || url.protocol === 'data:'
  } catch {
    return false
  }
}

function isSafeExternalUrl(rawUrl) {
  try {
    return new URL(rawUrl).protocol === 'https:'
  } catch {
    return false
  }
}

function clampNumber(value, min, max, fallback) {
  const number = Number(value)
  if (!Number.isFinite(number)) return fallback
  return Math.min(max, Math.max(min, number))
}

function hardenWindowNavigation(win) {
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (isSafeExternalUrl(url)) {
      shell.openExternal(url).catch(() => {})
    }
    return { action: 'deny' }
  })

  win.webContents.on('will-navigate', (event, url) => {
    if (isTrustedAppUrl(url)) return
    event.preventDefault()
    if (isSafeExternalUrl(url)) {
      shell.openExternal(url).catch(() => {})
    }
  })
}

function setRecordingPowerBlocker(active) {
  if (active) {
    if (powerBlockerId == null) {
      powerBlockerId = powerSaveBlocker.start('prevent-app-suspension')
    }
    return
  }
  if (powerBlockerId != null && powerSaveBlocker.isStarted(powerBlockerId)) {
    powerSaveBlocker.stop(powerBlockerId)
  }
  powerBlockerId = null
}

// ── Overlay settings ──────────────────────────────────────────────
const overlaySettingsFile = path.join(app.getPath('userData'), 'overlay-settings.json')

const OVERLAY_SIZES = {
  small: { width: 250, height: 24, fontSize: 9 },
  medium: { width: 290, height: 30, fontSize: 11 },
  large: { width: 360, height: 38, fontSize: 14 },
}

const OVERLAY_CORNERS = new Set([
  'top-left',
  'top-center',
  'top-right',
  'bottom-left',
  'bottom-center',
  'bottom-right',
])

function hasOverlaySize(size) {
  return Object.prototype.hasOwnProperty.call(OVERLAY_SIZES, size)
}

function normalizeOverlaySettings(rawSettings) {
  const source = rawSettings && typeof rawSettings === 'object' ? rawSettings : {}
  const settings = { ...source }
  settings.enabled = settings.enabled !== false
  settings.corner = OVERLAY_CORNERS.has(settings.corner) || settings.corner === 'custom'
    ? settings.corner
    : 'top-left'
  settings.opacity = clampNumber(settings.opacity, 40, 100, 88)
  settings.size = hasOverlaySize(settings.size) ? settings.size : 'medium'

  if (settings.corner === 'custom') {
    settings.customX = clampNumber(settings.customX, 0, 100, 0)
    settings.customY = clampNumber(settings.customY, 0, 100, 0)
  } else {
    delete settings.customX
    delete settings.customY
  }

  return settings
}

function loadOverlaySettings() {
  try {
    return normalizeOverlaySettings(JSON.parse(fs.readFileSync(overlaySettingsFile, 'utf-8')))
  } catch { return normalizeOverlaySettings({ enabled: true, corner: 'top-left' }) }
}

function saveOverlaySettings(settings) {
  try { fs.writeFileSync(overlaySettingsFile, JSON.stringify(normalizeOverlaySettings(settings))) } catch {}
}

function getOverlayDims() {
  const settings = loadOverlaySettings()
  return OVERLAY_SIZES[settings.size] || OVERLAY_SIZES.medium
}

const OVERLAY_WIN_WIDTH = 500

function getOverlayPosition(corner) {
  const { screen } = require('electron')
  const display = screen.getPrimaryDisplay()
  const wa = display.workArea
  const h = getOverlayDims().height + 28
  const w = OVERLAY_WIN_WIDTH
  switch (corner) {
    case 'top-right': return { x: wa.x + wa.width - w, y: wa.y }
    case 'top-center': return { x: wa.x + Math.round((wa.width - w) / 2), y: wa.y }
    case 'bottom-left': return { x: wa.x, y: wa.y + wa.height - h }
    case 'bottom-center': return { x: wa.x + Math.round((wa.width - w) / 2), y: wa.y + wa.height - h }
    case 'bottom-right': return { x: wa.x + wa.width - w, y: wa.y + wa.height - h }
    default: return { x: wa.x, y: wa.y } // top-left
  }
}

function getAutoOverlayCorner(xPercent, yPercent) {
  const x = clampNumber(xPercent, 0, 100, 0)
  const y = clampNumber(yPercent, 0, 100, 0)
  return (y < 50 ? 'top' : 'bottom') + '-' + (x > 66 ? 'right' : x > 33 ? 'center' : 'left')
}

function setOverlayAlign(corner) {
  if (!overlayWindow) return
  overlayWindow.webContents.send('overlay-align', corner)
}

function createOverlay() {
  const settings = loadOverlaySettings()
  if (!settings.enabled) return
  if (overlayWindow) return
  const dims = getOverlayDims()
  const overlayHeight = dims.height + 28
  const corner = settings.corner || 'top-left'
  const alignCorner = corner === 'custom'
    ? getAutoOverlayCorner(settings.customX, settings.customY)
    : corner
  let pos
  if (settings.customX != null && settings.customY != null && settings.corner === 'custom') {
    const { screen } = require('electron')
    const wa = screen.getPrimaryDisplay().workArea
    pos = {
      x: wa.x + Math.round(settings.customX / 100 * (wa.width - OVERLAY_WIN_WIDTH)),
      y: wa.y + Math.round(settings.customY / 100 * (wa.height - overlayHeight)),
    }
  } else {
    pos = getOverlayPosition(corner)
  }
  overlayWindow = new BrowserWindow({
    width: OVERLAY_WIN_WIDTH,
    height: overlayHeight,
    minWidth: 100,
    maxWidth: 600,
    minHeight: overlayHeight,
    maxHeight: overlayHeight,
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
      preload: path.join(__dirname, 'overlay-preload.js'),
    },
  })
  overlayWindow.setOpacity(settings.opacity / 100)
  hardenWindowNavigation(overlayWindow)
  overlayWindow.setIgnoreMouseEvents(true)
  overlayWindow.setAlwaysOnTop(true, 'screen-saver')  // Highest z-level — stays above fullscreen games
  overlayWindow.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true })

  // Re-assert always-on-top periodically — Windows can steal it on focus change / alt-tab
  overlayWindow._keepAliveInterval = setInterval(() => {
    if (overlayWindow && !overlayWindow.isDestroyed()) {
      overlayWindow.setAlwaysOnTop(true, 'screen-saver')
      if (!overlayWindow.isVisible()) overlayWindow.showInactive()
    }
  }, 10000)

  function cleanupOverlay() {
    if (overlayWindow?._keepAliveInterval) {
      clearInterval(overlayWindow._keepAliveInterval)
      overlayWindow._keepAliveInterval = null
    }
  }
  overlayWindow.on('closed', () => {
    cleanupOverlay()
    overlayWindow = null
  })
  overlayWindow.webContents.on('destroyed', cleanupOverlay)

  const overlayHTML = `<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body { width: 100%; height: 100%; }
body { background: transparent; overflow: hidden; user-select: none; -webkit-app-region: no-drag;
       display: flex; flex-direction: column; justify-content: flex-end; }
#bar { background: rgba(5,5,8,0.88); border-bottom: 1px solid rgba(200,255,0,0.15);
       border-right: 1px solid rgba(200,255,0,0.08);
       padding: 0 10px; font: 700 11px 'JetBrains Mono', monospace; letter-spacing: 0.18em;
       color: rgba(200,255,0,0.5); display: inline-flex; align-items: center; gap: 0; height: 30px;
       position: relative; overflow: hidden; white-space: nowrap; width: fit-content; }
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
#wrap { position: relative; display: inline-flex; flex-direction: column; align-items: flex-start; }
#notif { background: rgba(5,5,8,0.92); border: 1px solid rgba(0,255,255,0.3);
         padding: 0 10px; font: 700 9px 'JetBrains Mono', monospace; letter-spacing: 0.2em;
         color: rgba(0,255,255,0.8); height: 24px; display: inline-flex; align-items: center;
         white-space: nowrap; width: fit-content; position: relative;
         transform: translateY(100%); opacity: 0; transition: transform 0.4s ease, opacity 0.3s ease;
         pointer-events: none; margin-bottom: 2px; }
#notif.show { transform: translateY(0); opacity: 1; }
#notif::after { content: ''; position: absolute; bottom: 0; left: 0; right: 0; height: 1px;
                background: linear-gradient(90deg, rgba(0,255,255,0.4), transparent 60%); }
</style></head><body>
<div id="wrap">
  <div id="notif"></div>
  <div id="bar">
    <span id="sym">&#x25C8;</span>
    <span id="main">RUNLOG.EXE</span>
    <span id="sep">&#x2500;&#x2500;</span>
    <span id="aux">INIT</span>
  </div>
</div>
<script>
var _notifTimer = null;
function showNotification(msg, duration) {
  var notif = document.getElementById('notif');
  notif.textContent = msg;
  notif.classList.add('show');
  if (_notifTimer) clearTimeout(_notifTimer);
  _notifTimer = setTimeout(function() {
    notif.classList.remove('show');
    _notifTimer = null;
  }, duration || 4000);
}
function updateOverlayState(s, d) {
  var bar = document.getElementById('bar');
  var sym = document.getElementById('sym');
  var main = document.getElementById('main');
  var aux = document.getElementById('aux');
  if (s === 'recording') {
    bar.className = 'rec';
    sym.textContent = '\u25A0';
    var parts = (d||'').split('|');
    main.textContent = 'REC ' + parts[0];
    aux.textContent = parts[1] ? parts[1] + ' — WGC' : 'WGC';
  } else {
    bar.className = '';
    sym.textContent = '\u25C8';
    if (d && d !== 'WATCHING') {
      main.textContent = 'DET: ' + d;
      aux.textContent = 'WGC';
    } else {
      main.textContent = 'RUNLOG.EXE';
      aux.textContent = 'SCAN.ACTIVE';
    }
  }
}
function setAlign(corner) {
  var isRight = corner && corner.includes('right');
  var isCenter = corner && corner.includes('center');
  var isTop = corner && corner.includes('top');
  var hAlign = isRight ? 'flex-end' : isCenter ? 'center' : 'flex-start';
  document.body.style.alignItems = hAlign;
  document.body.style.justifyContent = isTop ? 'flex-start' : 'flex-end';
  var w = document.getElementById('wrap');
  w.style.alignItems = hAlign;
  w.style.flexDirection = isTop ? 'column-reverse' : 'column';
}
function setBarSize(fontSize, height) {
  document.getElementById('bar').style.font = '700 ' + fontSize + 'px "JetBrains Mono", monospace';
  document.getElementById('bar').style.height = height + 'px';
}
if (window.overlayBridge) {
  window.overlayBridge.onState(function(s, d) { updateOverlayState(s, d); });
  window.overlayBridge.onNotification(function(msg, dur) { showNotification(msg, dur); });
  window.overlayBridge.onAlign(function(corner) { setAlign(corner); });
  window.overlayBridge.onResize(function(fontSize, height) { setBarSize(fontSize, height); });
}
</script></body></html>`

  overlayWindow.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(overlayHTML))
  overlayWindow.webContents.on('did-finish-load', () => {
    setOverlayAlign(alignCorner)
  })
}

function updateOverlay(state, detail) {
  if (!overlayWindow) return
  overlayWindow.webContents.send('overlay-state', state || '', (detail || '').toString())
}

function showNotification(title, body) {
  // Replaced by overlay — no more Windows popups
}

function checkProcessingActive() {
  return new Promise((resolve) => {
    const req = http.get(`http://127.0.0.1:${API_PORT}/api/capture/status`, (res) => {
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
      backgroundThrottling: true,
    },
  })
  hardenWindowNavigation(mainWindow)
  if (saved?.isMaximized) mainWindow.maximize()

  // Overlay is created lazily — only when Marathon is first detected
  // (see recording manager status callback below)

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

  // Auto-updater — uncomment when code signing + GitHub releases are configured
  // initAutoUpdater(mainWindow)

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
              p.textContent = '> ' + l.text;
              boot.appendChild(p);
              setTimeout(() => {
                p.textContent = '> ' + l.text + ' ';
                const ok = document.createElement('span');
                ok.className = 'ok';
                ok.textContent = '[OK]';
                p.appendChild(ok);
              }, l.delay + l.okDelay);
            });
            const standby = document.createElement('p');
            standby.className = 'boot-line active';
            standby.style.animationDelay = '3100ms';
            standby.textContent = '> STANDING BY';
            const cursor = document.createElement('span');
            cursor.className = 'blink';
            cursor.textContent = '_';
            standby.appendChild(cursor);
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

      // Update overlay for key events
      if (status === 'recording_started') {
        setRecordingPowerBlocker(true)
        updateOverlay('recording', '')
      } else if (status === 'recording_stopped') {
        setRecordingPowerBlocker(false)
        // Let App.tsx control overlay via last_detection state
      } else if (status === 'run_processed') {
        // Let App.tsx control overlay via last_detection state
      } else if (status === 'active') {
        createOverlay()
        updateOverlay('active', 'WATCHING')
      }
    }, API_PORT)
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
  setRecordingPowerBlocker(false)
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
  event.returnValue = isDev ? '' : `http://127.0.0.1:${API_PORT}`
})
ipcMain.on('overlay-update', (_event, state, detail) => {
  updateOverlay(state, detail)
})
ipcMain.on('overlay-notify', (_event, message, duration) => {
  if (!overlayWindow) return
  overlayWindow.webContents.send('overlay-notification', (message || '').toString(), clampNumber(duration, 1000, 15000, 4000))
})
ipcMain.on('overlay-toggle', (_event, enabled) => {
  const settings = loadOverlaySettings()
  settings.enabled = enabled === true
  saveOverlaySettings(settings)
  if (enabled) {
    createOverlay()
    updateOverlay('active', 'WATCHING')
  } else if (overlayWindow) {
    overlayWindow.close()
    overlayWindow = null
  }
})
ipcMain.on('overlay-preview', () => {
  if (overlayWindow) {
    overlayWindow.close()
    overlayWindow = null
  } else {
    createOverlay()
    updateOverlay('active', 'PREVIEW')
  }
})
ipcMain.on('overlay-set-corner', (_event, corner) => {
  if (!OVERLAY_CORNERS.has(corner)) return
  const settings = loadOverlaySettings()
  settings.corner = corner
  delete settings.customX
  delete settings.customY
  saveOverlaySettings(settings)
  if (overlayWindow) {
    const pos = getOverlayPosition(corner)
    const dims = getOverlayDims()
    overlayWindow.setBounds({ x: pos.x, y: pos.y, width: OVERLAY_WIN_WIDTH, height: dims.height + 28 })
    setOverlayAlign(corner)
  }
})
ipcMain.on('overlay-nudge', (_event, direction) => {
  if (!overlayWindow) return
  if (!['up', 'down', 'left', 'right'].includes(direction)) return
  const { screen } = require('electron')
  const display = screen.getPrimaryDisplay()
  const wa = display.workArea
  const bounds = overlayWindow.getBounds()
  const step = 10
  let { x, y } = bounds
  if (direction === 'up') y = Math.max(wa.y, y - step)
  if (direction === 'down') y = Math.min(wa.y + wa.height - bounds.height, y + step)
  if (direction === 'left') x = Math.max(wa.x, x - step)
  if (direction === 'right') x = Math.min(wa.x + wa.width - bounds.width, x + step)
  overlayWindow.setBounds({ x, y, width: bounds.width, height: bounds.height })
  // Auto-align based on position
  const xPct = clampNumber((x - wa.x) / (wa.width - bounds.width) * 100, 0, 100, 0)
  const yPct = clampNumber((y - wa.y) / (wa.height - bounds.height) * 100, 0, 100, 0)
  const autoCorner = getAutoOverlayCorner(xPct, yPct)
  setOverlayAlign(autoCorner)
  // Save custom position
  const settings = loadOverlaySettings()
  settings.customX = xPct
  settings.customY = yPct
  settings.corner = 'custom'
  saveOverlaySettings(settings)
})
ipcMain.handle('overlay-get-settings', () => loadOverlaySettings())

ipcMain.on('overlay-set-opacity', (_event, opacity) => {
  const safeOpacity = clampNumber(opacity, 40, 100, 88)
  const settings = loadOverlaySettings()
  settings.opacity = safeOpacity
  saveOverlaySettings(settings)
  if (overlayWindow) {
    overlayWindow.setOpacity(safeOpacity / 100)
  }
})

ipcMain.on('overlay-set-size', (_event, size) => {
  if (!hasOverlaySize(size)) return
  const settings = loadOverlaySettings()
  settings.size = size
  saveOverlaySettings(settings)
  if (overlayWindow) {
    const dims = OVERLAY_SIZES[size] || OVERLAY_SIZES.medium
    const bounds = overlayWindow.getBounds()
    const oh = dims.height + 28
    overlayWindow.setMinimumSize(100, oh)
    overlayWindow.setMaximumSize(600, oh)
    overlayWindow.setBounds({ x: bounds.x, y: bounds.y, width: OVERLAY_WIN_WIDTH, height: oh })
    overlayWindow.webContents.send('overlay-resize', dims.fontSize, dims.height)
  }
})

let _overlayPosTimeout = null
ipcMain.on('overlay-set-position', (_event, xPercent, yPercent) => {
  const safeXPercent = clampNumber(xPercent, 0, 100, 0)
  const safeYPercent = clampNumber(yPercent, 0, 100, 0)
  // Move overlay window if it exists
  if (overlayWindow) {
    const { screen } = require('electron')
    const display = screen.getPrimaryDisplay()
    const wa = display.workArea
    const dims = getOverlayDims()
    const w = OVERLAY_WIN_WIDTH
    const h = dims.height + 28
    const x = wa.x + Math.max(0, Math.min(wa.width - w, Math.round(safeXPercent / 100 * (wa.width - w))))
    const y = wa.y + Math.max(0, Math.min(wa.height - h, Math.round(safeYPercent / 100 * (wa.height - h))))
    overlayWindow.setBounds({ x, y, width: w, height: h })
    // Auto-align content based on position
    const autoCorner = getAutoOverlayCorner(safeXPercent, safeYPercent)
    setOverlayAlign(autoCorner)
  }
  // Always save position — even if overlay isn't active
  if (_overlayPosTimeout) clearTimeout(_overlayPosTimeout)
  _overlayPosTimeout = setTimeout(() => {
    const settings = loadOverlaySettings()
    settings.customX = safeXPercent
    settings.customY = safeYPercent
    settings.corner = 'custom'
    saveOverlaySettings(settings)
  }, 500)
})

ipcMain.on('open-url', (_event, url) => {
  if (isSafeExternalUrl(url)) {
    shell.openExternal(url).catch(() => {})
  }
})
