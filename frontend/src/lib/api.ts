import axios from 'axios'
import { getApiBaseUrl } from './electron'
import type {
  Run, Runner, Loadout, Weapon, ParsedScreenshot,
  OverviewStats, MapStats, TrendData, Session, SpawnHeatmap,
} from './types'

const apiBase = getApiBaseUrl()
const api = axios.create({ baseURL: `${apiBase}/api` })

export { apiBase }

// Screenshot
export async function parseScreenshots(files: File[]): Promise<ParsedScreenshot> {
  const form = new FormData()
  for (const file of files) {
    form.append('files', file)
  }
  const { data } = await api.post<ParsedScreenshot>('/screenshot/parse', form)
  return data
}

// Runs
export async function getRuns(params?: Record<string, any>): Promise<Run[]> {
  const { data } = await api.get<Run[]>('/runs', { params })
  return data
}

export async function getRecentRuns(limit = 10): Promise<Run[]> {
  const { data } = await api.get<Run[]>('/runs/recent', { params: { limit } })
  return data
}

export async function createRun(run: Partial<Run>): Promise<Run> {
  const { data } = await api.post<Run>('/runs', run)
  return data
}

export async function updateRun(id: number, run: Partial<Run>): Promise<Run> {
  const { data } = await api.put<Run>(`/runs/${id}`, run)
  return data
}

export async function deleteRun(id: number): Promise<void> {
  await api.delete(`/runs/${id}`)
}

// Runners
export async function getRunners(): Promise<Runner[]> {
  const { data } = await api.get<Runner[]>('/runners')
  return data
}

export async function createRunner(runner: Partial<Runner>): Promise<Runner> {
  const { data } = await api.post<Runner>('/runners', runner)
  return data
}

// Loadouts
export async function getLoadouts(): Promise<Loadout[]> {
  const { data } = await api.get<Loadout[]>('/loadouts')
  return data
}

export async function createLoadout(loadout: Partial<Loadout>): Promise<Loadout> {
  const { data } = await api.post<Loadout>('/loadouts', loadout)
  return data
}

// Weapons
export async function getWeapons(): Promise<Weapon[]> {
  const { data } = await api.get<Weapon[]>('/weapons')
  return data
}

// Stats
export async function getOverviewStats(): Promise<OverviewStats> {
  const { data } = await api.get<OverviewStats>('/stats/overview')
  return data
}

export async function getMapStats(): Promise<MapStats[]> {
  const { data } = await api.get<MapStats[]>('/stats/by-map')
  return data
}

export async function getTrends(): Promise<TrendData[]> {
  const { data } = await api.get<TrendData[]>('/stats/trends')
  return data
}

// Spawns
export async function getSpawnHeatmap(): Promise<SpawnHeatmap[]> {
  const { data } = await api.get<SpawnHeatmap[]>('/spawns/heatmap')
  return data
}

// Sessions
export async function getSessions(): Promise<Session[]> {
  const { data } = await api.get<Session[]>('/sessions')
  return data
}

export async function createSession(notes?: string): Promise<Session> {
  const { data } = await api.post<Session>('/sessions', { notes })
  return data
}
