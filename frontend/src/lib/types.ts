export interface Runner {
  id: number
  name: string
  icon: string | null
  notes: string | null
  created_at: string
}

export interface Weapon {
  id: number
  name: string
  weapon_type: string | null
  notes: string | null
  created_at: string
}

export interface Loadout {
  id: number
  name: string
  runner_id: number | null
  primary_weapon: string | null
  secondary_weapon: string | null
  mods: string[] | null
  gear: string[] | null
  notes: string | null
  screenshot_path: string | null
  created_at: string
}

export interface Run {
  id: number
  runner_id: number | null
  loadout_id: number | null
  map_name: string | null
  date: string
  survived: boolean | null
  kills: number
  combatant_eliminations: number
  runner_eliminations: number
  deaths: number
  assists: number
  crew_revives: number
  loot_extracted: LootItem[] | null
  loot_value_total: number
  duration_seconds: number | null
  squad_size: number | null
  squad_members: string[] | null
  screenshot_path: string | null
  notes: string | null
  session_id: number | null
  primary_weapon: string | null
  secondary_weapon: string | null
  killed_by: string | null
  killed_by_damage: number | null
  killed_by_weapon: string | null
  damage_contributors: { name: string; damage: number; finished: boolean }[] | null
  starting_loadout_value: number | null
  player_level: number | null
  vault_value: number | null
  grade: string | null
  summary: string | null
  spawn_location: string | null
  shell_name: string | null
  player_gamertag: string | null
  recording_path: string | null
  viewed: boolean | null
  is_favorite: boolean | null
  is_ranked: boolean | null
  created_at: string
}

export interface PaginatedRuns {
  items: Run[]
  total: number
  maps: string[]
}

export interface LootItem {
  name: string
  value: number
}

export interface Session {
  id: number
  started_at: string
  ended_at: string | null
  notes: string | null
  runs: Run[]
}

export interface ParsedScreenshot {
  survived: boolean | null
  kills: number
  combatant_eliminations: number
  runner_eliminations: number
  deaths: number
  assists: number
  map_name: string | null
  duration_seconds: number | null
  loot_extracted: LootItem[] | null
  loot_value_total: number
  runner_name: string | null
  primary_weapon: string | null
  secondary_weapon: string | null
  items_collected: number | null
  items_auto_vaulted: number | null
  bullet_balance: number | null
  raw_text: string | null
  confidence: string | null
}

export interface MapTime {
  map_name: string
  total_seconds: number
}

export interface OverviewStats {
  total_runs: number
  total_survived: number
  survival_rate: number
  total_kills: number
  total_deaths: number
  total_assists: number
  total_revives: number
  kd_ratio: number
  total_loot_value: number
  avg_kills_per_run: number
  avg_loot_per_run: number
  favorite_map: string | null
  favorite_runner: string | null
  favorite_shell: string | null
  favorite_weapon: string | null
  favorite_squad_mate: string | null
  favorite_squad_mate_runs: number
  total_time_seconds: number
  time_by_map: MapTime[]
}

export interface MapStats {
  map: string
  runs: number
  survived: number
  kills: number
  pve_kills: number
  pvp_kills: number
  deaths: number
  loot: number
  time: number
  survival_rate: number
  kd: number
  avg_loot: number
  avg_time: number
}

export interface TrendData {
  date: string
  runs: number
  survived: number
  kills: number
  deaths: number
  loot: number
}

export interface SpawnPoint {
  id: number
  run_id: number | null
  map_name: string
  spawn_location: string | null
  screenshot_path: string | null
  notes: string | null
  created_at: string
}

export interface SpawnHeatmapEntry {
  location: string
  region: string | null
  x: number | null
  y: number | null
  count: number
  runs_survived: number
  runs_died: number
  survival_rate: number | null
  total_loot: number
  total_time: number
  total_kills: number
  avg_loot: number | null
  avg_time: number | null
}

export interface SpawnHeatmap {
  map: string
  total_spawns: number
  locations: SpawnHeatmapEntry[]
}

export interface CaptureStatus {
  active: boolean
  recording: boolean
  recording_seconds: number
  recording_path: string | null
  queue_size: number
  processing_phase: string | null
  processing_items: ProcessingItem[]
  status_counts: Record<string, number>
  resumed_count: number
  capture_mode: string | null
  has_frame: boolean
  window_found: boolean
  last_detection: string | null
  detection_count: number
  last_result: ProcessResult | null
}

export interface ProcessingItem {
  file: string
  status: string
  run_id: number | null
  duration_seconds: number | null
  created_at: string | null
  thumbnail: string | null
  detail: string | null
  phase_started_at: string | null
  p1_started_at?: string | null
  p1_ended_at?: string | null
  p2_started_at?: string | null
  p2_ended_at?: string | null
  file_size_mb?: number | null
  p1_failed?: boolean
  p2_failed?: boolean
  loading_screen_found?: boolean
  stats_tab_found?: boolean
  loadout_tab_found?: boolean
}

export interface ProcessResult {
  status: string
  recording: string
  analysis: RunAnalysis | null
  clips: string[]
  run_id: number | null
}

export interface RunAnalysis {
  map_name: string | null
  survived: boolean | null
  kills: number
  combatant_eliminations: number
  runner_eliminations: number
  deaths: number
  crew_revives: number
  duration_seconds: number | null
  loot_value_total: number
  primary_weapon: string | null
  secondary_weapon: string | null
  killed_by: string | null
  grade: string | null
  highlights: Highlight[]
  summary: string | null
}

export interface Highlight {
  timestamp_seconds: number
  duration_seconds: number
  type: string
  description: string
}

export interface Clip {
  filename: string
  size_mb: number
  type: string
  run_timestamp: string | null
  run_folder: string | null
  created: number
  thumbnail: string | null
  sprite: string | null
  sprite_cols: number | null
  sprite_rows: number | null
  sprite_frames: number | null
}

export interface ShellStats {
  runner_id: number
  runner_name: string
  runs: number
  survived: number
  kills: number
  pve_kills: number
  pvp_kills: number
  deaths: number
  revives: number
  loot: number
  time: number
  survival_rate: number
  kd: number
  avg_loot: number
  avg_time: number
  favorite_weapon: string | null
  score: number
}

export type View = 'dashboard' | 'history' | 'shells' | 'squad' | 'map-perimeter' | 'map-dire-marsh' | 'map-outpost' | 'map-cryo-archive' | 'live' | 'uplink' | 'settings'
