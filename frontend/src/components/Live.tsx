import { useEffect, useState, useCallback } from 'react'
import axios from 'axios'
import { getFrameUrl, getThumbnailUrl, apiBase } from '../lib/api'
import { useStore } from '../lib/store'
import { formatTime } from '../lib/utils'

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
  extracting_frames: 'FRAMES',
  analyzing_stats: 'STATS',
  phase1_done: 'STATS',
  saving: 'STATS',
  analyzing_gameplay: 'GAMEPLAY',
  analyzing: 'GAMEPLAY',
  cutting_clips: 'CLIPS',
  error: 'FAILED',
}

// Ordered pipeline stages — items vanish after CLIPS
const PIPELINE_STAGES = [
  { key: 'queued', label: 'QUEUED', short: 'Q' },
  { key: 'extracting_frames', label: 'FRAMES', short: 'FR' },
  { key: 'analyzing_stats', label: 'STATS', short: 'ST' },
  { key: 'analyzing_gameplay', label: 'GAMEPLAY', short: 'GP' },
  { key: 'cutting_clips', label: 'CLIPS', short: 'CL' },
]

function getStageIndex(status: string): number {
  // Handle aliases
  const key = status === 'analyzing' ? 'analyzing_gameplay'
    : status === 'phase1_failed' ? 'phase1_done'
    : status
  const idx = PIPELINE_STAGES.findIndex(s => s.key === key)
  return idx >= 0 ? idx : -1
}

function PipelineProgress({ status, detail, p1Failed, p2Failed, runId }: {
  status: string
  detail?: string | null
  p1Failed?: boolean
  p2Failed?: boolean
  runId?: number | null
}) {
  const isP1Failed = status === 'phase1_failed' || !!p1Failed
  const isP2Failed = !!p2Failed
  const p1EndIdx = 2  // FRAMES, STATS = indices 1-2 (QUEUED=0 is Phase 0)
  const p2StartIdx = 3  // GAMEPLAY, CLIPS = indices 3-4

  // If status is "queued" but run_id exists, P1 is done — item is waiting for a P2 slot
  const p1Done = !!runId
  const isP2Waiting = status === 'queued' && p1Done
  const currentIdx = isP2Waiting ? 0 : getStageIndex(status)  // Circle is "active" (queued)

  // Shape per stage: P1 (circle, triangle, square), P2 (triangle, square)
  const SHAPES = ['circle', 'triangle', 'square', 'triangle', 'square'] as const

  return (
    <div className="flex items-center gap-0">
      {/* Detail text + flags before shapes */}
      <div className="flex flex-col items-end mr-2 gap-0">
        {status !== 'done' && status !== 'encoding' && !(status === 'queued' && !p1Done) && (
          <span className={`text-[9px] font-mono tracking-wider ${isP1Failed ? 'text-m-red' : status === 'queued' ? 'text-m-text-muted' : 'text-m-cyan'}`}>
            {status === 'queued' && p1Done ? 'QUEUED' : PHASE_LABELS[status] || status.toUpperCase()}
          </span>
        )}
        {detail && status !== 'done' && (
          <span className="text-[8px] font-mono text-m-text-muted/60 tracking-wider truncate max-w-[150px]">
            {detail}
          </span>
        )}
      </div>
      {PIPELINE_STAGES.map((stage, i) => {
        const isCompleted = i < currentIdx
        const isActive = i === currentIdx
        const isDone = status === 'done'
        const phaseGap = i === 3  // Gap between P1 and P2
        const shape = SHAPES[i]
        const isP2Stage = i >= p2StartIdx

        const colorClass = isP2Waiting
          ? (i === 0 ? 'text-m-cyan'          // Circle = queued (active cyan)
            : i <= p1EndIdx ? 'text-m-green'   // P1 shapes = done (green)
            : 'text-m-border/40')              // P2 shapes = not started (dim)
          : isDone
            ? (isP1Failed && i <= p1EndIdx ? 'text-m-red/60'
              : isP2Failed && isP2Stage ? 'text-m-red/60'
              : 'text-m-green')
            : isP1Failed && i <= p1EndIdx
              ? (isActive ? 'text-m-red' : isCompleted ? 'text-m-red/60' : 'text-m-border/40')
              : isCompleted
                ? 'text-m-green'
                : isActive
                  ? 'text-m-cyan'
                  : 'text-m-border/40'

        const spin = isActive && !isP2Waiting && (shape === 'square' || shape === 'triangle')

        return (
          <div key={stage.key} className={`flex items-center ${phaseGap ? 'ml-2' : 'ml-[3px]'} ${i === 0 ? 'ml-0' : ''}`}>
            <div>
              <svg width="8" height="8" viewBox="0 0 8 8" className={`${colorClass} ${spin ? 'animate-spin-slow' : ''}`} style={{
                ...(spin ? { animationDuration: '3s' } : {}),
                ...((isActive || (isP2Waiting && i === 0)) ? { filter: 'drop-shadow(0 0 3px currentColor)' } : {}),
              }}>
                {shape === 'circle' && (
                  <circle cx="4" cy="4" r="3.5" fill="currentColor" />
                )}
                {shape === 'square' && (
                  <rect x="0.5" y="0.5" width="7" height="7" rx="1" fill="currentColor" />
                )}
                {shape === 'triangle' && (
                  <polygon points="4,0.5 7.5,7 0.5,7" fill="currentColor" />
                )}
              </svg>
            </div>
          </div>
        )
      })}
    </div>
  )
}

