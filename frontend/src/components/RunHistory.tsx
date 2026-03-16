import { useEffect, useState } from 'react'
import { format } from 'date-fns'
import { getRuns, deleteRun } from '../lib/api'
import { useStore } from '../lib/store'
import type { Run } from '../lib/types'

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

  async function handleDelete(id: number) {
    await deleteRun(id)
    setRuns(runs.filter((r) => r.id !== id))
  }

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div>
        <p className="label-tag text-m-green">SYSTEM / ARCHIVE</p>
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

      {/* Run List */}
      {filtered.length === 0 ? (
        <div className="border border-1 border-m-border bg-m-card p-10 text-center">
          <p className="text-xs text-m-text-muted tracking-wider">NO MATCHING RECORDS</p>
        </div>
      ) : (
        <div className="border border-1 border-m-green/20 divide-y divide-m-border">
          {filtered.map((run) => (
            <RunRow key={run.id} run={run} onDelete={() => handleDelete(run.id)} />
          ))}
        </div>
      )}
    </div>
  )
}

function RunRow({ run, onDelete }: { run: Run; onDelete: () => void }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div>
      <div
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-4 px-4 py-3 bg-m-card hover:bg-m-surface transition-colors cursor-pointer"
      >
        <div className={`w-1.5 h-8 ${run.survived ? 'bg-m-green' : 'bg-m-red'}`} />
        <span className="label-tag text-m-text-muted w-32 shrink-0">
          {format(new Date(run.date), 'yyyy.MM.dd HH:mm')}
        </span>
        <span className="text-xs text-m-text tracking-wider flex-1 uppercase">
          {run.map_name ?? 'UNKNOWN ZONE'}
        </span>
        <div className="flex items-center gap-3 font-mono text-xs">
          <span className="text-m-green">{run.combatant_eliminations || 0}<span className="text-m-text-muted text-2xs">PVE</span></span>
          <span className="text-m-cyan">{run.runner_eliminations || 0}<span className="text-m-text-muted text-2xs">PVP</span></span>
          <span className="text-m-red">{run.deaths}<span className="text-m-text-muted text-2xs">D</span></span>
        </div>
        <span className={`text-xs font-mono w-20 text-right ${
          run.loot_value_total >= 0 ? 'text-m-yellow' : 'text-m-red'
        }`}>
          ${run.loot_value_total.toLocaleString()}
        </span>
        <span className={`label-tag px-2 py-1 border border-1 ${
          run.survived
            ? 'border-m-green/30 text-m-green bg-m-green-glow'
            : 'border-m-red/30 text-m-red bg-m-red-glow'
        }`}>
          {run.survived ? 'EXFIL' : 'KIA'}
        </span>
      </div>

      {expanded && (
        <div className="px-4 py-3 bg-m-surface border-t border-m-border space-y-2">
          {run.duration_seconds && (
            <p className="text-xs text-m-text-dim font-mono">
              DURATION: {Math.floor(run.duration_seconds / 60)}:{String(run.duration_seconds % 60).padStart(2, '0')}
            </p>
          )}
          {run.notes && <p className="text-xs text-m-text">{run.notes}</p>}
          {run.loot_extracted && run.loot_extracted.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {run.loot_extracted.map((item, i) => (
                <span key={i} className="label-tag bg-m-card border border-1 border-m-border px-2 py-1 text-m-yellow">
                  {item.name}: ${item.value}
                </span>
              ))}
            </div>
          )}
          <button
            onClick={(e) => { e.stopPropagation(); onDelete() }}
            className="label-tag text-m-red/40 hover:text-m-red transition-colors"
          >
            DELETE RECORD
          </button>
        </div>
      )}
    </div>
  )
}
