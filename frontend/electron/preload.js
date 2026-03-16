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

  // Manually trigger captures from the UI
  captureRun: () => ipcRenderer.invoke('capture-run'),
  captureSpawn: () => ipcRenderer.invoke('capture-spawn'),

  // Get API base URL (empty in dev for Vite proxy, http://localhost:8000 in production)
  getApiBaseUrl: () => ipcRenderer.sendSync('get-api-base-url'),
})
