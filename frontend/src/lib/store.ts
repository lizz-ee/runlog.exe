import { create } from 'zustand'
import { getRecentRuns, getOverviewStats, getUnviewedCount } from './api'
import type { View, Run, OverviewStats, Runner, Loadout, ParsedScreenshot, CaptureStatus } from './types'

export interface Toast {
  id: string
  title: string
  body: string
  type: 'success' | 'error' | 'info'
  timestamp: number
}

export interface PendingCapture {
  type: 'run' | 'spawn'
  data: any
  timestamp: number
}

interface AppState {
  view: View
  setView: (view: View) => void

  runs: Run[]
  setRuns: (runs: Run[]) => void
  addRun: (run: Run) => void

  stats: OverviewStats | null
  setStats: (stats: OverviewStats) => void

  runners: Runner[]
  setRunners: (runners: Runner[]) => void

  loadouts: Loadout[]
  setLoadouts: (loadouts: Loadout[]) => void

  isLoading: boolean
  setLoading: (loading: boolean) => void

  // Toasts
  toasts: Toast[]
  addToast: (toast: Omit<Toast, 'id' | 'timestamp'>) => void
  removeToast: (id: string) => void

  // Refresh runs + stats from backend (after a new run is processed)
  refreshData: () => Promise<void>

  // Unviewed runs
  unviewedCount: number
  setUnviewedCount: (count: number) => void
  refreshUnviewed: () => Promise<void>

  // Pending captures from hotkeys
  pendingCapture: PendingCapture | null
  setPendingCapture: (capture: PendingCapture | null) => void

  // Capture status (polled from backend, shared across all pages)
  captureStatus: CaptureStatus | null
  setCaptureStatus: (status: CaptureStatus | null) => void
  captureError: string | null
  setCaptureError: (error: string | null) => void

  // Cross-page navigation: auto-expand a specific run
  focusRunId: number | null
  setFocusRunId: (id: number | null) => void

  // UPLINK chat (persists across page navigation)
  uplinkMessages: { role: 'user' | 'assistant'; content: string }[]
  setUplinkMessages: (msgs: { role: 'user' | 'assistant'; content: string }[]) => void
  uplinkBriefing: string | null
  setUplinkBriefing: (text: string | null) => void
}

export const useStore = create<AppState>((set) => ({
  view: 'dashboard',
  setView: (view) => set({ view }),

  runs: [],
  setRuns: (runs) => set({ runs }),
  addRun: (run) => set((s) => ({ runs: [run, ...s.runs] })),

  stats: null,
  setStats: (stats) => set({ stats }),

  runners: [],
  setRunners: (runners) => set({ runners }),

  loadouts: [],
  setLoadouts: (loadouts) => set({ loadouts }),

  isLoading: false,
  setLoading: (isLoading) => set({ isLoading }),

  toasts: [],
  addToast: (toast) =>
    set((s) => ({
      toasts: [
        ...s.toasts,
        { ...toast, id: `${Date.now()}-${Math.random()}`, timestamp: Date.now() },
      ],
    })),
  removeToast: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),

  refreshData: async () => {
    try {
      const [runs, stats] = await Promise.all([
        getRecentRuns(20),
        getOverviewStats(),
      ])
      set({ runs, stats })
    } catch (e) {
      console.error('Failed to refresh data:', e)
    }
  },

  unviewedCount: 0,
  setUnviewedCount: (unviewedCount) => set({ unviewedCount }),
  refreshUnviewed: async () => {
    try {
      const count = await getUnviewedCount()
      set({ unviewedCount: count })
    } catch {}
  },

  pendingCapture: null,
  setPendingCapture: (pendingCapture) => set({ pendingCapture }),

  captureStatus: null,
  setCaptureStatus: (captureStatus) => set({ captureStatus }),
  captureError: null,
  setCaptureError: (captureError) => set({ captureError }),

  focusRunId: null,
  setFocusRunId: (focusRunId) => set({ focusRunId }),

  uplinkMessages: [],
  setUplinkMessages: (uplinkMessages) => set({ uplinkMessages }),
  uplinkBriefing: null,
  setUplinkBriefing: (uplinkBriefing) => set({ uplinkBriefing }),
}))
