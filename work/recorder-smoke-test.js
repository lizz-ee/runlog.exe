const { spawn, spawnSync } = require('child_process')
const fs = require('fs')
const path = require('path')

const repo = path.resolve(__dirname, '..')
const binary = path.join(repo, 'backend', 'recorder', 'target', 'release', 'runlog-recorder.exe')
const durationSeconds = Number(process.argv[2] || 20)
const targetHeight = Number(process.argv[3] || 1440)
const encoder = String(process.argv[4] || 'hevc').toLowerCase()
const outputFps = Number(process.argv[5] || 60)
const stamp = new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 14)
const outputDir = 'D:\\runlog\\diagnostics'
const output = path.join(
  outputDir,
  `pipeline_${targetHeight || 'native'}p_${encoder}_${outputFps}fps_${stamp}.mp4`,
)
fs.mkdirSync(outputDir, { recursive: true })

const child = spawn(binary, [], {
  cwd: repo,
  stdio: ['pipe', 'pipe', 'pipe'],
  env: {
    ...process.env,
    RUNLOG_CAPTURE_FPS: String(outputFps),
    RUNLOG_OCR_INTERVAL: String(outputFps * 2),
  },
})

let stdoutBuffer = ''
let stderrBuffer = ''
let started = false
let stopping = false
let finished = false
let lastProgress = null
const gpuSamples = []

function command(payload) {
  child.stdin.write(`${JSON.stringify(payload)}\n`)
}

function consumeStdout(line) {
  let event
  try { event = JSON.parse(line) } catch { return }
  if (event.event === 'ready' && !started) {
    started = true
    console.log(`READY ${event.window} ${event.width}x${event.height}`)
    command({
      cmd: 'start',
      path: output,
      bitrate: 30000000,
      encoder,
      fps: outputFps,
      ...(targetHeight ? { target_height: targetHeight } : {}),
    })
  } else if (event.event === 'recording_started') {
    console.log(`STARTED ${event.path}`)
    setTimeout(() => {
      stopping = true
      console.log('STOP_REQUESTED')
      command({ cmd: 'stop' })
    }, durationSeconds * 1000)
  } else if (event.event === 'recording_progress') {
    lastProgress = event
    console.log(
      `PROGRESS t=${event.duration.toFixed(1)} capture=${event.capture_fps.toFixed(1)} `
      + `submit=${event.submitted_fps.toFixed(1)} dropped=${event.dropped_frames}`,
    )
  } else if (event.event === 'recording_stopped') {
    finished = true
    console.log(`STOPPED ${JSON.stringify(event)}`)
    command({ cmd: 'quit' })
  } else if (event.event === 'recording_failed' || event.event === 'error') {
    console.log(`ERROR ${JSON.stringify(event)}`)
  }
}

child.stdout.on('data', data => {
  stdoutBuffer += data.toString('utf8')
  const lines = stdoutBuffer.split(/\r?\n/)
  stdoutBuffer = lines.pop()
  for (const line of lines) consumeStdout(line)
})

child.stderr.on('data', data => {
  stderrBuffer += data.toString('utf8')
  const lines = stderrBuffer.split(/\r?\n/)
  stderrBuffer = lines.pop()
  for (const line of lines) {
    if (/Encoder|backpressure|FAILED|Capture stopped|Frame \d+ encoded/.test(line)) {
      console.log(`NATIVE ${line}`)
    }
  }
})

const gpuTimer = setInterval(() => {
  const result = spawnSync('nvidia-smi', [
    '--query-gpu=utilization.gpu,utilization.encoder,memory.used,power.draw',
    '--format=csv,noheader,nounits',
  ], { encoding: 'utf8', windowsHide: true })
  const values = String(result.stdout || '').trim().split(',').map(value => Number(value.trim()))
  if (values.length === 4 && values.every(Number.isFinite)) gpuSamples.push(values)
}, 1000)

const timeout = setTimeout(() => {
  console.log(`TIMEOUT started=${started} stopping=${stopping} finished=${finished}`)
  command({ cmd: 'quit' })
  setTimeout(() => child.kill(), 5000)
}, (durationSeconds + 50) * 1000)

child.on('exit', code => {
  clearInterval(gpuTimer)
  clearTimeout(timeout)
  const averages = gpuSamples.length
    ? gpuSamples[0].map((_, column) =>
        gpuSamples.reduce((sum, row) => sum + row[column], 0) / gpuSamples.length)
    : []
  console.log(`EXIT code=${code} output=${output}`)
  if (averages.length) {
    console.log(
      `GPU_AVG gpu=${averages[0].toFixed(1)}% enc=${averages[1].toFixed(1)}% `
      + `vram=${averages[2].toFixed(0)}MiB power=${averages[3].toFixed(1)}W samples=${gpuSamples.length}`,
    )
  }
  if (lastProgress) console.log(`LAST_PROGRESS ${JSON.stringify(lastProgress)}`)
  process.exitCode = finished && code === 0 ? 0 : 1
})
