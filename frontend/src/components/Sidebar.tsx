import { useStore } from '../lib/store'
import type { View } from '../lib/types'

interface NavItem {
  view: View
  label: string
  tag: string
  disabled?: boolean
}

interface NavSection {
  title: string
  items: NavItem[]
}

const sections: NavSection[] = [
  {
    title: 'SYSTEM',
    items: [
      { view: 'dashboard', label: 'OVERVIEW', tag: '01' },
      { view: 'history', label: 'ARCHIVE', tag: '02' },
      { view: 'shells', label: 'SHELLS', tag: '03' },
      { view: 'squad', label: 'SQUAD', tag: '04' },
    ],
  },
  {
    title: 'MAPS',
    items: [
      { view: 'map-perimeter', label: 'PERIMETER', tag: '05' },
      { view: 'map-dire-marsh', label: 'DIRE MARSH', tag: '06' },
      { view: 'map-outpost', label: 'OUTPOST', tag: '07' },
      { view: 'map-cryo-archive', label: 'CRYO ARCHIVE', tag: '08', disabled: true },
    ],
  },
  {
    title: 'CAPTURE',
    items: [
      { view: 'live' as View, label: 'LIVE', tag: '09' },
      { view: 'highlights' as View, label: 'DEBRIEF', tag: '10' },
    ],
  },
]

export default function Sidebar() {
  const { view, setView, stats } = useStore()

  return (
    <aside className="w-52 bg-m-black border-r border-1 border-m-border flex flex-col">
      {/* Header */}
      <div className="px-4 pt-5 pb-3">
        <p className="label-tag text-m-green flex items-center gap-2">
          <span className="w-1.5 h-1.5 bg-m-green rounded-full animate-pulse-slow" />
          SYSTEM ONLINE
        </p>
        <h1 className="text-xl font-display font-black tracking-wider text-m-text mt-1">
          RUNLOG.EXE
        </h1>
      </div>

      {/* Stats */}
      {stats && (
        <div className="px-4 pt-[22px] pb-3 space-y-1">
          <div className="flex justify-between">
            <span className="label-tag text-m-text-muted">RUNS</span>
            <span className="text-2xs font-mono text-m-text">{stats.total_runs}</span>
          </div>
          <div className="flex justify-between">
            <span className="label-tag text-m-text-muted">SURV%</span>
            <span className={`text-2xs font-mono ${
              stats.survival_rate >= 50 ? 'text-m-green' : 'text-m-red'
            }`}>{stats.survival_rate}%</span>
          </div>
          <div className="flex justify-between">
            <span className="label-tag text-m-text-muted">K/D</span>
            <span className={`text-2xs font-mono ${
              stats.kd_ratio >= 1 ? 'text-m-green' : 'text-m-red'
            }`}>{stats.kd_ratio.toFixed(2)}</span>
          </div>
        </div>
      )}

      {/* Nav with sections */}
      <nav className="flex-1">
        {sections.map((section) => (
          <div key={section.title}>
            {/* Section header */}
            <div className="px-4 pt-3 pb-1">
              <span className="text-[9px] tracking-[0.2em] font-bold text-m-text-muted/70 uppercase">
                {section.title}
              </span>
            </div>

            {/* Section items */}
            {section.items.map((item) => (
              <button
                key={item.view}
                onClick={() => !item.disabled && setView(item.view)}
                className={`w-full flex items-center gap-3 px-4 py-2 text-left transition-all border-l-2 ${
                  item.disabled
                    ? 'border-transparent cursor-not-allowed opacity-40'
                    : view === item.view
                      ? 'border-m-green bg-m-green-glow text-m-green'
                      : 'border-transparent text-m-text-dim hover:text-m-text hover:bg-m-surface'
                }`}
              >
                <span className={`label-tag ${
                  item.disabled ? 'text-m-text-muted' : view === item.view ? 'text-m-green' : 'text-m-text-muted'
                }`}>
                  {item.tag}
                </span>
                <div className="flex-1">
                  <span className={`text-xs tracking-[0.1em] font-medium ${item.disabled ? 'line-through decoration-m-red/60' : ''}`}>
                    {item.label}
                  </span>
                  {item.disabled && (
                    <p className="label-tag text-m-red/50 mt-0.5">REDACTED</p>
                  )}
                </div>
              </button>
            ))}
          </div>
        ))}
      </nav>

      {/* Config */}
      <button
        onClick={() => setView('settings')}
        className={`w-full flex items-center gap-3 px-4 py-3 text-left transition-all ${
          view === 'settings'
            ? 'bg-m-green-glow text-m-green'
            : 'text-m-text-dim hover:text-m-text hover:bg-m-surface'
        }`}
      >
        <span className={`label-tag ${view === 'settings' ? 'text-m-green' : 'text-m-text-muted'}`}>00</span>
        <span className="text-xs tracking-[0.1em] font-medium">SYS.CONFIG</span>
      </button>
    </aside>
  )
}
