const { contextBridge, ipcRenderer } = require('electron')

function subscribe(channel, callback) {
  const listener = (_event, ...args) => callback(...args)
  ipcRenderer.on(channel, listener)
  return () => ipcRenderer.removeListener(channel, listener)
}

contextBridge.exposeInMainWorld('overlayBridge', {
  onState: (callback) => {
    return subscribe('overlay-state', callback)
  },
  onNotification: (callback) => {
    return subscribe('overlay-notification', callback)
  },
  onAlign: (callback) => {
    return subscribe('overlay-align', callback)
  },
  onResize: (callback) => {
    return subscribe('overlay-resize', callback)
  },
})
