import { useEffect } from 'react'
import { useStore } from './lib/store'
import { getRecentRuns, getOverviewStats, getRunners, getLoadouts } from './lib/api'
import { onScreenshotParsed } from './lib/electron'
import Sidebar from './components/Sidebar'
import Dashboard from './components/Dashboard'
import RunHistory from './components/RunHistory'
import Maps from './components/Maps'
import Toasts from './components/Toasts'

const MAP_VIEW_TO_NAME: Record<string, string> = {
  'map-perimeter': 'Perimeter',
  'map-dire-marsh': 'Dire Marsh',
  'map-outpost': 'Outpost',
  'map-cryo-archive': 'Cryo Archive',
}

export default function App() {
  const { view, setRuns, setStats, setRunners, setLoadouts, addToast, setPendingCapture } = useStore()

  useEffect(() => {
    async function load() {
      try {
        const [runs, stats, runners, loadouts] = await Promise.all([
          getRecentRuns(20),
          getOverviewStats(),
          getRunners(),
          getLoadouts(),
        ])
        setRuns(runs)
        setStats(stats)
        setRunners(runners)
        setLoadouts(loadouts)
      } catch (e) {
        console.error('Failed to load data:', e)
      }
    }
    load()
  }, [])

  useEffect(() => {
    onScreenshotParsed((event) => {
      setPendingCapture(event)
      if (event.type === 'run') {
        const d = event.data
        const status = d.survived ? 'EXTRACTED' : 'KIA'
        const kills = (d.combatant_eliminations || 0) + (d.runner_eliminations || 0)
        addToast({
          type: d.survived ? 'success' : 'error',
          title: `RUN CAPTURED — ${status}`,
          body: `${kills} KILLS | $${d.loot_value_total || 0} LOOT | ${d.map_name || 'UNKNOWN'}`,
        })
      } else if (event.type === 'spawn') {
        const d = event.data
        addToast({
          type: 'info',
          title: 'SPAWN LOGGED',
          body: `${d.map_name || 'UNKNOWN'} — ${d.spawn_location || d.spawn_region || 'UNKNOWN'}`,
        })
      }
    })
  }, [])

  const mapName = MAP_VIEW_TO_NAME[view]

  return (
    <div className="flex h-screen bg-m-bg">
      <div className="fixed inset-0 scanlines z-50 pointer-events-none" />
      <Sidebar />
      <main className="flex-1 overflow-y-auto p-8">
        {view === 'dashboard' && <Dashboard />}
        {view === 'history' && <RunHistory />}
        {mapName && <Maps selectedMap={mapName} />}
        {view === 'live' && (
          <div className="max-w-7xl mx-auto space-y-6">
            <div>
              <p className="label-tag text-m-green">CAPTURE / LIVE</p>
              <h2 className="text-xl font-display font-black tracking-wider text-m-text mt-1">
                AUTO-CAPTURE
              </h2>
            </div>
            <div className="border border-1 border-m-border bg-m-card p-10 text-center">
              <p className="text-m-text-muted text-sm">AUTO-CAPTURE COMING SOON</p>
              <p className="label-tag text-m-text-muted mt-2">
                REQUIRES ELECTRON APP MODE
              </p>
            </div>
          </div>
        )}
      </main>
      <Toasts />
    </div>
  )
}
