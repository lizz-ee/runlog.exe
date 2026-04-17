import { useEffect, useRef } from 'react'
import axios from 'axios'
import { useStore } from './lib/store'
import { formatTime } from './lib/utils'
import { getRecentRuns, getOverviewStats, getRunners, getLoadouts, getCaptureStatus, apiBase } from './lib/api'
import { onScreenshotParsed } from './lib/electron'
import type { CaptureStatus } from './lib/types'
import type { OverlaySettings } from './lib/electron'
import Sidebar from './components/Sidebar'
import Dashboard from './components/Dashboard'
import RunHistory from './components/RunHistory'
import Maps from './components/Maps'
import Live from './components/Live'
import Shells from './components/Shells'
import Squad from './components/Squad'
import Settings from './components/Settings'
import Uplink from './components/Uplink'
import Toasts from './components/Toasts'
import TitleBar from './components/TitleBar'
import ErrorBoundary from './components/ErrorBoundary'

const MAP_VIEW_TO_NAME: Record<string, string> = {
  'map-perimeter': 'Perimeter',
  'map-dire-marsh': 'Dire Marsh',
  'map-outpost': 'Outpost',
  'map-cryo-archive': 'Cryo Archive',
}

function getSeenRunId(): number | null {
  const v = sessionStorage.getItem('runlog_lastSeenRunId')
  return v ? parseInt(v, 10) : null
}
function setSeenRunId(id: number) {
  sessionStorage.setItem('runlog_lastSeenRunId', String(id))
}
function wasResumeToastShown(): boolean {
  return sessionStorage.getItem('runlog_resumeToastShown') === '1'
}
function markResumeToastShown() {
  sessionStorage.setItem('runlog_resumeToastShown', '1')
}

