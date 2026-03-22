import { useEffect, useState } from 'react'
import axios from 'axios'
import { apiBase } from '../lib/api'
import { useStore } from '../lib/store'
import type { View, SpawnHeatmap, SpawnHeatmapEntry } from '../lib/types'

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
      { view: 'dashboard', label: 'TERMINAL', tag: '01' },
      { view: 'history', label: 'RUN.LOG', tag: '02' },
      { view: 'shells', label: 'NEURAL.LINK', tag: '03' },
    ],
  },
  {
    title: 'MAPS',
    items: [
      { view: 'map-perimeter', label: 'PERIMETER', tag: '04' },
      { view: 'map-dire-marsh', label: 'DIRE.MARSH', tag: '05' },
      { view: 'map-outpost', label: 'OUTPOST', tag: '06' },
      { view: 'map-cryo-archive', label: 'CRYO.ARCHIVE', tag: '07', disabled: true },
    ],
  },
  {
    title: 'LIVE',
    items: [
      { view: 'uplink' as View, label: 'UPLINK', tag: '08' },
      { view: 'live' as View, label: 'DETECT.EXE', tag: '09' },
    ],
  },
]

// Negative-space plus icon — four squares with a + gap between them
function UnviewedBadge() {
  return (
    <svg width="10" height="10" viewBox="0 0 10 10" className="ml-3 flex-shrink-0">
      <rect x="0" y="0" width="4" height="4" fill="currentColor" />
      <rect x="6" y="0" width="4" height="4" fill="currentColor" />
      <rect x="0" y="6" width="4" height="4" fill="currentColor" />
      <rect x="6" y="6" width="4" height="4" fill="currentColor" />
    </svg>
  )
}

// Map view names to actual map names in DB
const VIEW_TO_MAP: Record<string, string> = {
  'map-perimeter': 'Perimeter',
  'map-dire-marsh': 'Dire Marsh',
  'map-outpost': 'Outpost',
  'map-cryo-archive': 'Cryo Archive',
}

export default function Sidebar() {
  const { view, setView, stats, unviewedCount, refreshUnviewed, captureStatus } = useStore()
  const isProcessing = (captureStatus?.processing_items || []).some(i => i.status !== 'done')
  const [stagingCounts, setStagingCounts] = useState<Record<string, number>>({})

  useEffect(() => {
    refreshUnviewed()
    const interval = setInterval(() => { refreshUnviewed() }, 5000)
    return () => clearInterval(interval)
  }, [])

  // Fetch staging counts per map
  useEffect(() => {
    async function fetchStaging() {
      try {
        const { data } = await axios.get<SpawnHeatmap[]>(`${apiBase}/api/spawns/heatmap`)
        const counts: Record<string, number> = {}
        for (const map of data) {
          const uncharted = map.locations.filter((l: SpawnHeatmapEntry) =>
            l.location.startsWith('VCTR//') || l.location.startsWith('//VCTR.RDCT//')
          ).length
          if (uncharted > 0) {
            // Convert map name to view name
            const viewName = Object.entries(VIEW_TO_MAP).find(([, v]) => v === map.map)?.[0]
            if (viewName) counts[viewName] = uncharted
          }
        }
        setStagingCounts(counts)
      } catch (e) { console.error('[Sidebar] fetch staging counts failed:', e) }
    }
    fetchStaging()
    const interval = setInterval(fetchStaging, 10000)
    return () => clearInterval(interval)
  }, [])

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
                className={`w-full flex items-center gap-3 px-4 py-2 text-left transition-all ${
                  item.disabled
                    ? 'border-l-2 border-transparent cursor-not-allowed opacity-40'
                    : item.view === 'live' && isProcessing && view === item.view
                      ? 'animate-border-sweep bg-m-green-glow'
                      : item.view === 'live' && isProcessing
                        ? 'animate-border-sweep text-m-cyan/80 hover:text-m-cyan hover:bg-m-surface'
                        : view === item.view
                          ? 'border-l-2 border-m-green bg-m-green-glow text-m-green'
                          : 'border-l-2 border-transparent text-m-text-dim hover:text-m-text hover:bg-m-surface'
                }`}
              >
                <span className={`label-tag ${
                  item.disabled ? 'text-m-text-muted' : view === item.view ? 'text-m-green' : 'text-m-text-muted'
                }`}>
                  {item.tag}
                </span>
                <div className="flex-1 flex items-center">
                  <span className={`text-xs tracking-[0.1em] font-medium ${item.disabled ? 'line-through decoration-m-red/60' : ''}`}>
                    {item.label}
                  </span>
                  {item.view === 'history' && unviewedCount > 0 && (
                    <span className="text-m-cyan"><UnviewedBadge /></span>
                  )}
                  {stagingCounts[item.view] > 0 && (
                    <span className="text-m-cyan"><UnviewedBadge /></span>
                  )}
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
