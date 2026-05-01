import { useEffect, useState, useCallback } from 'react'
import { useStore } from '../lib/store'
import { getOverviewStats, getRecentRuns, markRunViewed, markAllRunsViewed, getClips, toggleFavorite, getVaultValues } from '../lib/api'
import { RunRow, matchRunClips } from './RunHistory'
import { AreaChart, Area, XAxis, YAxis, Tooltip, CartesianGrid, ResponsiveContainer } from 'recharts'
import { formatDuration } from '../lib/utils'

import type { Clip } from '../lib/types'

export default function Dashboard() {
  const { stats, runs, setStats, setRuns, setView, refreshUnviewed, captureStatus } = useStore()
  const [clips, setClipsState] = useState<Clip[]>([])
  const [expanded, setExpanded] = useState<Set<number>>(new Set())
  const [vaultData, setVaultData] = useState<{ value: number }[]>([])

  // Refresh triggers: new run (P1) or processing item completes (P2)
  const lastRunId = captureStatus?.last_result?.run_id
  const doneCount = captureStatus?.processing_items?.filter(i => i.status === 'done').length ?? 0

  useEffect(() => {
    getOverviewStats().then(setStats)
    getRecentRuns(20).then(setRuns)
    getClips().then(setClipsState).catch((e) => console.error('[Dashboard] fetch clips failed:', e))
    getVaultValues().then(setVaultData).catch((e) => console.error('[Dashboard] fetch vault values failed:', e))
  }, [lastRunId, doneCount])

  const refreshRuns = useCallback(() => {
    getRecentRuns(20).then(setRuns).catch((e) => console.error('[Dashboard] refresh runs failed:', e))
  }, [])

  const handleToggleFavorite = async (e: React.MouseEvent, runId: number) => {
    e.stopPropagation()
    try {
      const result = await toggleFavorite(runId)
      setRuns(runs.map(r => r.id === runId ? { ...r, is_favorite: result.is_favorite } : r))
    } catch (e) { console.error('[Dashboard] toggle favorite failed:', e) }
  }

  const toggleExpand = (runId: number) => {
    setExpanded(prev => {
      const next = new Set(prev)
      if (next.has(runId)) next.delete(runId)
      else {
        next.add(runId)
        const run = runs.find(r => r.id === runId)
        if (run && !run.viewed) {
          markRunViewed(runId).then(() => {
            setRuns(runs.map(r => r.id === runId ? { ...r, viewed: true } : r))
            refreshUnviewed()
          }).catch((e) => console.error('[Dashboard] mark run viewed failed:', e))
        }
      }
      return next
    })
  }

  return (
    <div className="max-w-7xl mx-auto space-y-4">
      {/* Header */}
      <div>
        <p className="label-tag text-m-green">SYSTEM // TERMINAL</p>
        <h2 className="text-xl font-display font-black tracking-wider text-m-text mt-1">
          {(() => {
            const latestLevel = runs.find(r => r.player_level != null)?.player_level
            return latestLevel != null ? `LVL:${latestLevel}:` : 'TERMINAL'
          })()}
        </h2>
      </div>

      {/* Core Stats — hero numbers */}
      <div className="grid grid-cols-4 gap-[1px] bg-m-border">
        <StatBlock label="TOTAL RUNS" value={String(stats?.total_runs ?? 0)} accent />
        <StatBlock label="SURVIVAL RATE" value={`${stats?.survival_rate ?? 0}%`}
          color={(stats?.survival_rate ?? 0) >= 50 ? 'green' : 'red'} />
        <StatBlock label="K/D" value={stats?.kd_ratio?.toFixed(2) ?? '0.00'}
          color={(stats?.kd_ratio ?? 0) >= 1 ? 'green' : 'red'} />
        <StatBlock label="TOTAL TIME" value={formatDuration(stats?.total_time_seconds ?? 0)} color="cyan" />
      </div>

      {/* Detail columns */}
      <div className="grid grid-cols-4 gap-[1px] bg-m-border">
        {/* Column 1: Favorites */}
        <div className="bg-m-card">
          <div className="px-4 py-2 border-b border-m-border">
            <p className="label-tag text-m-green">FAVORITES</p>
          </div>
          <div className="divide-y divide-m-border">
            <ColStat label="SHELL" value={stats?.favorite_shell ?? '—'} />
            <ColStat label="WEAPON" value={stats?.favorite_weapon ?? '—'} />
            <ColStat label="MAP" value={stats?.favorite_map ?? '—'} />
            <ColStat label="SQUAD MATE" value={stats?.favorite_squad_mate ?? '—'} />
          </div>
        </div>

        {/* Column 2: Economy */}
        <div className="bg-m-card">
          <div className="px-4 py-2 border-b border-m-border">
            <p className="label-tag text-m-green">ECONOMY</p>
          </div>
          <div className="divide-y divide-m-border">
            <ColStat label="TOTAL LOOT" value={`$${(stats?.total_loot_value ?? 0).toLocaleString()}`} color="yellow" />
            <ColStat label="AVG LOOT/RUN" value={`$${stats?.avg_loot_per_run?.toFixed(0) ?? '0'}`} color="yellow" />
            <ColStat label="BEST RUN" value={runs.length > 0 ? `$${Math.max(...runs.map(r => r.loot_value_total)).toLocaleString()}` : '—'} color="yellow" />
            <ColStat label="WORST RUN" value={runs.length > 0 ? `$${Math.min(...runs.map(r => r.loot_value_total)).toLocaleString()}` : '—'} color="red" />
          </div>
        </div>

        {/* Column 3: Combat */}
        <div className="bg-m-card">
          <div className="px-4 py-2 border-b border-m-border">
            <p className="label-tag text-m-green">COMBAT</p>
          </div>
          <div className="divide-y divide-m-border">
            <ColStat label="PVE KILLS" value={String(runs.reduce((s, r) => s + (r.combatant_eliminations || 0), 0))} color="green" />
            <ColStat label="RUNNER KILLS" value={String(runs.reduce((s, r) => s + (r.runner_eliminations || 0), 0))} color="cyan" />
            <ColStat label="DEATHS" value={String(stats?.total_deaths ?? 0)} color="red" />
            <ColStat label="REVIVES" value={String(stats?.total_revives ?? 0)}
              color={(stats?.total_revives ?? 0) > 0 ? 'green' : undefined} />
          </div>
        </div>

        {/* Column 4: Time by Map */}
        <div className="bg-m-card">
          <div className="px-4 py-2 border-b border-m-border">
            <p className="label-tag text-m-green">TIME BY MAP</p>
          </div>
          <div className="divide-y divide-m-border">
            {['Perimeter', 'Dire Marsh', 'Outpost', 'Cryo Archive'].map((mapName) => {
              const mt = stats?.time_by_map?.find(t => t.map_name === mapName)
              const seconds = mt?.total_seconds ?? 0
              return (
                <ColStat
                  key={mapName}
                  label={mapName.toUpperCase()}
                  value={formatDuration(seconds)}
                  color={seconds > 0 ? 'cyan' : undefined}
                />
              )
            })}
          </div>
        </div>
      </div>

      {/* Recent Runs */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <p className="label-tag text-m-text-muted">RECENT.RUNS</p>
          <div className="flex items-center gap-3">
            {runs.some(r => !r.viewed) && (
              <button
                onClick={() => {
                  markAllRunsViewed().then(() => {
                    setRuns(runs.map(r => ({ ...r, viewed: true })))
                    refreshUnviewed()
                  })
                }}
                className="label-tag text-m-cyan hover:text-m-text transition-colors"
              >
                MARK ALL READ
              </button>
            )}
            <button
              onClick={() => setView('history')}
              className="label-tag text-m-green hover:underline"
            >
              VIEW ALL →
            </button>
          </div>
        </div>

        {runs.length === 0 ? (
          <div className="border border-1 border-m-border bg-m-card p-10 text-center">
            <p className="text-m-text-muted text-sm">NO RUNS LOGGED</p>
            <p className="label-tag text-m-text-muted mt-2">
              LAUNCH MARATHON TO START AUTO-TRACKING
            </p>
          </div>
        ) : (
          <div className="border border-1 border-m-green/20 divide-y divide-m-border">
            {runs.slice(0, 7).map((run) => (
              <RunRow
                key={run.id}
                run={run}
                isExpanded={expanded.has(run.id)}
                onToggle={() => toggleExpand(run.id)}
                onToggleFavorite={(e) => handleToggleFavorite(e, run.id)}
                onUpdate={refreshRuns}
                clips={matchRunClips(run, clips)}
              />
            ))}
          </div>
        )}
      </div>

      {/* VAULT.VALUE Chart */}
      <div>
        <div className="flex justify-between items-center mb-1.5">
          <span className="label-tag text-m-text-muted">VAULT.VALUE</span>
          {vaultData.length > 0 && (
            <span className="text-[7px] font-mono text-m-text-muted/40 tracking-wider">
              {vaultData.length} DATAPOINT{vaultData.length !== 1 ? 'S' : ''}
            </span>
          )}
        </div>
        <div className="bg-m-card border border-m-border" style={{ height: 180 }}>
          {vaultData.length > 1 ? (
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={vaultData} margin={{ top: 5, right: 15, bottom: 5, left: -5 }}>
                <defs>
                  <linearGradient id="grad-vault" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#c8ff00" stopOpacity={0.15} />
                    <stop offset="100%" stopColor="#c8ff00" stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#1a1a2e" />
                <XAxis hide />
                <YAxis tick={{ fontSize: 8, fill: '#555', fontFamily: 'monospace' }} axisLine={{ stroke: '#1a1a2e' }} tickLine={false}
                  tickFormatter={v => `$${(v / 1000).toFixed(0)}k`} />
                <Tooltip
                  contentStyle={{ background: '#0a0a0f', border: '1px solid #1a1a2e', fontSize: 10, fontFamily: 'monospace' }}
                  labelStyle={{ display: 'none' }}
                  formatter={(v) => {
                    const n = typeof v === 'number' ? v : Number(v ?? 0)
                    return [`$${n.toLocaleString()}`, 'VAULT']
                  }}
                />
                <Area type="monotone" dataKey="value" stroke="#c8ff00" strokeWidth={2} fill="url(#grad-vault)"
                  dot={{ r: 3, fill: '#c8ff00', stroke: '#c8ff00', strokeWidth: 1 }}
                  activeDot={{ r: 5, fill: '#c8ff00', stroke: '#050508', strokeWidth: 2 }} />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-full relative">
              <div className="absolute inset-0 opacity-[0.04]" style={{
                backgroundImage: 'linear-gradient(to right, rgba(200,255,0,0.3) 1px, transparent 1px), linear-gradient(to bottom, rgba(200,255,0,0.3) 1px, transparent 1px)',
                backgroundSize: '20% 25%',
              }} />
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="text-center space-y-2">
                  <p className="text-xs font-mono text-m-text-muted tracking-widest">AWAITING DATA</p>
                  <p className="text-[9px] font-mono text-m-text-muted">Vault value tracked per run</p>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}


function StatBlock({
  label, value, color, small, accent: _accent,
}: {
  label: string
  value: string
  color?: 'green' | 'red' | 'yellow' | 'cyan'
  small?: boolean
  accent?: boolean
}) {
  const colorClass = {
    green: 'text-m-green',
    red: 'text-m-red',
    yellow: 'text-m-yellow',
    cyan: 'text-m-cyan',
  }[color as string] ?? 'text-m-text'

  return (
    <div className={`bg-m-card ${small ? 'p-3' : 'p-5'}`}>
      <p className="label-tag text-m-text-muted">{label}</p>
      <p className={`${small ? 'text-lg' : 'text-2xl'} font-mono font-bold mt-1 ${colorClass}`}>
        {value}
      </p>
    </div>
  )
}

function ColStat({ label, value, color }: { label: string; value: string; color?: 'green' | 'red' | 'yellow' | 'cyan' }) {
  const c = color
    ? { green: 'text-m-green', red: 'text-m-red', yellow: 'text-m-yellow', cyan: 'text-m-cyan' }[color]
    : 'text-m-text'
  return (
    <div className="flex justify-between items-center px-4 py-2.5">
      <span className="label-tag text-m-text-muted">{label}</span>
      <span className={`text-xs font-mono font-bold ${c}`}>{value}</span>
    </div>
  )
}

