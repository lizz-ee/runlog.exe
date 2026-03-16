import { useEffect, useState } from 'react'
import { useStore } from '../lib/store'
import { getOverviewStats, getRecentRuns } from '../lib/api'
import { format } from 'date-fns'
import type { Run } from '../lib/types'

function formatTime(seconds: number): string {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (h > 0) return `${h}h ${m}m`
  return `${m}m`
}

function formatDuration(seconds: number | null): string {
  if (!seconds) return '—'
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

export default function Dashboard() {
  const { stats, runs, setStats, setRuns, setView } = useStore()

  useEffect(() => {
    getOverviewStats().then(setStats)
    getRecentRuns(20).then(setRuns)
  }, [])

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      {/* Header */}
      <div>
        <p className="label-tag text-m-green">SYSTEM / OVERVIEW</p>
        <h2 className="text-xl font-display font-black tracking-wider text-m-text mt-1">
          DASHBOARD
        </h2>
      </div>

      {/* Core Stats — the numbers that matter most */}
      <div className="grid grid-cols-4 gap-[1px] bg-m-border">
        <StatBlock label="TOTAL RUNS" value={String(stats?.total_runs ?? 0)} accent />
        <StatBlock label="SURVIVAL RATE" value={`${stats?.survival_rate ?? 0}%`}
          color={(stats?.survival_rate ?? 0) >= 50 ? 'green' : 'red'} />
        <StatBlock label="K/D" value={stats?.kd_ratio?.toFixed(2) ?? '0.00'}
          color={(stats?.kd_ratio ?? 0) >= 1 ? 'green' : 'red'} />
        <StatBlock label="TOTAL TIME" value={formatTime(stats?.total_time_seconds ?? 0)} color="cyan" />
      </div>

      {/* Combat + Economy side by side */}
      <div className="grid grid-cols-2 gap-6">
        {/* Combat */}
        <div>
          <p className="label-tag text-m-text-muted mb-2">COMBAT</p>
          <div className="grid grid-cols-2 gap-[1px] bg-m-border">
            <StatBlock label="PVE KILLS" value={String(runs.reduce((s, r) => s + (r.combatant_eliminations || 0), 0))} small color="green" />
            <StatBlock label="RUNNER KILLS" value={String(runs.reduce((s, r) => s + (r.runner_eliminations || 0), 0))} small color="cyan" />
            <StatBlock label="DEATHS" value={String(stats?.total_deaths ?? 0)} small color="red" />
            <StatBlock label="REVIVES" value={String(stats?.total_revives ?? 0)} small color="green" />
          </div>
        </div>

        {/* Economy */}
        <div>
          <p className="label-tag text-m-text-muted mb-2">ECONOMY</p>
          <div className="grid grid-cols-2 gap-[1px] bg-m-border">
            <StatBlock label="TOTAL LOOT" value={`$${(stats?.total_loot_value ?? 0).toLocaleString()}`} small color="yellow" />
            <StatBlock label="AVG LOOT/RUN" value={`$${stats?.avg_loot_per_run?.toFixed(0) ?? '0'}`} small color="yellow" />
            <StatBlock label="FAV MAP" value={stats?.favorite_map ?? '—'} small />
            <StatBlock label="FAV SQUAD MATE" value={stats?.favorite_squad_mate ?? '—'} small color="cyan" />
          </div>
        </div>
      </div>

      {/* Time by Map */}
      {stats?.time_by_map && stats.time_by_map.length > 0 && (
        <div>
          <p className="label-tag text-m-text-muted mb-2">TIME BY MAP</p>
          <div className={`grid grid-cols-${Math.min(stats.time_by_map.length, 4)} gap-[1px] bg-m-border`}>
            {stats.time_by_map.map((mt) => (
              <StatBlock key={mt.map_name} label={mt.map_name.toUpperCase()} value={formatTime(mt.total_seconds)} small color="cyan" />
            ))}
          </div>
        </div>
      )}

      {/* Recent Runs */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <p className="label-tag text-m-green">RECENT OPERATIONS</p>
          <button
            onClick={() => setView('history')}
            className="label-tag text-m-green hover:underline"
          >
            VIEW ALL →
          </button>
        </div>

        {runs.length === 0 ? (
          <div className="border border-1 border-m-border bg-m-card p-10 text-center">
            <p className="text-m-text-muted text-sm">NO RUNS LOGGED</p>
            <p className="label-tag text-m-text-muted mt-2">
              PRESS F12 IN-GAME TO START TRACKING
            </p>
          </div>
        ) : (
          <div className="border border-1 border-m-green/20 divide-y divide-m-border">
            {runs.slice(0, 7).map((run) => (
              <RunRow key={run.id} run={run} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function RunRow({ run }: { run: Run }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div>
      <div
        onClick={() => setExpanded(!expanded)}
        className="grid grid-cols-[50px_6px_110px_1fr_40px_40px_30px_30px_75px_50px] items-center gap-x-3 px-4 py-3 bg-m-card hover:bg-m-surface transition-colors cursor-pointer"
      >
        <span className={`label-tag px-2 py-0.5 border border-1 text-center ${
          run.survived
            ? 'border-m-green/30 text-m-green bg-m-green-glow'
            : 'border-m-red/30 text-m-red bg-m-red-glow'
        }`}>
          {run.survived ? 'EXFIL' : 'KIA'}
        </span>
        <div className={`w-1.5 h-8 ${run.survived ? 'bg-m-green' : 'bg-m-red'}`} />
        <span className="label-tag text-m-text-muted">
          {format(new Date(run.date), 'yyyy.MM.dd HH:mm')}
        </span>
        <span className="text-xs text-m-text tracking-wider uppercase truncate">
          {run.map_name ?? 'UNKNOWN'}
          {run.spawn_location && (
            <span className="text-m-text-muted"> — {run.spawn_location}</span>
          )}
        </span>
        <span className={`text-xs font-mono text-right ${run.combatant_eliminations ? 'text-m-green' : 'text-m-text-muted'}`}>
          {run.combatant_eliminations || 0}<span className="text-m-text-muted text-2xs">PVE</span>
        </span>
        <span className={`text-xs font-mono text-right ${run.runner_eliminations ? 'text-m-cyan' : 'text-m-text-muted'}`}>
          {run.runner_eliminations || 0}<span className="text-m-text-muted text-2xs">RNR</span>
        </span>
        <span className={`text-xs font-mono text-right ${run.deaths ? 'text-m-red' : 'text-m-text-muted'}`}>
          {run.deaths}<span className="text-m-text-muted text-2xs">D</span>
        </span>
        <span className={`text-xs font-mono text-right ${run.crew_revives ? 'text-m-green' : 'text-m-text-muted'}`}>
          {run.crew_revives || 0}<span className="text-m-text-muted text-2xs">R</span>
        </span>
        <span className={`text-xs font-mono text-right ${
          run.loot_value_total >= 0 ? 'text-m-yellow' : 'text-m-red'
        }`}>
          ${run.loot_value_total.toLocaleString()}
        </span>
        <span className="text-xs font-mono text-m-text-muted text-right">
          {formatDuration(run.duration_seconds)}
        </span>
      </div>

      {expanded && (
        <div className="px-6 py-4 bg-m-surface border-t border-m-border">
          <div className="grid grid-cols-3 gap-6">
            <div className="space-y-2">
              <p className="label-tag text-m-green mb-2">RUN DETAILS</p>
              <DetailRow label="MAP" value={run.map_name ?? '—'} />
              <DetailRow label="SPAWN" value={run.spawn_location ?? 'Unknown'} />
              <DetailRow label="OUTCOME" value={run.survived ? 'Exfiltrated' : 'Eliminated'}
                color={run.survived ? 'green' : 'red'} />
              <DetailRow label="DURATION" value={formatDuration(run.duration_seconds)} />
              <DetailRow label="DATE" value={format(new Date(run.date), 'yyyy.MM.dd HH:mm:ss')} />
            </div>
            <div className="space-y-2">
              <p className="label-tag text-m-green mb-2">COMBAT</p>
              <DetailRow label="PVE KILLS" value={String(run.combatant_eliminations || 0)} color="green" />
              <DetailRow label="RUNNER KILLS" value={String(run.runner_eliminations || 0)} color="cyan" />
              <DetailRow label="DEATHS" value={String(run.deaths)} color={run.deaths > 0 ? 'red' : undefined} />
              <DetailRow label="REVIVES" value={String(run.crew_revives || 0)} color="green" />
              <DetailRow label="TOTAL KILLS" value={String((run.combatant_eliminations || 0) + (run.runner_eliminations || 0))} />
            </div>
            <div className="space-y-2">
              <p className="label-tag text-m-green mb-2">LOOT & SQUAD</p>
              <DetailRow label="INVENTORY" value={`$${run.loot_value_total.toLocaleString()}`}
                color={run.loot_value_total >= 0 ? 'yellow' : 'red'} />
              <DetailRow label="SQUAD SIZE" value={run.squad_size ? `${run.squad_size} players` : 'Solo'} />
              {run.squad_members && run.squad_members.length > 0 && (
                <div>
                  <span className="text-[9px] text-m-text-muted uppercase">SQUAD</span>
                  <div className="mt-0.5">
                    {run.squad_members.map((m, i) => (
                      <p key={i} className="text-[10px] font-mono text-m-text">{m}</p>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
          {run.notes && (
            <div className="mt-4 pt-3 border-t border-m-border">
              <p className="label-tag text-m-text-muted mb-1">NOTES</p>
              <p className="text-xs text-m-text">{run.notes}</p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function StatBlock({
  label, value, color, small, accent,
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
  }[color ?? ''] ?? 'text-m-text'

  return (
    <div className={`bg-m-card ${small ? 'p-3' : 'p-5'} ${accent ? 'border-t-2 border-m-green' : ''}`}>
      <p className="label-tag text-m-text-muted">{label}</p>
      <p className={`${small ? 'text-lg' : 'text-2xl'} font-mono font-bold mt-1 ${colorClass}`}>
        {value}
      </p>
    </div>
  )
}

function DetailRow({ label, value, color }: { label: string; value: string; color?: 'green' | 'red' | 'yellow' | 'cyan' }) {
  const c = color === 'green' ? 'text-m-green' : color === 'red' ? 'text-m-red' : color === 'yellow' ? 'text-m-yellow' : color === 'cyan' ? 'text-m-cyan' : 'text-m-text'
  return (
    <div className="flex justify-between">
      <span className="text-[9px] text-m-text-muted uppercase">{label}</span>
      <span className={`text-[10px] font-mono ${c}`}>{value}</span>
    </div>
  )
}
