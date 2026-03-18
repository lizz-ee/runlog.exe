import { useEffect, useState } from 'react'
import { format } from 'date-fns'
import { getRuns } from '../lib/api'
import { useStore } from '../lib/store'
import type { Run } from '../lib/types'

function formatDuration(seconds: number | null): string {
  if (!seconds) return '—'
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

export default function RunHistory() {
  const { runs, setRuns } = useStore()
  const [filter, setFilter] = useState<'all' | 'survived' | 'died'>('all')
  const [mapFilter, setMapFilter] = useState('')

  useEffect(() => {
    getRuns({ limit: 200 }).then(setRuns).catch(console.error)
  }, [])

  const filtered = runs.filter((r) => {
    if (filter === 'survived' && !r.survived) return false
    if (filter === 'died' && r.survived) return false
    if (mapFilter && r.map_name?.toLowerCase() !== mapFilter.toLowerCase()) return false
    return true
  })

  const maps = [...new Set(runs.map((r) => r.map_name).filter(Boolean))]

  return (
    <div className="max-w-7xl mx-auto space-y-4">
      <div>
        <p className="label-tag text-m-green">SYSTEM // ARCHIVE</p>
        <h2 className="text-xl font-display font-black tracking-wider text-m-text mt-1">
          RUN HISTORY
        </h2>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-4 flex-wrap">
        <div className="flex gap-[1px] bg-m-border">
          {(['all', 'survived', 'died'] as const).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-4 py-2 text-xs tracking-widest uppercase transition-all ${
                filter === f
                  ? 'bg-[#c8ff00]/10 text-[#c8ff00] border-b-2 border-[#c8ff00]'
                  : 'bg-m-card text-m-text-muted hover:text-m-text'
              }`}
            >
              {f === 'all' ? 'ALL' : f === 'survived' ? 'EXFIL' : 'KIA'}
            </button>
          ))}
        </div>

        {maps.length > 0 && (
          <select
            value={mapFilter}
            onChange={(e) => setMapFilter(e.target.value)}
            className="px-3 py-2 text-xs bg-m-black text-m-text border border-1 border-m-border focus:outline-none appearance-none"
            style={{ colorScheme: 'dark' }}
          >
            <option value="">ALL ZONES</option>
            {maps.map((m) => (
              <option key={m} value={m!}>{m!.toUpperCase()}</option>
            ))}
          </select>
        )}

        <span className="label-tag text-m-text-muted ml-auto">
          {filtered.length} OPERATION{filtered.length !== 1 ? 'S' : ''}
        </span>
      </div>

      {/* Column headers */}
      <div className="grid grid-cols-[50px_6px_110px_auto_1fr_40px_40px_30px_30px_75px_50px] items-center gap-x-3 px-4 py-2 border-b border-m-border">
        <span className="label-tag text-m-text-muted text-center">STATUS</span>
        <span />
        <span className="label-tag text-m-text-muted">DATE</span>
        <span className="label-tag text-m-text-muted">SHELL</span>
        <span className="label-tag text-m-text-muted">LOCATION</span>
        <span className="label-tag text-m-text-muted text-right">PVE</span>
        <span className="label-tag text-m-text-muted text-right">RNR</span>
        <span className="label-tag text-m-text-muted text-right">DEATH</span>
        <span className="label-tag text-m-text-muted text-right">REV</span>
        <span className="label-tag text-m-text-muted text-right">LOOT</span>
        <span className="label-tag text-m-text-muted text-right">TIME</span>
      </div>

      {/* Run List */}
      {filtered.length === 0 ? (
        <div className="border border-1 border-m-border bg-m-card p-10 text-center">
          <p className="text-xs text-m-text-muted tracking-wider">NO MATCHING RECORDS</p>
        </div>
      ) : (
        <div className="border border-1 border-m-green/20 divide-y divide-m-border">
          {filtered.map((run) => (
            <RunRow key={run.id} run={run} />
          ))}
        </div>
      )}
    </div>
  )
}

function RunRow({ run }: { run: Run }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div>
      <div
        onClick={() => setExpanded(!expanded)}
        className="grid grid-cols-[50px_6px_110px_auto_1fr_40px_40px_30px_30px_75px_50px] items-center gap-x-3 px-4 py-3 bg-m-card hover:bg-m-surface transition-colors cursor-pointer"
      >
        {/* Status badge */}
        <span className={`label-tag px-2 py-0.5 border border-1 text-center ${
          run.survived
            ? 'border-m-green/30 text-m-green bg-m-green-glow'
            : 'border-m-red/30 text-m-red bg-m-red-glow'
        }`}>
          {run.survived ? 'EXFIL' : 'KIA'}
        </span>

        {/* Status bar */}
        <div className={`w-1.5 h-8 ${run.survived ? 'bg-m-green' : 'bg-m-red'}`} />

        {/* Timestamp */}
        <span className="label-tag text-m-text-muted">
          {format(new Date(run.date), 'yyyy.MM.dd HH:mm')}
        </span>

        {/* Shell */}
        <span className="text-xs text-m-cyan tracking-wider uppercase truncate">
          {run.shell_name ?? '—'}
        </span>

        {/* Map + Spawn */}
        <span className="text-xs text-m-text tracking-wider uppercase truncate">
          {run.map_name ?? 'UNKNOWN'}
          {run.spawn_location && (
            <span className="text-m-text-muted"> — {run.spawn_location}</span>
          )}
        </span>

        <span className={`text-xs font-mono text-right ${run.combatant_eliminations ? 'text-m-green' : 'text-m-text-muted'}`}>
          {run.combatant_eliminations || 0}<span className="text-m-text-muted text-2xs"> PVE</span>
        </span>
        <span className={`text-xs font-mono text-right ${run.runner_eliminations ? 'text-m-cyan' : 'text-m-text-muted'}`}>
          {run.runner_eliminations || 0}<span className="text-m-text-muted text-2xs"> RNR</span>
        </span>
        <span className={`text-xs font-mono text-right ${run.deaths ? 'text-m-red' : 'text-m-text-muted'}`}>
          {run.deaths}<span className="text-m-text-muted text-2xs"> D</span>
        </span>
        <span className={`text-xs font-mono text-right ${run.crew_revives ? 'text-m-green' : 'text-m-text-muted'}`}>
          {run.crew_revives || 0}<span className="text-m-text-muted text-2xs"> R</span>
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
            {/* Left column - Run details */}
            <div className="space-y-2">
              <p className="label-tag text-m-green mb-2">RUN DETAILS</p>
              <DetailRow label="MAP" value={run.map_name ?? '—'} />
              <DetailRow label="SPAWN" value={run.spawn_location ?? 'Unknown'} />
              <DetailRow label="SHELL" value={run.shell_name ?? 'Unknown'} />
              <DetailRow label="PRIMARY" value={run.primary_weapon ?? '—'} />
              <DetailRow label="SECONDARY" value={run.secondary_weapon ?? '—'} />
              <DetailRow label="OUTCOME" value={run.survived ? 'Exfiltrated' : 'Eliminated'}
                color={run.survived ? 'green' : 'red'} />
              {run.killed_by && (
                <DetailRow label="KILLED BY" value={`${run.killed_by}${run.killed_by_damage ? ` (${run.killed_by_damage} DMG)` : ''}`} color="red" />
              )}
              <DetailRow label="DURATION" value={formatDuration(run.duration_seconds)} />
            </div>

            {/* Middle column - Combat */}
            <div className="space-y-2">
              <p className="label-tag text-m-green mb-2">COMBAT</p>
              <DetailRow label="PVE KILLS" value={String(run.combatant_eliminations || 0)} color="green" />
              <DetailRow label="RUNNER KILLS" value={String(run.runner_eliminations || 0)} color="cyan" />
              <DetailRow label="DEATHS" value={String(run.deaths)} color={run.deaths > 0 ? 'red' : undefined} />
              <DetailRow label="REVIVES" value={String(run.crew_revives || 0)} color="green" />
              <DetailRow label="TOTAL KILLS" value={String((run.combatant_eliminations || 0) + (run.runner_eliminations || 0))} />
            </div>

            {/* Right column - Loot & Squad */}
            <div className="space-y-2">
              <p className="label-tag text-m-green mb-2">LOOT & SQUAD</p>
              <DetailRow label="INVENTORY" value={`$${run.loot_value_total.toLocaleString()}`}
                color={run.loot_value_total >= 0 ? 'yellow' : 'red'} />
              {run.squad_members && run.squad_members.length > 0 ? (
                run.squad_members.map((m, i) => (
                  <DetailRow key={i} label={i === 0 ? 'SQUAD' : ''} value={m} />
                ))
              ) : (
                <DetailRow label="SQUAD" value="Solo" />
              )}
              <DetailRow label="DATE" value={format(new Date(run.date), 'yyyy.MM.dd HH:mm:ss')} />
            </div>
          </div>

          {/* Notes */}
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

function DetailRow({ label, value, color }: { label: string; value: string; color?: 'green' | 'red' | 'yellow' | 'cyan' }) {
  const c = color === 'green' ? 'text-m-green' : color === 'red' ? 'text-m-red' : color === 'yellow' ? 'text-m-yellow' : color === 'cyan' ? 'text-m-cyan' : 'text-m-text'
  return (
    <div className="flex justify-between">
      <span className="text-[9px] text-m-text-muted uppercase">{label}</span>
      <span className={`text-[10px] font-mono ${c}`}>{value}</span>
    </div>
  )
}