export default function App() {
  const { view, setRuns, setStats, setRunners, setLoadouts, addToast, setPendingCapture, captureStatus, setCaptureStatus, setCaptureError, refreshData, refreshUnviewed } = useStore()

  useEffect(() => {
    async function load() {
      try {
        const [runs, stats, runners, loadouts] = await Promise.all([
          getRecentRuns(20),
          getOverviewStats(),
          getRunners(),
          getLoadouts(),
        ])
        setRuns(runs)
        setStats(stats)
        setRunners(runners)
        setLoadouts(loadouts)
      } catch (e) {
        console.error('Failed to load data:', e)
      }
    }
    load()
  }, [])

  useEffect(() => {
    onScreenshotParsed((event) => {
      setPendingCapture(event)
      if (event.type === 'run') {
        const d = event.data as Record<string, number | string | boolean | null>
        const status = d.survived ? 'EXTRACTED' : 'KIA'
        const kills = (Number(d.combatant_eliminations) || 0) + (Number(d.runner_eliminations) || 0)
        addToast({
          type: d.survived ? 'success' : 'error',
          title: `RUN CAPTURED — ${status}`,
          body: `${kills} KILLS | $${d.loot_value_total || 0} LOOT | ${d.map_name || 'UNKNOWN'}`,
        })
      } else if (event.type === 'spawn') {
        const d = event.data as Record<string, string | null>
        addToast({
          type: 'info',
          title: 'SPAWN LOGGED',
          body: `${d.map_name || 'UNKNOWN'} — ${d.spawn_location || 'UNKNOWN'}`,
        })
      }
    })
  }, [])

  // SSE for real-time capture status, with polling fallback
  useEffect(() => {
    let eventSource: EventSource | null = null
    let fallbackInterval: ReturnType<typeof setInterval> | null = null

    function handleStatusUpdate(status: CaptureStatus) {
      setCaptureStatus(status)
      setCaptureError(null)
    }

    function startPolling() {
      if (fallbackInterval) return
      fallbackInterval = setInterval(poll, 10000) // Slower fallback when SSE unavailable
    }

    async function poll() {
      try {
        const s = await getCaptureStatus()
        handleStatusUpdate(s)
        if (!s.active) {
          try { await axios.post(`${apiBase}/api/capture/start`, {}) } catch {}
        }
      } catch {
        setCaptureError('Capture engine not running')
      }
    }

    // Try SSE first
    try {
      eventSource = new EventSource(`${apiBase}/api/sse/events`)
      eventSource.addEventListener('capture_status', (e) => {
        try {
          const status = JSON.parse((e as MessageEvent).data)
          handleStatusUpdate(status)
        } catch (err) {
          console.error('[SSE] Failed to parse capture_status:', err)
        }
      })
      eventSource.onerror = () => {
        // SSE failed or disconnected — close and fall back to polling
        eventSource?.close()
        eventSource = null
        startPolling()
      }
    } catch {
      startPolling()
    }

    // Initial poll to get immediate status (SSE only pushes on changes)
    poll()

    const runlog = window.runlog
    if (runlog?.onRecordingStatus) {
      runlog.onRecordingStatus(() => poll())
    }

    return () => {
      eventSource?.close()
      if (fallbackInterval) clearInterval(fallbackInterval)
    }
  }, [])

  // Push overlay updates when recording state changes
  useEffect(() => {
    const runlog = window.runlog
    if (!runlog?.updateOverlay || !captureStatus) return
    if (captureStatus.recording) {
      const det = captureStatus.last_detection
      let recDetail = formatTime(captureStatus.recording_seconds)
      if (det === 'endgame') recDetail += '|RUN.COMPLETE'
      if (det === 'exfiltrated') recDetail += '|EXFILTRATED'
      if (det === 'eliminated') recDetail += '|ELIMINATED'
      runlog.updateOverlay('recording', recDetail)
    } else if (captureStatus.active && captureStatus.last_detection) {
      const det = captureStatus.last_detection === 'run' ? 'RUN.EXE' : captureStatus.last_detection.toUpperCase().replace('_', '.')
      runlog.updateOverlay('active', det)
    } else if (captureStatus.active) {
      runlog.updateOverlay('active', 'WATCHING')
    }
  }, [captureStatus?.recording, captureStatus?.recording_seconds, captureStatus?.last_detection])

  // Auto-refresh dashboard data when a new run is processed
  useEffect(() => {
    const newRunId = captureStatus?.last_result?.run_id
    if (newRunId && newRunId !== getSeenRunId()) {
      setSeenRunId(newRunId)
      refreshData()
      addToast({
        type: 'success',
        title: 'RUN PROCESSED',
        body: 'Run analyzed and saved',
      })
    }
  }, [captureStatus?.last_result?.run_id])

  // Refresh dashboard when Phase 1 stats are ready
  useEffect(() => {
    const items = captureStatus?.processing_items || []
    const phase1Item = items.find(i => i.status === 'phase1_done' && i.run_id)
    if (phase1Item?.run_id) {
      refreshData()
      const runlog = window.runlog
      if (runlog?.notifyOverlay) runlog.notifyOverlay('NEW STATS AVAILABLE', 4000)
    }
  }, [captureStatus?.processing_items?.find(i => i.status === 'phase1_done')?.run_id])

  // Notify when a run finishes processing (item vanishes from queue)
  const prevItemFiles = useRef<Set<string>>(new Set())
  useEffect(() => {
    const currentItems = captureStatus?.processing_items || []
    const currentFiles = new Set(currentItems.map(i => i.file))
    const prevFiles = prevItemFiles.current

    // Check if any items from previous set are gone (completed/removed)
    if (prevFiles.size > 0) {
      const removed = [...prevFiles].filter(f => !currentFiles.has(f))
      if (removed.length > 0) {
        refreshData()
        refreshUnviewed()
        const runlog = window.runlog
        if (runlog?.notifyOverlay) runlog.notifyOverlay('RUN PROCESSED', 4000)

        // Close app when queue empty (if enabled)
        if (currentFiles.size === 0) {
          if (runlog?.getOverlaySettings) {
            runlog.getOverlaySettings().then((s: OverlaySettings) => {
              if (s?.closeWhenDone) {
                setTimeout(() => { if (runlog?.windowClose) runlog.windowClose() }, 3000)
              }
            })
          }
        }
      }
    }
    prevItemFiles.current = currentFiles
  }, [captureStatus?.processing_items])

  // Show toast for auto-resumed recordings
  useEffect(() => {
    if (captureStatus?.resumed_count && captureStatus.resumed_count > 0 && !wasResumeToastShown()) {
      markResumeToastShown()
      addToast({
        type: 'info',
        title: 'RESUMING PROCESSING',
        body: `Found ${captureStatus.resumed_count} unprocessed recording${captureStatus.resumed_count > 1 ? 's' : ''} from last session`,
      })
    }
  }, [captureStatus?.resumed_count])

  const mapName = MAP_VIEW_TO_NAME[view]

  return (
    <div className="flex flex-col h-screen bg-m-bg splash-bg">
      {/* Splash background elements */}
      {/* Corner deco — centered in the main area's bottom-right padding */}
      <div className="corner-bracket corner-br" />
      <div className="fixed bottom-[1rem] right-[3.5rem] text-[8px] tracking-widest font-mono text-m-text-muted/15 select-none pointer-events-none z-[2]">
        0x4D415241 // 0x54484F4E
      </div>
      <TitleBar />
      <div className="flex flex-1 overflow-hidden relative z-10">
      <Sidebar />
      <main className="flex-1 overflow-y-auto px-8 pt-5 pb-8">
        <ErrorBoundary>
        {view === 'dashboard' && <Dashboard />}
        {view === 'history' && <RunHistory />}
        {view === 'shells' && <Shells />}
        {view === 'squad' && <Squad />}
        {mapName && <Maps selectedMap={mapName} />}
        {view === 'live' && <Live />}
        {view === 'uplink' && <Uplink />}
        {view === 'settings' && <Settings />}
        </ErrorBoundary>
      </main>
      <Toasts />
      </div>
    </div>
  )
}
