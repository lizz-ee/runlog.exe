/**
 * Marathon map data.
 * Spawn points are stored as x%, y% coordinates on the cropped map image.
 *
 * Each zone has a name (matching the HUD text shown on spawn-in) and
 * approximate x,y% center coordinates on the map. This allows auto-capture
 * to read the HUD zone name and place the spawn marker without needing
 * the player to open the minimap.
 */

export interface SpawnRef {
  id: string          // unique spawn ID (e.g. "perimeter_south_relay_001")
  zone: string        // HUD zone name this spawn belongs to
  x: number           // precise % x on map image (0-100)
  y: number           // precise % y on map image (0-100)
  referenceImage: string  // filename in assets/spawns/<map>/
  description?: string    // visual landmarks for human reference
  dbId?: number
  gameCoords?: [number, number]  // game coordinates from loading screen
}

export interface Zone {
  name: string    // HUD display name (e.g. "SOUTH RELAY" → "South Relay")
  x: number       // approximate % x center of zone (0-100)
  y: number       // approximate % y center of zone (0-100)
}

export interface MapData {
  name: string
  image: string | null
  zones: Zone[]
  spawns: SpawnRef[]
}

export const MAPS: Record<string, MapData> = {
  'Perimeter': {
    name: 'Perimeter',
    image: 'perimeter',
    zones: [
      { name: 'Bluffs',       x: 40, y: 10 },
      { name: 'North Relay',  x: 42, y: 18 },
      { name: 'Station',      x: 68, y: 30 },
      { name: 'Hauler',       x: 30, y: 42 },
      { name: 'Data Wall',    x: 48, y: 43 },
      { name: 'Tunnels',      x: 58, y: 50 },
      { name: 'East Wall',    x: 72, y: 52 },
      { name: 'Ravine',       x: 50, y: 58 },
      { name: 'Overflow',     x: 35, y: 68 },
      { name: 'Columns',      x: 52, y: 70 },
      { name: 'South Relay',  x: 62, y: 64 },
    ],
    spawns: [
      {
        id: 'perimeter_south_relay_001',
        zone: 'South Relay',
        x: 56,
        y: 89,
        referenceImage: 'south_relay_001.jpg',
        description: 'Facing north, rocky cliffs on both sides, dead trees, open valley ahead',
      },
      {
        id: 'perimeter_bluffs_001',
        zone: 'Bluffs',
        x: 33,
        y: 8,
        referenceImage: 'bluffs_001.jpg',
        description: 'Misty canyon, tall rocky bluffs, dead trees, water/river below, structures in distance',
      },
    ],
  },
  'Dire Marsh': {
    name: 'Dire Marsh',
    image: 'dire-marsh',
    zones: [],
    spawns: [],
  },
  'Outpost': {
    name: 'Outpost',
    image: 'outpost',
    zones: [],
    spawns: [],
  },
  'Cryo Archive': {
    name: 'Cryo Archive',
    image: 'cryo-archive',
    zones: [],
    spawns: [],
  },
}

/** Lookup a zone by HUD name (case-insensitive) within a map */
export function findZone(mapName: string, hudZoneName: string): Zone | undefined {
  const map = MAPS[mapName]
  if (!map) return undefined
  const needle = hudZoneName.toLowerCase().trim()
  return map.zones.find(z => z.name.toLowerCase() === needle)
}

/** Get all known spawn references for a zone */
export function getSpawnsInZone(mapName: string, zoneName: string): SpawnRef[] {
  const map = MAPS[mapName]
  if (!map) return []
  const needle = zoneName.toLowerCase().trim()
  return map.spawns.filter(s => s.zone.toLowerCase() === needle)
}

export const MAP_LIST = [
  MAPS['Perimeter'],
  MAPS['Dire Marsh'],
  MAPS['Outpost'],
  MAPS['Cryo Archive'],
]
