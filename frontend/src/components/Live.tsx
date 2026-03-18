import { useEffect, useState } from 'react'
import axios from 'axios'
import { getCaptureStatus, getFrameUrl, getThumbnailUrl, apiBase } from '../lib/api'
import { useStore } from '../lib/store'
import type { CaptureStatus } from '../lib/types'

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

function formatTimestamp(isoStr: string | null): string {
  if (!isoStr) return ''
  try {
    const d = new Date(isoStr)
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })
  } catch {
    return ''
  }
}

const PHASE_LABELS: Record<string, string> = {
  queued: 'QUEUED',
  extracting_frames: 'EXTRACTING FRAMES',
  analyzing_stats: 'ANALYZING STATS',
  saving: 'SAVING TO DB',
  phase1_done: 'STATS READY',
  compressing: 'COMPRESSING',
  analyzing_gameplay: 'ANALYZING GAMEPLAY',
  analyzing: 'ANALYZING',
  cutting_clips: 'CUTTING CLIPS',
  done: 'COMPLETE',
  error: 'FAILED',
}

function phaseLabel(status: string): string {
  return PHASE_LABELS[status] || status.toUpperCase()
}

function phaseColor(status: string): string {
  switch (status) {
    case 'done': return 'text-m-green'
    case 'phase1_done': return 'text-m-yellow'
    case 'error': return 'text-m-red'
    case 'queued': return 'text-m-text-muted'
    default: return 'text-m-yellow'
  }
}

