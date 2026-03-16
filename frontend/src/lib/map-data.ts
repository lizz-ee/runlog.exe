/**
 * Marathon map data.
 * Spawn points are stored as x%, y% coordinates on the cropped map image.
 */

export interface MapData {
  name: string
  image: string | null
}

export const MAPS: Record<string, MapData> = {
  'Perimeter': {
    name: 'Perimeter',
    image: 'perimeter',
  },
  'Dire Marsh': {
    name: 'Dire Marsh',
    image: 'dire-marsh',
  },
  'Outpost': {
    name: 'Outpost',
    image: 'outpost',
  },
  'Cryo Archive': {
    name: 'Cryo Archive',
    image: null,
  },
}

export const MAP_LIST = [
  MAPS['Perimeter'],
  MAPS['Dire Marsh'],
  MAPS['Outpost'],
  MAPS['Cryo Archive'],
]
