import { useStore } from '../lib/store'
import { format } from 'date-fns'

export default function Dashboard() {
  const { stats, runs, setView } = useStore()

  return (
    <div className="max-w-6xl mx-auto space-y-8">
      {/* Header */}
      <div className="flex items-end justify-between">
        <div>
          <p className="label-tag text-m-green">SYSTEM / OVERVIEW</p>
          <h2 className="text-xl font-display font-black tracking-wider text-m-text mt-1">
            DASHBOARD
          </h2>
        </div>
      </div>

      {/* Primary Stats */}
      <div className="grid grid-cols-4 gap-[1px] bg-m-border">
        <StatBlock
          label="TOTAL RUNS"
          value={String(stats?.total_runs ?? 0)}
          accent
        />
        <StatBlock
          label="SURVIVAL RATE"
          value={`${stats?.survival_rate ?? 0}%`}
          color={(stats?.survival_rate ?? 0) >= 50 ? 'green' : 'red'}
        />
        <StatBlock
          label="RUNNER K/D"
          value={stats?.kd_ratio?.toFixed(2) ?? '0.00'}
          color={(stats?.kd_ratio ?? 0) >= 1 ? 'green' : 'red'}
        />
        <StatBlock
          label="TOTAL LOOT"
          value={`$${(stats?.total_loot_value ?? 0).toLocaleString()}`}
          color="yellow"
        />
      </div>

      {/* Secondary Stats */}
      <div className="grid grid-cols-5 gap-[1px] bg-m-border">
        <StatBlock label="PVE KILLS" value={String(runs.reduce((s, r) => s + (r.combatant_eliminations || 0), 0))} small color="green" />
        <StatBlock label="PVP KILLS" value={String(runs.reduce((s, r) => s + (r.runner_eliminations || 0), 0))} small color="cyan" />
        <StatBlock label="DEATHS" value={String(stats?.total_deaths ?? 0)} small color="red" />
        <StatBlock label="AVG LOOT/RUN" value={`$${stats?.avg_loot_per_run?.toFixed(0) ?? '0'}`} small color="yellow" />
        <StatBlock label="FAV MAP" value={stats?.favorite_map ?? '—'} small />
      </div>

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
            {runs.slice(0, 8).map((run) => (
              <div
                key={run.id}
                className="flex items-center gap-4 px-4 py-3 bg-m-card hover:bg-m-surface transition-colors"
              >
                {/* Status indicator */}
                <div className={`w-1.5 h-8 ${
                  run.survived ? 'bg-m-green' : 'bg-m-red'
                }`} />

                {/* Timestamp */}
                <span className="label-tag text-m-text-muted w-32 shrink-0">
                  {format(new Date(run.date), 'yyyy.MM.dd HH:mm')}
                </span>

                {/* Map */}
                <span className="text-xs text-m-text tracking-wider flex-1 uppercase">
                  {run.map_name ?? 'UNKNOWN ZONE'}
                </span>

                {/* PvE / PvP / Deaths */}
                <div className="flex items-center gap-3 font-mono text-xs">
                  <span className="text-m-green">{run.combatant_eliminations || 0}<span className="text-m-text-muted text-2xs">PVE</span></span>
                  <span className="text-m-cyan">{run.runner_eliminations || 0}<span className="text-m-text-muted text-2xs">PVP</span></span>
                  <span className="text-m-red">{run.deaths}<span className="text-m-text-muted text-2xs">D</span></span>
                </div>

                {/* Loot */}
                <span className={`text-xs font-mono w-20 text-right ${
                  run.loot_value_total >= 0 ? 'text-m-yellow' : 'text-m-red'
                }`}>
                  ${run.loot_value_total.toLocaleString()}
                </span>

                {/* Status badge */}
                <span className={`label-tag px-2 py-1 border border-1 ${
                  run.survived
                    ? 'border-m-green/30 text-m-green bg-m-green-glow'
                    : 'border-m-red/30 text-m-red bg-m-red-glow'
                }`}>
                  {run.survived ? 'EXFIL' : 'KIA'}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function StatBlock({
  label,
  value,
  color,
  small,
  accent,
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
