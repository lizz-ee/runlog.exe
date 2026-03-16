import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { getSpawnHeatmap, getMapStats } from '../lib/api'
import { MAPS, MAP_LIST } from '../lib/map-data'
import type { SpawnHeatmap, MapStats } from '../lib/types'

import mapDireMarsh from '../assets/map-dire-marsh.png'
import mapPerimeter from '../assets/map-perimeter.png'
import mapOutpost from '../assets/map-outpost.png'

const MAP_IMAGES: Record<string, string> = {
  'dire-marsh': mapDireMarsh,
  'perimeter': mapPerimeter,
  'outpost': mapOutpost,
}

export default function Maps({ selectedMap }: { selectedMap: string }) {
  const [heatmap, setHeatmap] = useState<SpawnHeatmap[]>([])
  const [mapStats, setMapStats] = useState<MapStats[]>([])
  const [hoveredSpawn, setHoveredSpawn] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([getSpawnHeatmap(), getMapStats()]).then(([h, s]) => {
      setHeatmap(h)
      setMapStats(s)
    })
  }, [])

  const mapData = MAPS[selectedMap]
  const currentHeatmap = heatmap.find((h) => h.map === selectedMap)
  const currentStats = mapStats.find((s) => s.map === selectedMap)
  const mapImage = mapData?.image ? MAP_IMAGES[mapData.image] : null

  return (
    <div className="max-w-7xl mx-auto">
      {/* Map + sidebar */}
      <div className="grid grid-cols-[1fr_220px] gap-[1px] bg-m-border">
        {/* Map — maintain 16:9 aspect ratio to match the screenshot */}
        <div className="bg-m-black relative overflow-hidden w-full" style={{ aspectRatio: '1.414' }}>
          {mapImage ? (
            <img
              src={mapImage}
              alt={selectedMap}
              className="absolute inset-0 w-full h-full opacity-80"
              draggable={false}
            />
          ) : (
            <div className="absolute inset-0 flex items-center justify-center">
              <p className="label-tag text-m-text-muted">NO MAP IMAGE</p>
            </div>
          )}

          {/* Spawn point markers */}
          {currentHeatmap?.locations.map((loc) => {
            if (loc.x == null || loc.y == null) return null
            const isHovered = hoveredSpawn === loc.location
            return (
              <div
                key={loc.location}
                className="absolute transform -translate-x-1/2 -translate-y-1/2 cursor-pointer"
                style={{ left: `${loc.x}%`, top: `${loc.y}%` }}
                onMouseEnter={() => setHoveredSpawn(loc.location)}
                onMouseLeave={() => setHoveredSpawn(null)}
              >
                {/* Outer pulse ring */}
                <motion.div
                  className="absolute rounded-full border border-m-green/30"
                  style={{ width: 28, height: 28, left: -14, top: -14 }}
                  animate={{ opacity: [0.3, 0.6, 0.3], scale: [1, 1.2, 1] }}
                  transition={{ duration: 2.5, repeat: Infinity }}
                />

                {/* Spawn circle */}
                <div className={`relative w-4 h-4 -ml-2 -mt-2 rounded-full border-2 border-m-green flex items-center justify-center transition-all ${
                  isHovered ? 'bg-m-green/40 scale-125' : 'bg-m-green/15'
                }`}>
                  <span className="text-[7px] font-mono font-bold text-m-green">{loc.count}</span>
                </div>

                {/* Hover tooltip */}
                {isHovered && (
                  <motion.div
                    initial={{ opacity: 0, y: 5 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="absolute bottom-full left-1/2 -translate-x-1/2 mb-4 bg-m-black/95 border border-1 border-m-green/40 px-4 py-3 min-w-[150px] z-20"
                  >
                    <p className="text-[10px] tracking-[0.15em] text-m-green font-bold uppercase">
                      {loc.location}
                    </p>
                    {loc.region && (
                      <p className="text-[9px] text-m-text-muted mt-0.5">{loc.region}</p>
                    )}
                    <div className="mt-2 space-y-1">
                      <TooltipRow label="SPAWNS" value={String(loc.count)} />
                      {(loc.runs_survived + loc.runs_died > 0) && (
                        <>
                          <TooltipRow label="SURVIVED" value={String(loc.runs_survived)} color="green" />
                          <TooltipRow label="DIED" value={String(loc.runs_died)} color="red" />
                          {loc.survival_rate !== null && (
                            <div className="border-t border-m-border pt-1 mt-1">
                              <TooltipRow
                                label="SURV%"
                                value={`${loc.survival_rate}%`}
                                color={loc.survival_rate >= 50 ? 'green' : 'red'}
                              />
                            </div>
                          )}
                        </>
                      )}
                    </div>
                  </motion.div>
                )}
              </div>
            )
          })}
        </div>

        {/* Sidebar */}
        <div className="bg-m-card flex flex-col">
          <div className="p-4 border-b border-m-border border-l-2 border-l-m-green">
            <p className="text-xs font-bold tracking-[0.15em] text-m-green uppercase">{selectedMap}</p>
          </div>

          {/* Map stats */}
          {currentStats ? (
            <div className="p-4 border-b border-m-border space-y-2">
              <StatRow label="RUNS" value={String(currentStats.runs)} />
              <StatRow label="SURVIVAL" value={`${currentStats.survival_rate}%`}
                color={currentStats.survival_rate >= 50 ? 'green' : 'red'} />
              <StatRow label="K/D" value={String(currentStats.kd)}
                color={currentStats.kd >= 1 ? 'green' : 'red'} />
              <StatRow label="LOOT" value={`$${currentStats.loot.toLocaleString()}`} color="yellow" />
            </div>
          ) : (
            <div className="p-4 border-b border-m-border">
              <p className="text-2xs text-m-text-muted">NO RUN DATA</p>
            </div>
          )}

          {/* Spawn points list */}
          <div className="p-4 flex-1 overflow-y-auto">
            <p className="label-tag text-m-text-muted mb-3">SPAWN POINTS</p>
            {currentHeatmap && currentHeatmap.locations.length > 0 ? (
              <div className="space-y-2">
                {currentHeatmap.locations.map((loc) => (
                  <div
                    key={loc.location}
                    className={`flex items-center gap-2 cursor-pointer transition-colors ${
                      hoveredSpawn === loc.location ? 'text-m-green' : ''
                    }`}
                    onMouseEnter={() => setHoveredSpawn(loc.location)}
                    onMouseLeave={() => setHoveredSpawn(null)}
                  >
                    <div className="w-2 h-2 rounded-full bg-m-green/60 border border-m-green" />
                    <span className="text-2xs text-m-text uppercase tracking-wider flex-1">{loc.location}</span>
                    <span className="text-2xs font-mono text-m-green">{loc.count}x</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-2xs text-m-text-muted">NO SPAWNS RECORDED</p>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function StatRow({ label, value, color }: { label: string; value: string; color?: 'green' | 'red' | 'yellow' }) {
  const c = color === 'green' ? 'text-m-green' : color === 'red' ? 'text-m-red' : color === 'yellow' ? 'text-m-yellow' : 'text-m-text'
  return (
    <div className="flex justify-between">
      <span className="label-tag text-m-text-muted">{label}</span>
      <span className={`text-2xs font-mono ${c}`}>{value}</span>
    </div>
  )
}

function TooltipRow({ label, value, color }: { label: string; value: string; color?: 'green' | 'red' }) {
  const c = color === 'green' ? 'text-m-green' : color === 'red' ? 'text-m-red' : 'text-m-text'
  return (
    <div className="flex justify-between">
      <span className="text-[9px] text-m-text-muted">{label}</span>
      <span className={`text-[9px] font-mono ${c}`}>{value}</span>
    </div>
  )
}
