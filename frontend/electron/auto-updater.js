/**
 * Auto-updater module — checks for updates on startup and installs them.
 *
 * Prerequisites:
 * - Code signing certificate configured in electron-builder
 * - GitHub releases published with electron-builder
 * - "publish" config set in package.json build section
 *
 * To enable: call initAutoUpdater(mainWindow) from main.js after app.whenReady()
 */

const { autoUpdater } = require('electron-updater')

let _mainWindow = null

function initAutoUpdater(mainWindow) {
  // Skip in dev mode
  const { app } = require('electron')
  if (!app.isPackaged) return

  _mainWindow = mainWindow
  autoUpdater.logger = console
  autoUpdater.autoDownload = true
  autoUpdater.autoInstallOnAppQuit = true

  autoUpdater.on('checking-for-update', () => {
    console.log('[updater] Checking for updates...')
  })

  autoUpdater.on('update-available', (info) => {
    console.log(`[updater] Update available: ${info.version}`)
    sendToRenderer('update-status', { status: 'available', version: info.version })
  })

  autoUpdater.on('update-not-available', () => {
    console.log('[updater] App is up to date')
  })

  autoUpdater.on('download-progress', (progress) => {
    console.log(`[updater] Download: ${Math.round(progress.percent)}%`)
  })

  autoUpdater.on('update-downloaded', (info) => {
    console.log(`[updater] Update downloaded: ${info.version} — will install on quit`)
    sendToRenderer('update-status', { status: 'downloaded', version: info.version })
  })

  autoUpdater.on('error', (err) => {
    console.error('[updater] Error:', err.message)
  })

  // Check for updates after 10 second delay (let app finish loading)
  setTimeout(() => {
    autoUpdater.checkForUpdatesAndNotify().catch((err) => {
      console.error('[updater] Check failed:', err.message)
    })
  }, 10000)
}

function sendToRenderer(channel, data) {
  if (_mainWindow && !_mainWindow.isDestroyed()) {
    _mainWindow.webContents.send(channel, data)
  }
}

module.exports = { initAutoUpdater }
