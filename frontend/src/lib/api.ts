import axios from 'axios'
import { getApiBaseUrl } from './electron'
import type {
  Run, PaginatedRuns, Runner, Loadout, Weapon, ShellStats,
  OverviewStats, MapStats, TrendData, Session, SpawnHeatmap,
  CaptureStatus, Clip,
} from './types'

const apiBase = getApiBaseUrl()
const api = axios.create({ baseURL: `${apiBase}/api` })

export { apiBase }

// Runs
export async function getRuns(params?: Record<string, any>): Promise<PaginatedRuns> {
  const { data } = await api.get<PaginatedRuns>('/runs', { params })
  return data
}

export async function getVaultValues(): Promise<{ value: number }[]> {
  const { data } = await api.get<{ value: number }[]>('/runs/vault-values')
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

export async function getUnviewedCount(): Promise<number> {
  const { data } = await api.get('/runs/unviewed/count')
  return data.count
}

export async function markRunViewed(id: number): Promise<void> {
  await api.post(`/runs/${id}/viewed`)
}

export async function markAllRunsViewed(): Promise<void> {
  await api.post('/runs/viewed/all')
}

export async function toggleFavorite(id: number): Promise<{ is_favorite: boolean }> {
  const { data } = await api.post(`/runs/${id}/favorite`)
  return data
}

export async function cutClip(source: string, inPoint: number, outPoint: number, name: string): Promise<{ status: string; filename: string; duration: number }> {
  const { data } = await api.post('/capture/clip/cut', { source, in_point: inPoint, out_point: outPoint, name })
  return data
}

// Settings
export interface AppSettings {
  has_api_key: boolean
  api_key_masked: string
  api_key_source: string
  cli_available: boolean
  encoder: string
  bitrate: number
  fps: number
  p1_workers: number
  p2_workers: number
  auth_mode: string
  model: string
  uplink_model?: string
}

export async function getSettings(): Promise<AppSettings> {
  const { data } = await api.get('/settings')
  return data
}

export async function setApiKey(apiKey: string): Promise<void> {
  await api.post('/settings/api-key', { api_key: apiKey })
}

export async function testApiKey(apiKey: string): Promise<{ status: string; response: string }> {
  const { data } = await api.post('/settings/api-key/test', { api_key: apiKey })
  return data
}

export async function removeApiKey(): Promise<void> {
  await api.delete('/settings/api-key')
}

export async function updateConfig(key: string, value: string | number | boolean): Promise<void> {
  await api.post('/settings/config', { key, value })
}

export async function getCliStatus(): Promise<{ installed: boolean; authenticated: boolean; path: string | null }> {
  const { data } = await api.get('/settings/cli-status')
  return data
}

// Squad
export async function getSquadStats(limit = 7): Promise<any[]> {
  const { data } = await api.get('/squad/stats', { params: { limit } })
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

export async function deleteClip(filename: string): Promise<void> {
  await api.post('/capture/clip/delete', { filename })
}

export async function deleteKeptRecording(runId: number): Promise<void> {
  await api.post('/capture/recording/delete-kept', { run_id: runId })
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
