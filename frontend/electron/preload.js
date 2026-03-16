const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('runlog', {
  // Listen for auto-captured screenshots from hotkeys
  onScreenshotParsed: (callback) => {
    ipcRenderer.on('screenshot-parsed', (_event, data) => callback(data))
  },

  // Manually trigger captures from the UI
  captureRun: () => ipcRenderer.invoke('capture-run'),
  captureSpawn: () => ipcRenderer.invoke('capture-spawn'),
})