function statusCardText(counts: Record<string, number>): string {
  const parts: string[] = []
  const active = [
    'extracting_frames', 'analyzing_stats', 'saving', 'phase1_done',
    'compressing', 'analyzing_gameplay', 'analyzing', 'cutting_clips',
  ]
  for (const phase of active) {
    if (counts[phase]) {
      const label = PHASE_LABELS[phase] || phase.toUpperCase()
      parts.push(`${counts[phase]} ${label}`)
    }
  }
  if (counts.queued) parts.push(`${counts.queued} QUEUED`)
  if (parts.length === 0) return '0 PENDING'
  return parts.join(' | ')
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

export default function Live() {
  const [status, setStatus] = useState<CaptureStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [frameKey, setFrameKey] = useState(0)
  const { refreshData, addToast } = useStore()

  useEffect(() => {
    let interval: ReturnType<typeof setInterval>
    let frameInterval: ReturnType<typeof setInterval>

    async function poll() {
      try {
        const s = await getCaptureStatus()
        setStatus(s)
        setError(null)

        // Auto-start the capture engine if it's not active
        if (!s.active) {
          try {
            await axios.post(`${apiBase}/api/capture/start`, {})
          } catch {}
        }
      } catch {
        setError('Capture engine not running')
      }
    }

    poll()
    interval = setInterval(poll, 2000)
    frameInterval = setInterval(() => setFrameKey(k => k + 1), 2000)

    const runlog = (window as any).runlog
    if (runlog?.onRecordingStatus) {
      runlog.onRecordingStatus(() => poll())
    }

    return () => {
      clearInterval(interval)
      clearInterval(frameInterval)
    }
  }, [])

  // Auto-refresh dashboard data when a new run is processed
  useEffect(() => {
    const newRunId = status?.last_result?.run_id
    if (newRunId && newRunId !== getSeenRunId()) {
      setSeenRunId(newRunId)
      refreshData()
      addToast({
        type: 'success',
        title: 'RUN PROCESSED',
        body: `Run #${newRunId} analyzed and saved`,
      })
    }
  }, [status?.last_result?.run_id])

  // Refresh dashboard when Phase 1 stats are ready (before Phase 2 finishes)
  useEffect(() => {
    const items = status?.processing_items || []
    const phase1Item = items.find(i => i.status === 'phase1_done' && i.run_id)
    if (phase1Item?.run_id) {
      refreshData()
    }
  }, [status?.processing_items?.find(i => i.status === 'phase1_done')?.run_id])

  // Show toast for auto-resumed recordings
  useEffect(() => {
    if (status?.resumed_count && status.resumed_count > 0 && !wasResumeToastShown()) {
      markResumeToastShown()
      addToast({
        type: 'info',
        title: 'RESUMING PROCESSING',
        body: `Found ${status.resumed_count} unprocessed recording${status.resumed_count > 1 ? 's' : ''} from last session`,
      })
    }
  }, [status?.resumed_count])

  const processingItems = status?.processing_items || []
  const counts = status?.status_counts || {}
  const hasActive = Object.keys(counts).some(k => !['done', 'error'].includes(k) && counts[k] > 0)

  // Show newest first
  const displayItems = [...processingItems].reverse()

  return (
    <div className="max-w-7xl mx-auto space-y-4">
      {/* Header */}
      <div>
        <p className="label-tag text-m-green">CAPTURE // LIVE</p>
        <h2 className="text-xl font-display font-black tracking-wider text-m-text mt-1">
          AUTO-CAPTURE
        </h2>
      </div>

      {/* Status Cards */}
      <div className="grid grid-cols-4 gap-[1px] bg-m-border">
        <div className="bg-m-card p-5">
          <p className="label-tag text-m-text-muted">ENGINE</p>
          <p className={`text-2xl font-mono font-bold mt-1 ${
            status?.active ? 'text-m-green' : error ? 'text-m-red' : 'text-m-yellow'
          }`}>
            {status?.active ? 'ACTIVE' : error ? 'OFFLINE' : 'WAITING'}
          </p>
        </div>
        <div className="bg-m-card p-5">
          <p className="label-tag text-m-text-muted">RECORDING</p>
          <p className={`text-2xl font-mono font-bold mt-1 ${
            status?.recording ? 'text-m-red' : 'text-m-text-muted'
          }`}>
            {status?.recording ? 'RECORDING' : 'IDLE'}
          </p>
        </div>
        <div className="bg-m-card p-5">
          <p className="label-tag text-m-text-muted">DURATION</p>
          <p className="text-2xl font-mono font-bold mt-1 text-m-text">
            {status?.recording ? formatTime(status.recording_seconds) : '--:--'}
          </p>
        </div>
        <div className="bg-m-card p-5">
          <p className="label-tag text-m-text-muted">QUEUE</p>
          <p className={`text-2xl font-mono font-bold mt-1 ${
            hasActive ? 'text-m-yellow' : 'text-m-text-muted'
          }`}>
            {statusCardText(counts)}
          </p>
        </div>
      </div>

      {/* Recording indicator */}
      {status?.recording && (
        <div className="bg-m-card border border-m-red/40 p-4 flex items-center gap-3">
          <div className="w-3 h-3 bg-m-red rounded-full animate-pulse" />
          <span className="text-sm font-mono text-m-red font-bold tracking-wider">
            REC {formatTime(status.recording_seconds)}
          </span>
          <span className="text-xs text-m-text-muted ml-2">
            {status.recording_path?.split(/[/\\]/).pop()}
          </span>
        </div>
      )}

      {/* Detection Feed */}
      <div>
        <p className="label-tag text-m-text-muted mb-3">DETECTION FEED</p>
        <div className="bg-m-card border border-m-border p-2">
          {status?.active && status?.capture_mode === 'wgc' ? (
            <img
              src={`${getFrameUrl()}?t=${frameKey}`}
              alt="Detection feed"
              className="w-full max-h-[400px] object-contain"
            />
          ) : (
            <div className="h-[300px] flex items-center justify-center flex-col gap-3">
              <p className="text-m-text-muted text-sm font-mono tracking-wider">
                {error
                  ? 'CAPTURE ENGINE OFFLINE'
                  : status?.capture_mode === 'waiting' || status?.capture_mode === 'none'
                    ? 'NO GAME DETECTED'
                    : 'STARTING...'}
              </p>
              {(status?.capture_mode === 'waiting' || status?.capture_mode === 'none') && (
                <p className="text-m-text-muted/50 text-xs">
                  Launch Marathon for game capture
                </p>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Processing Queue - always visible */}
      <div>
        <p className="label-tag text-m-text-muted mb-3">PROCESSING QUEUE</p>
        <div className="bg-m-card border border-m-border">
          {displayItems.length === 0 ? (
            <div className="px-5 py-4 flex items-center gap-3">
              <div className="w-2 h-2 bg-m-text-muted/40 rounded-full" />
              <span className="text-xs font-mono text-m-text-muted">
                WAITING FOR RUNS
              </span>
            </div>
          ) : (
            <div className="divide-y divide-m-border max-h-[500px] overflow-y-auto">
              {displayItems.map((item, i) => (
                <div key={`${item.file}-${i}`} className="px-5 py-3 flex items-center gap-4">
                  {/* Thumbnail */}
                  {item.thumbnail ? (
                    <img
                      src={getThumbnailUrl(item.thumbnail)}
                      alt=""
                      className="w-16 h-9 object-cover rounded border border-m-border flex-shrink-0"
                    />
                  ) : (
                    <div className="w-16 h-9 bg-m-border/30 rounded border border-m-border flex-shrink-0" />
                  )}

                  {/* Status dot */}
                  {item.status === 'done' ? (
                    <div className="w-2 h-2 bg-m-green rounded-full flex-shrink-0" />
                  ) : item.status === 'error' ? (
                    <div className="w-2 h-2 bg-m-red rounded-full flex-shrink-0" />
                  ) : item.status === 'queued' ? (
                    <div className="w-2 h-2 bg-m-text-muted rounded-full flex-shrink-0" />
                  ) : (
                    <div className="w-2 h-2 bg-m-yellow rounded-full animate-pulse flex-shrink-0" />
                  )}

                  {/* Info */}
                  <div className="flex-1 min-w-0">
                    <span className="text-xs font-mono text-m-text truncate block">
                      {item.file}
                    </span>
                    <div className="flex items-center gap-3 mt-0.5">
                      {item.created_at && (
                        <span className="text-[10px] font-mono text-m-text-muted">
                          TIME: {formatTimestamp(item.created_at)}
                        </span>
                      )}
                      {item.duration_seconds && (
                        <span className="text-[10px] font-mono text-m-text-muted">
                          LENGTH: {formatTime(item.duration_seconds)}
                        </span>
                      )}
                      {item.run_id && (
                        <span className="text-[10px] font-mono text-m-green">
                          RUN {item.run_id}
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Status + actions */}
                  <div className="flex items-center gap-3 flex-shrink-0">
                    {item.status === 'done' ? (
                      <>
                        <button
                          onClick={() => axios.post(`${apiBase}/api/capture/recording/keep`, { filename: item.file })
                            .then(() => addToast({ type: 'success', title: 'VIDEO SAVED', body: item.file }))
                            .catch(() => addToast({ type: 'error', title: 'SAVE FAILED', body: item.file }))}
                          className="label-tag px-2 py-1 border border-m-green/40 text-m-green hover:bg-m-green-glow transition-all"
                        >
                          KEEP
                        </button>
                        <button
                          onClick={() => axios.post(`${apiBase}/api/capture/recording/delete`, { filename: item.file })
                            .then(() => addToast({ type: 'info', title: 'VIDEO DELETED', body: item.file }))
                            .catch(() => addToast({ type: 'error', title: 'DELETE FAILED', body: item.file }))}
                          className="label-tag px-2 py-1 border border-m-red/40 text-m-red hover:bg-m-red-glow transition-all"
                        >
                          DELETE
                        </button>
                        <span className="text-xs font-mono font-bold tracking-wider text-m-green">
                          COMPLETE
                        </span>
                      </>
                    ) : (
                      <span className={`text-xs font-mono font-bold tracking-wider ${phaseColor(item.status)}`}>
                        {phaseLabel(item.status)}
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

    </div>
  )
}
