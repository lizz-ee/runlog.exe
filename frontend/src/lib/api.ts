import axios from 'axios'
import { getApiBaseUrl } from './electron'
import type {
  Run, Runner, Loadout, Weapon, ShellStats,
  OverviewStats, MapStats, TrendData, Session, SpawnHeatmap,
  CaptureStatus, Clip,
} from './types'

const apiBase = getApiBaseUrl()
const api = axios.create({ baseURL: `${apiBase}/api` })

export { apiBase }

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

export async function getShellStats(): Promise<ShellStats[]> {
  const { data } = await api.get<ShellStats[]>('/stats/by-runner')
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

// Capture
export async function getCaptureStatus(): Promise<CaptureStatus> {
  const { data } = await api.get<CaptureStatus>('/capture/status')
  return data
}

export async function getClips(): Promise<Clip[]> {
  const { data } = await api.get<{ clips: Clip[] }>('/capture/clips')
  return data.clips
}

export function getClipUrl(filename: string): string {
  return `${apiBase}/api/capture/clips/${filename}`
}

export function getFrameUrl(): string {
  return `${apiBase}/api/capture/frame`
}

export function getThumbnailUrl(filename: string): string {
  return `${apiBase}/api/capture/thumbnail/${filename}`
}
