/**
 * Watches the Steam screenshot folder for new Marathon screenshots.
 *
 * Steam screenshot default paths:
 *   Windows: C:\Program Files (x86)\Steam\userdata\<user_id>\760\remote\<app_id>\screenshots
 *
 * Marathon's Steam App ID will need to be configured. The watcher also
 * supports a custom folder path.
 */

const fs = require('fs')
const path = require('path')
const os = require('os')

// Default Steam screenshot paths to search
function getSteamScreenshotPaths() {
  const steamPaths = [
    'C:\\Program Files (x86)\\Steam\\userdata',
    'C:\\Program Files\\Steam\\userdata',
    path.join(os.homedir(), 'Steam', 'userdata'),
  ]

  const found = []
  for (const base of steamPaths) {
    if (fs.existsSync(base)) {
      // List user IDs
      try {
        const userDirs = fs.readdirSync(base).filter(d => /^\d+$/.test(d))
        for (const uid of userDirs) {
          // 760 = Steam screenshots app
          const screenshotRoot = path.join(base, uid, '760', 'remote')
          if (fs.existsSync(screenshotRoot)) {
            // List all game app IDs
            try {
              const appDirs = fs.readdirSync(screenshotRoot).filter(d => /^\d+$/.test(d))
              for (const appId of appDirs) {
                const ssDir = path.join(screenshotRoot, appId, 'screenshots')
                if (fs.existsSync(ssDir)) {
                  found.push({ path: ssDir, appId, userId: uid })
                }
              }
            } catch {}
          }
        }
      } catch {}
    }
  }
  return found
}

class SteamScreenshotWatcher {
  constructor(onNewScreenshot) {
    this.onNewScreenshot = onNewScreenshot
    this.watchers = []
    this.seenFiles = new Set()
    this.watchPaths = []
  }

  start(customPath = null) {
    this.stop()

    if (customPath && fs.existsSync(customPath)) {
      this.watchPaths = [{ path: customPath, appId: 'custom', userId: 'custom' }]
    } else {
      this.watchPaths = getSteamScreenshotPaths()
    }

    if (this.watchPaths.length === 0) {
      console.log('Steam watcher: No screenshot folders found')
      return false
    }

    for (const wp of this.watchPaths) {
      console.log(`Steam watcher: Watching ${wp.path} (app: ${wp.appId})`)

      // Seed seen files so we don't re-process existing screenshots
      try {
        const existing = fs.readdirSync(wp.path)
        existing.forEach(f => this.seenFiles.add(path.join(wp.path, f)))
      } catch {}

      try {
        const watcher = fs.watch(wp.path, (eventType, filename) => {
          if (eventType === 'rename' && filename) {
            const fullPath = path.join(wp.path, filename)
            const ext = path.extname(filename).toLowerCase()

            if (['.png', '.jpg', '.jpeg', '.webp'].includes(ext) && !this.seenFiles.has(fullPath)) {
              this.seenFiles.add(fullPath)

              // Wait a moment for the file to finish writing
              setTimeout(() => {
                if (fs.existsSync(fullPath)) {
                  console.log(`Steam watcher: New screenshot detected: ${filename}`)
                  this.onNewScreenshot(fullPath, wp.appId)
                }
              }, 1000)
            }
          }
        })
        this.watchers.push(watcher)
      } catch (err) {
        console.error(`Steam watcher: Failed to watch ${wp.path}:`, err)
      }
    }

    return this.watchers.length > 0
  }

  stop() {
    this.watchers.forEach(w => w.close())
    this.watchers = []
    this.watchPaths = []
  }

  getPaths() {
    return this.watchPaths
  }
}

module.exports = { SteamScreenshotWatcher, getSteamScreenshotPaths }
