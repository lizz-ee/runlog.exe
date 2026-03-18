import { useEffect } from 'react'
import { useStore } from './lib/store'
import { getRecentRuns, getOverviewStats, getRunners, getLoadouts } from './lib/api'
import { onScreenshotParsed } from './lib/electron'
import Sidebar from './components/Sidebar'
import Dashboard from './components/Dashboard'
import RunHistory from './components/RunHistory'
import Maps from './components/Maps'
import Live from './components/Live'
import RunReports from './components/RunReports'
import Shells from './components/Shells'
import Squad from './components/Squad'
import Settings from './components/Settings'
import Toasts from './components/Toasts'
import TitleBar from './components/TitleBar'

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
    <div className="flex flex-col h-screen bg-m-bg">
      <TitleBar />
      {/* scanlines overlay removed — too distracting */}
      <div className="flex flex-1 overflow-hidden">
      <Sidebar />
      <main className="flex-1 overflow-y-auto px-8 pt-5 pb-8">
        {view === 'dashboard' && <Dashboard />}
        {view === 'history' && <RunHistory />}
        {view === 'shells' && <Shells />}
        {view === 'squad' && <Squad />}
        {mapName && <Maps selectedMap={mapName} />}
        {view === 'live' && <Live />}
        {view === 'highlights' && <RunReports />}
        {view === 'settings' && <Settings />}
      </main>
      <Toasts />
      </div>
    </div>
  )
}
