import { lazy, Suspense, useEffect, useRef } from 'react'
import { useStore } from './lib/store'
import { getRecentRuns, getOverviewStats, getRunners, getLoadouts, getCaptureStatus, apiBase } from './lib/api'
import { onScreenshotParsed } from './lib/electron'
import type { CaptureStatus } from './lib/types'
import Sidebar from './components/Sidebar'
import Toasts from './components/Toasts'
import TitleBar from './components/TitleBar'
import ErrorBoundary from './components/ErrorBoundary'

const Dashboard = lazy(() => import('./components/Dashboard'))
const RunHistory = lazy(() => import('./components/RunHistory'))
const Maps = lazy(() => import('./components/Maps'))
const Live = lazy(() => import('./components/Live'))
const Shells = lazy(() => import('./components/Shells'))
const Squad = lazy(() => import('./components/Squad'))
const Settings = lazy(() => import('./components/Settings'))
const Uplink = lazy(() => import('./components/Uplink'))

const MAP_VIEW_TO_SELECTION: Record<string, { name: string; variant?: 'Day' | 'Night' }> = {
  'map-perimeter': { name: 'Perimeter' },
  'map-dire-marsh': { name: 'Dire Marsh' },
  'map-dire-marsh-day': { name: 'Dire Marsh', variant: 'Day' },
  'map-dire-marsh-night': { name: 'Dire Marsh', variant: 'Night' },
  'map-outpost': { name: 'Outpost' },
  'map-cryo-archive': { name: 'Cryo Archive' },
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
          body: `${kills} KILLS | $${d.loot_value_total || 0} LOOT | ${d.map_name || 'UNKNOWN'}${d.map_variant ? ` // ${d.map_variant}` : ''}`,
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
    let reconcileInterval: ReturnType<typeof setInterval> | null = null

    function handleStatusUpdate(status: CaptureStatus) {
      setCaptureStatus(status)
      setCaptureError(null)
    }

    function startPolling() {
      if (fallbackInterval) return
      fallbackInterval = setInterval(poll, 20000) // Slower fallback when SSE unavailable
    }

    async function poll() {
      try {
        const s = await getCaptureStatus()
        handleStatusUpdate(s)
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
        if (reconcileInterval) {
          clearInterval(reconcileInterval)
          reconcileInterval = null
        }
        startPolling()
      }
    } catch {
      startPolling()
    }

    // Initial poll to get immediate status (SSE only pushes on changes)
    poll()
    // Reconcile occasionally even with SSE connected. Frame readiness can
    // change between the initial poll and the first event, and DETECT.EXE must
    // never remain stuck on that stale INITIALIZING snapshot.
    if (eventSource) reconcileInterval = setInterval(poll, 5000)

    return () => {
      eventSource?.close()
      if (fallbackInterval) clearInterval(fallbackInterval)
      if (reconcileInterval) clearInterval(reconcileInterval)
    }
  }, [])

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

  const mapSelection = MAP_VIEW_TO_SELECTION[view]

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
        <Suspense fallback={<div className="label-tag text-m-text-muted">LOADING...</div>}>
          {view === 'dashboard' && <Dashboard />}
          {view === 'history' && <RunHistory />}
          {view === 'shells' && <Shells />}
          {view === 'squad' && <Squad />}
          {mapSelection && <Maps selectedMap={mapSelection.name} variant={mapSelection.variant} />}
          {view === 'live' && <Live />}
          {view === 'uplink' && <Uplink />}
          {view === 'settings' && <Settings />}
        </Suspense>
        </ErrorBoundary>
      </main>
      <Toasts />
      </div>
    </div>
  )
}
