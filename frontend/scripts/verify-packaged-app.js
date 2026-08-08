const fs = require('fs')
const path = require('path')
const asar = require('@electron/asar')

const releaseDir = path.resolve(__dirname, '..', '..', 'release', 'win-unpacked')
const executablePath = path.join(releaseDir, 'runlog.exe')
const asarPath = path.join(releaseDir, 'resources', 'app.asar')
const recorderPath = path.join(releaseDir, 'resources', 'backend', 'runlog-recorder.exe')

function fail(message) {
  console.error(`[verify-package] ${message}`)
  process.exit(1)
}

for (const requiredFile of [executablePath, asarPath, recorderPath]) {
  if (!fs.existsSync(requiredFile)) {
    fail(`Missing packaged file: ${requiredFile}`)
  }
}

const entries = new Set(
  asar.listPackage(asarPath).map((entry) => entry.replaceAll('\\', '/').replace(/^\/+/, '')),
)

for (const requiredEntry of ['electron/main.js', 'electron/preload.js', 'dist/index.html']) {
  if (!entries.has(requiredEntry)) {
    fail(`app.asar is missing ${requiredEntry}`)
  }
}

const indexHtml = asar.extractFile(asarPath, 'dist/index.html').toString('utf8')
const assetRefs = [...indexHtml.matchAll(/(?:src|href)="\.\/([^"]+)"/g)].map((match) => match[1])

if (assetRefs.length === 0) {
  fail('packaged dist/index.html contains no renderer assets')
}

for (const assetRef of assetRefs) {
  if (!entries.has(`dist/${assetRef}`)) {
    fail(`app.asar is missing renderer asset dist/${assetRef}`)
  }
}

console.log(`[verify-package] OK: executable, recorder, renderer, and ${assetRefs.length} entry asset(s)`)
