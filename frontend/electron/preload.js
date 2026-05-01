const { contextBridge, ipcRenderer } = require('electron')

function subscribe(channel, callback) {
  const listener = (_event, data) => callback(data)
  ipcRenderer.on(channel, listener)
  return () => ipcRenderer.removeListener(channel, listener)
}

contextBridge.exposeInMainWorld('runlog', {
  // Listen for auto-captured screenshots from hotkeys
  onScreenshotParsed: (callback) => {
    return subscribe('screenshot-parsed', callback)
  },

  // Listen for auto-capture events
  onAutoCaptureEvent: (callback) => {
    return subscribe('auto-capture-event', callback)
  },

  // Listen for recording status changes (from recording-manager)
  onRecordingStatus: (callback) => {
    return subscribe('recording-status', callback)
  },

  // Get API base URL (empty in dev for Vite proxy, configured local backend in production)
  // sendSync is acceptable here — called once at startup, value is needed synchronously
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
  previewOverlay: () => ipcRenderer.send('overlay-preview'),

  // Open a URL in the default browser
  openUrl: (url) => ipcRenderer.send('open-url', url),
})
