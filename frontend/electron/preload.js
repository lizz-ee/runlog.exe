const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('runlog', {
  // Listen for auto-captured screenshots from hotkeys
  onScreenshotParsed: (callback) => {
    ipcRenderer.on('screenshot-parsed', (_event, data) => callback(data))
  },

  // Listen for auto-capture events
  onAutoCaptureEvent: (callback) => {
    ipcRenderer.on('auto-capture-event', (_event, data) => callback(data))
  },

  // Listen for recording status changes (from recording-manager)
  onRecordingStatus: (callback) => {
    ipcRenderer.on('recording-status', (_event, data) => callback(data))
  },

  // Get API base URL (empty in dev for Vite proxy, http://127.0.0.1:8000 in production)
  getApiBaseUrl: () => ipcRenderer.sendSync('get-api-base-url'),

  // Window controls
  windowMinimize: () => ipcRenderer.send('window-minimize'),
  windowMaximize: () => ipcRenderer.send('window-maximize'),
  windowClose: () => ipcRenderer.send('window-close'),

  // Overlay
  updateOverlay: (state, detail) => ipcRenderer.send('overlay-update', state, detail),
  notifyOverlay: (message, duration) => ipcRenderer.send('overlay-notify', message, duration),
  toggleOverlay: (enabled) => ipcRenderer.send('overlay-toggle', enabled),
  setOverlayCorner: (corner) => ipcRenderer.send('overlay-set-corner', corner),
  nudgeOverlay: (direction) => ipcRenderer.send('overlay-nudge', direction),
  getOverlaySettings: () => ipcRenderer.invoke('overlay-get-settings'),
  setOverlayOpacity: (opacity) => ipcRenderer.send('overlay-set-opacity', opacity),
  setOverlaySize: (size) => ipcRenderer.send('overlay-set-size', size),
  setOverlayPosition: (xPct, yPct) => ipcRenderer.send('overlay-set-position', xPct, yPct),

  // Open a file in system default application
  openFile: (filePath) => ipcRenderer.send('open-file', filePath),
})
