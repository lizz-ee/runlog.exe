import { useEffect, useState } from 'react'
import { getRuns, getClips, getClipUrl } from '../lib/api'
import type { Run, Clip } from '../lib/types'

const GRADE_COLORS: Record<string, string> = {
  S: 'text-m-yellow border-m-yellow bg-m-yellow/10',
  A: 'text-m-green border-m-green bg-m-green/10',
  B: 'text-m-cyan border-m-cyan bg-m-cyan/10',
  C: 'text-m-text border-m-border bg-m-border/10',
  D: 'text-m-red/70 border-m-red/50 bg-m-red/5',
  F: 'text-m-red border-m-red bg-m-red/10',
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

function formatDate(dateStr: string): string {
  const d = new Date(dateStr)
  const month = d.toLocaleDateString('en-US', { month: 'short' })
  const day = d.getDate()
  const h = String(d.getHours()).padStart(2, '0')
  const m = String(d.getMinutes()).padStart(2, '0')
  return `${month} ${day}, ${h}:${m}`
}

const RUNS_PER_PAGE = 21 // Marathon lore — divisible by 7

export default function RunReports() {
  const [runs, setRuns] = useState<Run[]>([])
  const [clips, setClips] = useState<Clip[]>([])
  const [playingClips, setPlayingClips] = useState<Record<number, string>>({})
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(0)
  const [expanded, setExpanded] = useState<Set<number>>(new Set())

  useEffect(() => {
    async function load() {
      try {
        const [allRuns, allClips] = await Promise.all([
          getRuns({ limit: 500 }),
          getClips(),
        ])
        // Filter to runs with summaries (auto-captured and processed)
        const reportRuns = allRuns.filter((r: Run) => r.summary)
        setRuns(reportRuns)
        setClips(allClips)
      } catch (e) {
        console.error('Failed to load run reports:', e)
      }
      setLoading(false)
    }
    load()
  }, [])

  const totalPages = Math.max(1, Math.ceil(runs.length / RUNS_PER_PAGE))
  const pageRuns = runs.slice(page * RUNS_PER_PAGE, (page + 1) * RUNS_PER_PAGE)

  // Match clips to runs by shared recording timestamp
  // Clip filename has YYYYMMDD_HHMMSS matching the recording start time
  function getRunClips(run: Run): Clip[] {
    // Convert run date to YYYYMMDD_HHMMSS format for matching
    const d = new Date(run.date)
    const runTs = [
      d.getFullYear(),
      String(d.getMonth() + 1).padStart(2, '0'),
      String(d.getDate()).padStart(2, '0'),
      '_',
      String(d.getHours()).padStart(2, '0'),
      String(d.getMinutes()).padStart(2, '0'),
      String(d.getSeconds()).padStart(2, '0'),
    ].join('')

    const directMatch = clips.filter(c => c.run_timestamp === runTs)
    if (directMatch.length > 0) return directMatch

    // Fallback: timestamp proximity (for old clips)
    const runEpoch = d.getTime() / 1000
    return clips.filter(c => {
      const diff = c.created - runEpoch
      return diff >= 0 && diff < 7200
    })
  }

  if (loading) {
    return (
      <div className="max-w-7xl mx-auto space-y-6">
        <div>
          <p className="label-tag text-m-green">CAPTURE / RUN REPORTS</p>
          <h2 className="text-xl font-display font-black tracking-wider text-m-text mt-1">
            RUN REPORTS
          </h2>
        </div>
        <div className="bg-m-card border border-m-border p-10 text-center">
          <p className="text-m-text-muted text-sm">LOADING...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-end justify-between">
        <div>
          <p className="label-tag text-m-green">CAPTURE / RUN REPORTS</p>
          <h2 className="text-xl font-display font-black tracking-wider text-m-text mt-1">
            RUN REPORTS
          </h2>
        </div>
        <p className="label-tag text-m-text-muted">
          {runs.length} REPORT{runs.length !== 1 ? 'S' : ''}
        </p>
      </div>

      {/* Empty state */}
      {runs.length === 0 ? (
        <div className="bg-m-card border border-m-border p-10 text-center">
          <p className="text-m-text-muted text-sm">NO RUN REPORTS YET</p>
          <p className="label-tag text-m-text-muted mt-2">
            REPORTS ARE AUTO-GENERATED WHEN SONNET ANALYZES YOUR RECORDED RUNS
          </p>
        </div>
      ) : (
        <div className="space-y-6">
          {pageRuns.map((run) => {
            const runClips = getRunClips(run)
            const gradeClass = GRADE_COLORS[run.grade || ''] || GRADE_COLORS.C
            const isExpanded = expanded.has(run.id)
            const toggleExpand = () => setExpanded(prev => {
              const next = new Set(prev)
              if (next.has(run.id)) next.delete(run.id)
              else next.add(run.id)
              return next
            })
            return (
              <div
                key={run.id}
                className={`bg-m-card border ${
                  run.survived
                    ? 'border-m-green/30'
                    : 'border-m-red/30'
                }`}
              >
                {/* Header row — always visible, clickable to expand */}
                <button
                  onClick={toggleExpand}
                  className="w-full text-left p-6 pb-0 flex items-center gap-4"
                >
                  {run.grade && (
                    <span className={`text-3xl font-display font-black px-3 py-1 border rounded ${gradeClass}`}>
                      {run.grade}
                    </span>
                  )}
                  <div className="flex-1">
                    <div className="flex items-center gap-3">
                      <span className={`label-tag px-2 py-0.5 border ${
                        run.survived
                          ? 'border-m-green/30 text-m-green bg-m-green-glow'
                          : 'border-m-red/30 text-m-red bg-m-red-glow'
                      }`}>
                        {run.survived ? 'EXTRACTED' : 'KIA'}
                      </span>
                      <span className="text-sm font-mono text-m-text font-bold">
                        {run.map_name || 'UNKNOWN MAP'}
                      </span>
                      {run.spawn_location && (
                        <span className="label-tag text-m-text-muted">
                          {run.spawn_location}
                        </span>
                      )}
                    </div>
                    <p className="label-tag text-m-text-muted mt-1">
                      {formatDate(run.date)}
                    </p>
                  </div>

                  {/* Quick stats inline */}
                  <div className="flex items-center gap-4 text-xs font-mono">
                    <span className="text-m-text">{run.kills}K</span>
                    <span className="text-m-green">${run.loot_value_total}</span>
                    <span className="text-m-text-muted">{run.duration_seconds ? formatTime(run.duration_seconds) : '--:--'}</span>
                  </div>

                  {run.killed_by && (
                    <div className="text-right">
                      <p className="label-tag text-m-red">KILLED BY</p>
                      <p className="text-xs font-mono text-m-text">{run.killed_by}</p>
                    </div>
                  )}

                  <span className={`text-m-text-muted text-xs transition-transform ${isExpanded ? 'rotate-180' : ''}`}>
                    ▼
                  </span>
                </button>

                {/* Expanded content */}
                {isExpanded && (
                  <div className="px-6 pb-6">
                    {/* Stats row */}
                    <div className="grid grid-cols-6 gap-4 my-4 py-3 border-y border-m-border">
                      <div>
                        <p className="label-tag text-m-text-muted">KILLS</p>
                        <p className="text-lg font-mono font-bold text-m-text mt-1">
                          {run.kills}
                        </p>
                      </div>
                      <div>
                        <p className="label-tag text-m-text-muted">PVE</p>
                        <p className="text-lg font-mono font-bold text-m-text mt-1">
                          {run.combatant_eliminations}
                        </p>
                      </div>
                      <div>
                        <p className="label-tag text-m-text-muted">PVP</p>
                        <p className="text-lg font-mono font-bold text-m-text mt-1">
                          {run.runner_eliminations}
                        </p>
                      </div>
                      <div>
                        <p className="label-tag text-m-text-muted">LOOT</p>
                        <p className="text-lg font-mono font-bold text-m-green mt-1">
                          ${run.loot_value_total}
                        </p>
                      </div>
                      <div>
                        <p className="label-tag text-m-text-muted">DURATION</p>
                        <p className="text-lg font-mono font-bold text-m-text mt-1">
                          {run.duration_seconds ? formatTime(run.duration_seconds) : '--:--'}
                        </p>
                      </div>
                      <div>
                        <p className="label-tag text-m-text-muted">WEAPONS</p>
                        <p className="text-xs font-mono text-m-text mt-1 truncate" title={[run.primary_weapon, run.secondary_weapon].filter(Boolean).join(' / ')}>
                          {run.primary_weapon || '—'}
                        </p>
                      </div>
                    </div>

                    {/* Sonnet's narrative */}
                    {run.summary && (
                      <div className="mb-4">
                        <p className="label-tag text-m-text-muted mb-2">RUN REPORT</p>
                        <p className="text-sm text-m-text leading-relaxed whitespace-pre-line">
                          {run.summary}
                        </p>
                      </div>
                    )}

                    {/* Highlight clips — inline player per run */}
                    {runClips.length > 0 && (
                      <div>
                        <p className="label-tag text-m-text-muted mb-2">
                          HIGHLIGHTS — {runClips.length} CLIP{runClips.length !== 1 ? 'S' : ''}
                        </p>
                        {playingClips[run.id] && (
                          <div className="mb-3 border border-m-green/40 bg-m-surface">
                            <video
                              src={getClipUrl(playingClips[run.id])}
                              controls
                              autoPlay
                              className="w-full max-h-[400px]"
                              onEnded={() => setPlayingClips(prev => { const next = { ...prev }; delete next[run.id]; return next })}
                            />
                            <div className="flex items-center justify-between px-3 py-1.5">
                              <span className="text-[10px] font-mono text-m-text-muted">{playingClips[run.id]}</span>
                              <button
                                onClick={(e) => { e.stopPropagation(); setPlayingClips(prev => { const next = { ...prev }; delete next[run.id]; return next }) }}
                                className="label-tag text-m-text-muted hover:text-m-red transition-colors"
                              >
                                CLOSE
                              </button>
                            </div>
                          </div>
                        )}
                        <div className="grid grid-cols-3 gap-3">
                          {runClips.map((clip) => (
                            <button
                              key={clip.filename}
                              onClick={(e) => { e.stopPropagation(); setPlayingClips(prev => ({ ...prev, [run.id]: clip.filename })) }}
                              className={`bg-m-surface border overflow-hidden text-left transition-all hover:border-m-green/40 ${
                                playingClips[run.id] === clip.filename ? 'border-m-green/60' : 'border-m-border'
                              }`}
                            >
                              {clip.thumbnail ? (
                                <img
                                  src={getClipUrl(clip.thumbnail)}
                                  alt=""
                                  className="w-full h-24 object-cover"
                                />
                              ) : (
                                <div className="w-full h-24 bg-m-border/20 flex items-center justify-center">
                                  <span className="text-m-text-muted text-xs">NO PREVIEW</span>
                                </div>
                              )}
                              <div className="p-2 flex items-center justify-between">
                                <span className="label-tag text-m-cyan">
                                  {clip.type.toUpperCase().replace('_', ' ')}
                                </span>
                                <span className="label-tag text-m-text-muted">
                                  {clip.size_mb} MB
                                </span>
                              </div>
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {/* Bottom padding when collapsed */}
                {!isExpanded && <div className="pb-4" />}
              </div>
            )
          })}

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-center gap-3 pt-4">
              <button
                onClick={() => setPage(p => Math.max(0, p - 1))}
                disabled={page === 0}
                className="label-tag px-3 py-1.5 border border-m-border text-m-text-muted hover:text-m-text hover:border-m-green/40 disabled:opacity-30 disabled:cursor-not-allowed transition-all"
              >
                PREV
              </button>
              {Array.from({ length: totalPages }, (_, i) => (
                <button
                  key={i}
                  onClick={() => setPage(i)}
                  className={`label-tag px-2.5 py-1.5 border transition-all ${
                    i === page
                      ? 'border-m-green text-m-green bg-m-green-glow'
                      : 'border-m-border text-m-text-muted hover:text-m-text hover:border-m-green/40'
                  }`}
                >
                  {i + 1}
                </button>
              ))}
              <button
                onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))}
                disabled={page === totalPages - 1}
                className="label-tag px-3 py-1.5 border border-m-border text-m-text-muted hover:text-m-text hover:border-m-green/40 disabled:opacity-30 disabled:cursor-not-allowed transition-all"
              >
                NEXT
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