function ScanLine({ gradient }: { gradient: string }) {
  const [key, setKey] = useState(0)
  const [duration, setDuration] = useState(() => 5 + Math.random() * 6)
  const onEnd = useCallback(() => {
    setDuration(5 + Math.random() * 6)
    setKey(k => k + 1)
  }, [])
  return (
    <div
      key={key}
      className={`absolute left-0 right-0 h-[15px] bg-gradient-to-b ${gradient} to-transparent`}
      style={{
        animation: `feedScan ${duration}s linear 1 forwards`,
      }}
      onAnimationEnd={onEnd}
    />
  )
}


export default function Live() {
  const status = useStore(s => s.captureStatus)
  const error = useStore(s => s.captureError)
  const [frameKey, setFrameKey] = useState(0)
  // dismissing state removed — recordings auto-save on completion
  const { addToast } = useStore()

  // Frame refresh interval — specific to Live page preview
  useEffect(() => {
    const frameInterval = setInterval(() => setFrameKey(k => k + 1), 2000)
    return () => clearInterval(frameInterval)
  }, [])

  const allItems = status?.processing_items || []
  // Filter out done/complete items — they vanish from the queue
  const processingItems = allItems.filter(i => !['done', 'complete'].includes(i.status))
  const counts = status?.status_counts || {}

  // Show newest first
  const displayItems = [...processingItems].reverse()

  return (
    <div className="max-w-7xl mx-auto space-y-4">
      {/* Header */}
      <div>
        <p className="label-tag text-m-green">CAPTURE // DETECT.EXE</p>
        <h2 className="text-xl font-display font-black tracking-wider text-m-text mt-1">
          DETECTION SYSTEM
        </h2>
      </div>

      {/* Detection Feed — cyberpunk terminal with CSS overlays */}
      <div>
        <div className={`relative overflow-hidden border-2 transition-colors duration-500 ${
          status?.recording ? 'border-m-red/50' : 'border-m-green/10'
        }`} style={{ background: 'radial-gradient(ellipse at center, #080812 0%, #030306 70%)' }}>
          {/* CRT effects — identical to UPLINK chat terminal */}
          <div className="absolute inset-0 pointer-events-none z-10"
            style={{ backgroundImage: 'repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(200,255,0,0.025) 2px, rgba(200,255,0,0.025) 3px)' }} />
          <div className="absolute inset-0 pointer-events-none z-10"
            style={{ boxShadow: 'inset 0 0 60px rgba(0,0,0,0.5), inset 0 0 120px rgba(0,0,0,0.3)' }} />

          {/* Top-left overlay: Engine + Detection */}
          <div className="absolute top-3 left-3 z-20 pointer-events-none feed-overlay-block feed-overlay-block-left">
            <p className={`text-[11px] font-mono font-bold tracking-wider ${
              status?.active ? 'text-m-green animate-rgb-split' : error ? 'text-m-red' : 'text-m-yellow'
            }`}>
              {status?.active ? 'ENGINE.ACTIVE' : error ? 'ENGINE.OFFLINE' : 'ENGINE.WAITING'}
            </p>
            <p className="text-[10px] font-mono text-m-text-muted mt-0.5">
              DET: <span className={
                !status?.last_detection ? 'text-m-text-muted/50'
                : status.last_detection === 'deploy' ? 'text-m-green'
                : status.last_detection === 'ready_up' ? 'text-m-yellow'
                : status.last_detection === 'run' ? 'text-m-yellow'
                : status.last_detection === 'deploying' ? 'text-m-yellow'
                : status.last_detection === 'searching' ? 'text-m-cyan'
                : status.last_detection === 'endgame' ? 'text-m-red'
                : status.last_detection === 'exfiltrated' ? 'text-m-green'
                : status.last_detection === 'eliminated' ? 'text-m-red'
                : status.last_detection === 'prepare' ? 'text-m-cyan'
                : status.last_detection === 'select_zone' ? 'text-m-cyan'
                : 'text-m-green'
              }>
                {status?.last_detection === 'run' ? 'RUN.EXE' : status?.last_detection?.toUpperCase().replace('_', '.') || 'NONE'}
              </span>
            </p>
          </div>

          {/* Top-right overlay: Branding + Recording */}
          <div className="absolute top-3 right-3 z-20 pointer-events-none feed-overlay-block feed-overlay-block-right">
            <p className="text-[11px] font-mono font-bold tracking-wider text-m-green">
              RUNLOG CAPTURE SYSTEMS
            </p>
            {status?.recording ? (
              <p className="text-[10px] font-mono text-m-red font-bold mt-0.5 animate-pulse">
                ■ REC {formatTime(status.recording_seconds)}
              </p>
            ) : (
              <p className="text-[10px] font-mono text-m-text-muted/50 mt-0.5">
                STANDBY
              </p>
            )}
          </div>

          {/* Bottom data bar — Marathon-style ticker. Hugs bottom in standby, overlays frame when active */}
          <div className={`absolute left-0 right-0 z-20 pointer-events-none flex items-center justify-between px-3 py-1.5 ${
            status?.has_frame && status?.window_found ? 'bottom-[30px]' : 'bottom-1'
          }`}>
            <div className="flex items-center gap-4">
              {status?.recording && status.recording_path && (
                <p className="text-[9px] font-mono text-m-text-muted/50">
                  {status.recording_path.split(/[/\\]/).pop()}
                </p>
              )}
              <p className="text-[8px] font-mono text-m-green/20 tracking-widest">
                RDP 978xd 1704-24595
              </p>
            </div>
            <div className="flex items-center gap-4">
              <p className="text-[8px] font-mono text-m-green/20 tracking-widest">
                IRT 7962 // TGSSPASK 7211
              </p>
              <p className="text-[9px] font-mono text-m-green/30 tracking-wider">
                {status?.capture_mode === 'wgc' ? 'WGC // 4K' : status?.capture_mode?.toUpperCase() || ''}
              </p>
            </div>
          </div>

          {/* OCR regions overlay — CSS positioned */}
          {status?.active && status?.capture_mode === 'wgc' && status?.has_frame && (
            <>
              {/* OCR.DEPLOY — center, map name detection */}
              <div className="absolute z-10 pointer-events-none" style={{ left: '35%', top: '38%', width: '30%', height: '27%' }}>
                <span className="absolute -top-4 left-0 text-[8px] font-mono text-m-cyan/50 tracking-wider">OCR.DEPLOY</span>
                <div className="w-full h-full border border-m-cyan/30 bg-m-cyan/[0.02] overflow-hidden relative">
                  <ScanLine gradient="from-m-cyan/[0.1]" />
                  <div className="absolute top-0 left-0 w-2 h-2 border-l border-t border-m-cyan/60" />
                  <div className="absolute top-0 right-0 w-2 h-2 border-r border-t border-m-cyan/60" />
                  <div className="absolute bottom-0 left-0 w-2 h-2 border-l border-b border-m-cyan/60" />
                  <div className="absolute bottom-0 right-0 w-2 h-2 border-r border-b border-m-cyan/60" />
                </div>
              </div>

              {/* OCR.ENDGAME — upper center, //RUN_COMPLETE */}
              <div className="absolute z-10 pointer-events-none" style={{ left: '28%', top: '13.5%', width: '44%', height: '14%' }}>
                <span className="absolute -top-4 left-0 text-[8px] font-mono text-m-green/50 tracking-wider">OCR.ENDGAME</span>
                <div className="w-full h-full border border-m-green/20 bg-m-green/[0.01] overflow-hidden relative">
                  <ScanLine gradient="from-m-green/[0.1]" />
                  <div className="absolute top-0 left-0 w-2 h-2 border-l border-t border-m-green/40" />
                  <div className="absolute top-0 right-0 w-2 h-2 border-r border-t border-m-green/40" />
                  <div className="absolute bottom-0 left-0 w-2 h-2 border-l border-b border-m-green/40" />
                  <div className="absolute bottom-0 right-0 w-2 h-2 border-r border-b border-m-green/40" />
                </div>
              </div>

              {/* OCR.LOBBY — bottom center, PREPARE/READY UP */}
              <div className="absolute z-10 pointer-events-none" style={{ left: '33%', top: '72%', width: '34%', height: '17%' }}>
                <span className="absolute -top-4 left-0 text-[8px] font-mono text-m-yellow/50 tracking-wider">OCR.LOBBY</span>
                <div className="w-full h-full border border-m-yellow/30 bg-m-yellow/[0.02] overflow-hidden relative">
                  <ScanLine gradient="from-m-yellow/[0.1]" />
                  <div className="absolute top-0 left-0 w-2 h-2 border-l border-t border-m-yellow/60" />
                  <div className="absolute top-0 right-0 w-2 h-2 border-r border-t border-m-yellow/60" />
                  <div className="absolute bottom-0 left-0 w-2 h-2 border-l border-b border-m-yellow/60" />
                  <div className="absolute bottom-0 right-0 w-2 h-2 border-r border-b border-m-yellow/60" />
                </div>
              </div>
            </>
          )}

          {/* The actual feed — no PIL debug overlay */}
          {status?.active && status?.capture_mode === 'wgc' && status?.has_frame ? (
            <img
              src={`${getFrameUrl()}?t=${frameKey}`}
              alt=""
              className="w-full aspect-video object-contain relative z-0 text-transparent"
            />
          ) : (
            <div className="h-[400px] flex items-center justify-center flex-col gap-4 relative z-0">
              {/* Empty state — cyberpunk terminal */}
              <div className="animate-glitch">
                <p className="text-m-green/60 text-lg font-mono tracking-[0.3em] font-bold">
                  {error
                    ? 'ENGINE.OFFLINE'
                    : status?.capture_mode === 'unavailable'
                      ? 'RECORDER.MISSING'
                      : status?.capture_mode === 'wgc' && status?.window_found
                        ? 'INITIALIZING...'
                        : 'AWAITING SIGNAL'}
                </p>
              </div>
              <div className="text-center space-y-2">
                <p className="text-m-text-muted/40 text-[10px] font-mono tracking-[0.2em]">
                  {status?.active ? 'ENGINE.ACTIVE' : 'ENGINE.STANDBY'} // {status?.capture_mode?.toUpperCase() || 'NONE'}
                </p>
                {!(status?.capture_mode === 'wgc' && status?.window_found) && (
                  <p className="text-m-text-muted/20 text-[10px] font-mono tracking-wider">
                    Launch Marathon to begin detection
                  </p>
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Pipeline Overview */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <p className="label-tag text-m-text-muted">PIPELINE.STATUS</p>
          <div className="flex items-center gap-4 text-[10px] font-mono text-m-text-muted">
            <span>{processingItems.length} TOTAL</span>
            {(counts.done || 0) > 0 && <span className="text-m-green">{counts.done} DONE</span>}
            {(counts.error || 0) > 0 && <span className="text-m-red">{counts.error} FAILED</span>}
          </div>
        </div>
      <div className="bg-m-card border border-m-border px-6 pt-4 pb-5 relative overflow-hidden">

        {/* Pill-shaped pipeline — Marathon HUD style */}
        {(() => {
          const phases = [
            { label: 'PHASE.00 // QUEUE', stages: PIPELINE_STAGES.slice(0, 1) },
            { label: 'PHASE.01 // STATS', stages: PIPELINE_STAGES.slice(1, 3) },
            { label: 'PHASE.02 // NARRATIVE', stages: PIPELINE_STAGES.slice(3) },
          ]

          function pillColor(key: string, hasItems: boolean) {
            if (!hasItems) return 'border-m-border/20 bg-m-surface/50'
            if (key === 'done') return 'border-m-green bg-m-green/15'
            if (key === 'queued') return 'border-m-text-muted/60 bg-m-text-muted/5'
            return 'border-m-cyan bg-m-cyan/10 animate-pill-glow'
          }

          function pillTextColor(key: string, hasItems: boolean) {
            if (!hasItems) return 'text-m-text-muted/25'
            if (key === 'done') return 'text-m-green'
            if (key === 'queued') return 'text-m-text-muted'
            return 'text-m-cyan'
          }

          return (
            <div className="flex items-start gap-4">
              {phases.map((phase, pi) => (
                <div key={pi} style={{ flex: phase.stages.length }}>
                  <p className="text-[8px] font-mono tracking-[0.2em] text-m-text-muted/40 mb-2">{phase.label}</p>
                  <div className="flex gap-[2px]">
                    {phase.stages.map((stage, si) => {
                      const count = stage.key === 'analyzing_gameplay'
                        ? (counts[stage.key] || 0) + (counts['analyzing'] || 0)
                        : (counts[stage.key] || 0)
                      const hasItems = count > 0
                      const isFirst = si === 0
                      const isLast = si === phase.stages.length - 1
                      const rounded = isFirst && isLast
                        ? 'rounded-full'
                        : isFirst
                          ? 'rounded-l-full rounded-r-[3px]'
                          : isLast
                            ? 'rounded-r-full rounded-l-[3px]'
                            : 'rounded-[3px]'

                      return (
                        <div
                          key={stage.key}
                          className={`flex-1 flex items-center justify-center border ${rounded} h-7 transition-all ${pillColor(stage.key, hasItems)}`}
                        >
                          <span className={`text-[9px] font-mono font-bold tracking-wider ${pillTextColor(stage.key, hasItems)}`}>
                            {hasItems ? `${count} ${stage.label}` : stage.label}
                          </span>
                        </div>
                      )
                    })}
                  </div>
                </div>
              ))}
            </div>
          )
        })()}
      </div>
      </div>

      {/* Processing Queue - always visible */}
      <div>
        <p className="label-tag text-m-text-muted mb-3">PROCESSING.QUEUE</p>
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
                      {item.status === 'error' && (
                        <span className="text-[10px] font-mono text-m-red">FAILED</span>
                      )}
                    </div>
                  </div>

                  {/* Status + actions — fixed width for alignment */}
                  <div className="flex items-center gap-3 flex-shrink-0 w-[200px] justify-end">
                    {item.status === 'error' ? (
                      <div className="flex items-center gap-3">
                        <button
                          onClick={() => {
                            axios.post(`${apiBase}/api/capture/recording/retry`, { filename: item.file })
                              .then(() => addToast({ type: 'info', title: 'RETRYING', body: item.file }))
                              .catch(() => addToast({ type: 'error', title: 'RETRY FAILED', body: item.file }))
                          }}
                          className="label-tag px-2 py-1 border border-m-yellow/40 text-m-yellow hover:bg-m-yellow/10 transition-all"
                        >
                          RETRY
                        </button>
                        <div className="flex flex-col items-end">
                          <span className="text-xs font-mono font-bold tracking-wider text-m-red">
                            FAILED
                          </span>
                          {item.detail && (
                            <span className="text-[8px] font-mono text-m-red/50 tracking-wider truncate max-w-[150px]" title={item.detail}>
                              {item.detail}
                            </span>
                          )}
                        </div>
                      </div>
                    ) : (
                      <PipelineProgress status={item.status} detail={item.detail} p1Failed={item.p1_failed} p2Failed={item.p2_failed} runId={item.run_id} />
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
