const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('overlayBridge', {
  onState: (callback) => {
    ipcRenderer.on('overlay-state', (_event, state, detail) => callback(state, detail))
  },
  onNotification: (callback) => {
    ipcRenderer.on('overlay-notification', (_event, message, duration) => callback(message, duration))
  },
  onAlign: (callback) => {
    ipcRenderer.on('overlay-align', (_event, corner) => callback(corner))
  },
  onResize: (callback) => {
    ipcRenderer.on('overlay-resize', (_event, fontSize, height) => callback(fontSize, height))
  },
})
