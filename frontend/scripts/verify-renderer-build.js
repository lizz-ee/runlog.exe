const fs = require('fs')
const path = require('path')

const distDir = path.resolve(__dirname, '..', 'dist')
const indexPath = path.join(distDir, 'index.html')

function fail(message) {
  console.error(`[verify-renderer] ${message}`)
  process.exit(1)
}

if (!fs.existsSync(indexPath)) {
  fail(`Missing renderer entry point: ${indexPath}`)
}

const html = fs.readFileSync(indexPath, 'utf8')
const assetRefs = [...html.matchAll(/(?:src|href)="\.\/([^"]+)"/g)].map((match) => match[1])

if (assetRefs.length === 0) {
  fail('index.html contains no relative renderer assets')
}

for (const assetRef of assetRefs) {
  const assetPath = path.join(distDir, ...assetRef.split('/'))
  if (!fs.existsSync(assetPath)) {
    fail(`index.html references a missing asset: ${assetRef}`)
  }
}

console.log(`[verify-renderer] OK: index.html + ${assetRefs.length} entry asset(s)`)
