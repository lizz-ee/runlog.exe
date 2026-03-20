import { useEffect } from 'react'
import axios from 'axios'
import { useStore } from './lib/store'
import { getRecentRuns, getOverviewStats, getRunners, getLoadouts, getCaptureStatus, apiBase } from './lib/api'
import { onScreenshotParsed } from './lib/electron'
import Sidebar from './components/Sidebar'
import Dashboard from './components/Dashboard'
import RunHistory from './components/RunHistory'
import Maps from './components/Maps'
import Live from './components/Live'
import RunReports from './components/RunReports'
import Shells from './components/Shells'
import Squad from './components/Squad'
import Settings from './components/Settings'
import Toasts from './components/Toasts'
import TitleBar from './components/TitleBar'

const MAP_VIEW_TO_NAME: Record<string, string> = {
  'map-perimeter': 'Perimeter',
  'map-dire-marsh': 'Dire Marsh',
  'map-outpost': 'Outpost',
  'map-cryo-archive': 'Cryo Archive',
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
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
  const { view, setRuns, setStats, setRunners, setLoadouts, addToast, setPendingCapture, captureStatus, setCaptureStatus, setCaptureError, refreshData } = useStore()

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
        const d = event.data
        const status = d.survived ? 'EXTRACTED' : 'KIA'
        const kills = (d.combatant_eliminations || 0) + (d.runner_eliminations || 0)
        addToast({
          type: d.survived ? 'success' : 'error',
          title: `RUN CAPTURED — ${status}`,
          body: `${kills} KILLS | $${d.loot_value_total || 0} LOOT | ${d.map_name || 'UNKNOWN'}`,
        })
      } else if (event.type === 'spawn') {
        const d = event.data
        addToast({
          type: 'info',
          title: 'SPAWN LOGGED',
          body: `${d.map_name || 'UNKNOWN'} — ${d.spawn_location || 'UNKNOWN'}`,
        })
      }
    })
  }, [])

  // Global capture status polling — always runs regardless of active page
  useEffect(() => {
    async function poll() {
      try {
        const s = await getCaptureStatus()
        setCaptureStatus(s)
        setCaptureError(null)

        // Auto-start the capture engine if it's not active
        if (!s.active) {
          try {
            await axios.post(`${apiBase}/api/capture/start`, {})
          } catch {}
        }
      } catch {
        setCaptureError('Capture engine not running')
      }
    }

    poll()
    const interval = setInterval(poll, 2000)

    const runlog = (window as any).runlog
    if (runlog?.onRecordingStatus) {
      runlog.onRecordingStatus(() => poll())
    }

    return () => clearInterval(interval)
  }, [])

  // Push overlay updates when recording state changes
  useEffect(() => {
    const runlog = (window as any).runlog
    if (!runlog?.updateOverlay || !captureStatus) return
    if (captureStatus.recording) {
      const det = captureStatus.last_detection
      let recDetail = formatTime(captureStatus.recording_seconds)
      if (det === 'endgame') recDetail += '|RUN.COMPLETE'
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

  // Refresh dashboard when Phase 1 stats are ready (before Phase 2 finishes)
  useEffect(() => {
    const items = captureStatus?.processing_items || []
    const phase1Item = items.find(i => i.status === 'phase1_done' && i.run_id)
    if (phase1Item?.run_id) {
      refreshData()
    }
  }, [captureStatus?.processing_items?.find(i => i.status === 'phase1_done')?.run_id])

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
        {view === 'dashboard' && <Dashboard />}
        {view === 'history' && <RunHistory />}
        {view === 'shells' && <Shells />}
        {view === 'squad' && <Squad />}
        {mapName && <Maps selectedMap={mapName} />}
        {view === 'live' && <Live />}
        {view === 'highlights' && <RunReports />}
        {view === 'settings' && <Settings />}
      </main>
      <Toasts />
      </div>
    </div>
  )
}
