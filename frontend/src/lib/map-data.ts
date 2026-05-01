/**
 * Marathon map data.
 * Spawn points are stored as x%, y% coordinates on the cropped map image
 * and are user-placed via drag-and-drop in the Maps view.
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

export interface MapData {
  name: string
  image: string | null
  spawns: SpawnRef[]
}

export const MAPS: Record<string, MapData> = {
  'Perimeter': {
    name: 'Perimeter',
    image: 'perimeter',
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
    spawns: [],
  },
  'Outpost': {
    name: 'Outpost',
    image: 'outpost',
    spawns: [],
  },
  'Cryo Archive': {
    name: 'Cryo Archive',
    image: 'cryo-archive',
    zones: [],
    spawns: [],
  },
}
