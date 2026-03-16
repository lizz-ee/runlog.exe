import { useEffect, useState, useRef, useCallback } from 'react'
import { motion } from 'framer-motion'
import { getMapStats, getSpawnHeatmap } from '../lib/api'
import { MAPS, MAP_LIST } from '../lib/map-data'
import type { SpawnRef } from '../lib/map-data'
import type { MapStats, SpawnHeatmap } from '../lib/types'
import axios from 'axios'

import mapDireMarsh from '../assets/map-dire-marsh.png'
import mapPerimeter from '../assets/map-perimeter.png'
import mapOutpost from '../assets/map-outpost.png'

const MAP_IMAGES: Record<string, string> = {
  'dire-marsh': mapDireMarsh,
  'perimeter': mapPerimeter,
  'outpost': mapOutpost,
}

interface DragState {
  spawnId: string
  startMouseX: number
  startMouseY: number
  startX: number
  startY: number
}

function formatTime(seconds: number): string {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (h > 0) return `${h}h ${m}m`
  return `${m}m`
}

export default function Maps({ selectedMap }: { selectedMap: string }) {
  const [mapStats, setMapStats] = useState<MapStats[]>([])
  const [heatmap, setHeatmap] = useState<SpawnHeatmap[]>([])
  const [hoveredSpawn, setHoveredSpawn] = useState<string | null>(null)
  const [spawns, setSpawns] = useState<SpawnRef[]>([])
  const [dragState, setDragState] = useState<DragState | null>(null)
  const [dirty, setDirty] = useState<Set<string>>(new Set())
  const [saving, setSaving] = useState(false)
  const mapRef = useRef<HTMLDivElement>(null)

  const mapData = MAPS[selectedMap]
  const currentStats = mapStats.find((s) => s.map === selectedMap)
  const currentHeatmap = heatmap.find((h) => h.map === selectedMap)
  const mapImage = mapData?.image ? MAP_IMAGES[mapData.image] : null

  // Load spawns: try DB first, fall back to map-data.ts
  useEffect(() => {
    const md = MAPS[selectedMap]
    const fallback = md ? md.spawns.map(s => ({ ...s })) : []

    axios.get('/api/spawns', { params: { map_name: selectedMap } })
      .then(({ data }) => {
        if (data.length > 0) {
          // Build SpawnRef objects from DB records
          const dbSpawns: SpawnRef[] = data.map((s: any) => ({
            id: `${selectedMap.toLowerCase().replace(/\s/g, '_')}_${(s.spawn_location || 'unknown').toLowerCase().replace(/\s/g, '_')}_${s.id}`,
            zone: s.spawn_location || 'Unknown',
            x: s.x ?? 50,
            y: s.y ?? 50,
            referenceImage: '',
            description: s.notes || '',
            dbId: s.id,
          }))
          setSpawns(dbSpawns)
        } else {
          setSpawns(fallback)
        }
      })
      .catch(() => setSpawns(fallback))

    setDirty(new Set())
  }, [selectedMap])

  useEffect(() => {
    getMapStats().then(setMapStats)
    getSpawnHeatmap().then(setHeatmap)
  }, [selectedMap])

  const toPercent = useCallback((clientX: number, clientY: number) => {
    if (!mapRef.current) return { x: 0, y: 0 }
    const rect = mapRef.current.getBoundingClientRect()
    const x = Math.max(0, Math.min(100, ((clientX - rect.left) / rect.width) * 100))
    const y = Math.max(0, Math.min(100, ((clientY - rect.top) / rect.height) * 100))
    return { x: Math.round(x * 10) / 10, y: Math.round(y * 10) / 10 }
  }, [])

  const onMouseDown = useCallback((e: React.MouseEvent, spawn: SpawnRef) => {
    e.preventDefault()
    setDragState({
      spawnId: spawn.id,
      startMouseX: e.clientX,
      startMouseY: e.clientY,
      startX: spawn.x,
      startY: spawn.y,
    })
  }, [])

  const onMouseMove = useCallback((e: React.MouseEvent) => {
    if (!dragState || !mapRef.current) return
    const { x, y } = toPercent(e.clientX, e.clientY)
    setSpawns(prev => prev.map(s =>
      s.id === dragState.spawnId ? { ...s, x, y } : s
    ))
    setDirty(prev => new Set(prev).add(dragState.spawnId))
  }, [dragState, toPercent])

  const onMouseUp = useCallback(() => {
    setDragState(null)
  }, [])

  const saveToDb = async () => {
    setSaving(true)
    try {
      for (const spawn of spawns) {
        if (!dirty.has(spawn.id)) continue
        // Update DB via API
        await axios.put(`/api/spawns/update-coords`, {
          map_name: selectedMap,
          spawn_location: spawn.zone,
          x: spawn.x,
          y: spawn.y,
        })
      }
      setDirty(new Set())
    } catch (err) {
      console.error('Failed to save:', err)
    }
    setSaving(false)
  }

  return (
    <div className="max-w-7xl mx-auto">
      <div className="grid grid-cols-[1fr_220px] gap-[1px] bg-m-border">
        {/* Map with draggable dots */}
        <div
          ref={mapRef}
          className="bg-m-black relative w-full select-none"
          style={{ aspectRatio: '1.414', cursor: dragState ? 'grabbing' : 'default' }}
          onMouseMove={onMouseMove}
          onMouseUp={onMouseUp}
          onMouseLeave={onMouseUp}
        >
          {mapImage ? (
            <img
              src={mapImage}
              alt={selectedMap}
              className="absolute inset-0 w-full h-full opacity-80 pointer-events-none"
              draggable={false}
            />
          ) : (
            <div className="absolute inset-0 flex items-center justify-center">
              <p className="label-tag text-m-text-muted">NO MAP IMAGE</p>
            </div>
          )}

          {/* Spawn point markers — draggable */}
          {spawns.map((spawn) => {
            const isHovered = hoveredSpawn === spawn.id
            const isDragging = dragState?.spawnId === spawn.id
            const isDirty = dirty.has(spawn.id)
            return (
              <div
                key={spawn.id}
                className="absolute transform -translate-x-1/2 -translate-y-1/2"
                style={{
                  left: `${spawn.x}%`,
                  top: `${spawn.y}%`,
                  cursor: isDragging ? 'grabbing' : 'grab',
                  zIndex: isDragging ? 50 : isHovered ? 40 : 10,
                }}
                onMouseDown={(e) => onMouseDown(e, spawn)}
                onMouseEnter={() => !dragState && setHoveredSpawn(spawn.id)}
                onMouseLeave={() => !dragState && setHoveredSpawn(null)}
              >
                {/* Outer pulse ring */}
                <motion.div
                  className={`absolute rounded-full border ${isDirty ? 'border-m-yellow/50' : 'border-m-green/30'}`}
                  style={{ width: 28, height: 28, left: -14, top: -14 }}
                  animate={{ opacity: [0.3, 0.6, 0.3], scale: [1, 1.2, 1] }}
                  transition={{ duration: 2.5, repeat: Infinity }}
                />

                {/* Spawn circle */}
                <div className={`relative w-4 h-4 -ml-2 -mt-2 rounded-full border-2 flex items-center justify-center transition-all ${
                  isDirty
                    ? 'border-m-yellow bg-m-yellow/30'
                    : 'border-m-green bg-m-green/15'
                } ${isHovered || isDragging ? 'scale-150' : ''}`}>
                  <div className={`w-1.5 h-1.5 rounded-full ${isDirty ? 'bg-m-yellow' : 'bg-m-green'}`} />
                </div>

                {/* Spawn tooltip — stats or drag coords */}
                {(isHovered || isDragging) && (() => {
                  const loc = currentHeatmap?.locations.find(l => l.location === spawn.zone)
                  const totalRuns = loc ? loc.runs_survived + loc.runs_died : 0
                  const survRate = totalRuns > 0 ? Math.round(loc!.runs_survived / totalRuns * 100) : null
                  return (
                    <div className="absolute top-full left-1/2 -translate-x-1/2 mt-3 bg-m-black/95 border border-m-green/40 px-3 py-2 min-w-[140px] z-[100] pointer-events-none">
                      <p className="text-[10px] tracking-[0.15em] text-m-green font-bold uppercase">
                        {spawn.zone}
                      </p>
                      {isDragging && (
                        <p className="text-[10px] font-mono text-m-yellow mt-1">
                          x: {spawn.x} &nbsp; y: {spawn.y}
                        </p>
                      )}
                      {!isDragging && loc && totalRuns > 0 && (
                        <div className="mt-1.5 space-y-0.5">
                          <TooltipStat label="SPAWNS" value={`${loc.count}x`} />
                          <TooltipStat label="SURVIVAL" value={`${survRate}%`} color={survRate! >= 50 ? 'green' : 'red'} />
                          <TooltipStat label="AVG LOOT" value={`$${Math.round(loc.avg_loot ?? 0).toLocaleString()}`} color="yellow" />
                          <TooltipStat label="AVG TIME" value={loc.avg_time ? formatTime(loc.avg_time) : '—'} color="cyan" />
                          <div className="border-t border-m-border/30 my-1 pt-1" />
                          <TooltipStat label="PVE KILLS" value={String((loc as any).pve_kills ?? 0)} color={(loc as any).pve_kills ? 'green' : undefined} />
                          <TooltipStat label="RUNNER KILLS" value={String((loc as any).runner_kills ?? 0)} color={(loc as any).runner_kills ? 'cyan' : undefined} />
                          <TooltipStat label="DEATHS" value={String((loc as any).total_deaths ?? 0)} color={(loc as any).total_deaths ? 'red' : undefined} />
                          <TooltipStat label="REVIVES" value={String((loc as any).total_revives ?? 0)} color={(loc as any).total_revives ? 'green' : undefined} />
                        </div>
                      )}
                      {!isDragging && (!loc || totalRuns === 0) && (
                        <p className="text-[9px] text-m-text-muted mt-1">NO RUN DATA</p>
                      )}
                      {isDirty && (
                        <p className="text-[8px] text-m-yellow mt-1 uppercase tracking-wider">unsaved</p>
                      )}
                    </div>
                  )
                })()}
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
              <StatRow label="PVE KILLS" value={String(currentStats.pve_kills)} color="green" />
              <StatRow label="RUNNER KILLS" value={String(currentStats.pvp_kills)} color="cyan" />
              <StatRow label="TOTAL LOOT" value={`$${currentStats.loot.toLocaleString()}`} color="yellow" />
              <StatRow label="AVG LOOT" value={`$${currentStats.avg_loot.toLocaleString()}`} color="yellow" />
              <StatRow label="TOTAL TIME" value={formatTime(currentStats.time)} color="cyan" />
              <StatRow label="AVG TIME" value={formatTime(currentStats.avg_time)} color="cyan" />
            </div>
          ) : (
            <div className="p-4 border-b border-m-border">
              <p className="text-2xs text-m-text-muted">NO RUN DATA</p>
            </div>
          )}

          {/* Spawn points list with per-spawn stats */}
          <div className="p-4 flex-1 overflow-y-auto">
            <p className="label-tag text-m-text-muted mb-3">SPAWN POINTS</p>
            {currentHeatmap && currentHeatmap.locations.length > 0 ? (
              <div className="space-y-1">
                {currentHeatmap.locations.map((loc) => {
                  const spawnMatch = spawns.find(s => s.zone === loc.location)
                  const totalRuns = loc.runs_survived + loc.runs_died
                  const survRate = totalRuns > 0 ? Math.round(loc.runs_survived / totalRuns * 100) : null
                  return (
                    <div
                      key={loc.location}
                      className={`px-2 py-2 cursor-pointer transition-colors border-l-2 ${
                        hoveredSpawn === spawnMatch?.id
                          ? 'border-l-m-green bg-m-surface'
                          : 'border-l-transparent'
                      }`}
                      onMouseEnter={() => spawnMatch && setHoveredSpawn(spawnMatch.id)}
                      onMouseLeave={() => setHoveredSpawn(null)}
                    >
                      <div className="flex items-center gap-2 mb-1">
                        <div className="w-2 h-2 rounded-full bg-m-green/60 border border-m-green" />
                        <span className="text-2xs text-m-text uppercase tracking-wider flex-1 font-bold">{loc.location}</span>
                        <span className="text-[9px] font-mono text-m-text-muted">{loc.count}x</span>
                      </div>
                      {totalRuns > 0 && (
                        <div className="ml-4 grid grid-cols-2 gap-x-3 gap-y-0.5">
                          <span className="text-[8px] text-m-text-muted">SURV</span>
                          <span className={`text-[8px] font-mono text-right ${
                            survRate !== null && survRate >= 50 ? 'text-m-green' : 'text-m-red'
                          }`}>{survRate}%</span>
                          <span className="text-[8px] text-m-text-muted">LOOT</span>
                          <span className="text-[8px] font-mono text-m-yellow text-right">
                            ${Math.round(loc.avg_loot ?? 0).toLocaleString()}
                          </span>
                          <span className="text-[8px] text-m-text-muted">AVG TIME</span>
                          <span className="text-[8px] font-mono text-m-cyan text-right">
                            {loc.avg_time ? formatTime(loc.avg_time) : '—'}
                          </span>
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            ) : spawns.length > 0 ? (
              <div className="space-y-2">
                {spawns.map((spawn) => (
                  <div
                    key={spawn.id}
                    className={`flex items-center gap-2 cursor-pointer transition-colors ${
                      hoveredSpawn === spawn.id ? 'text-m-green' : ''
                    }`}
                    onMouseEnter={() => setHoveredSpawn(spawn.id)}
                    onMouseLeave={() => setHoveredSpawn(null)}
                  >
                    <div className="w-2 h-2 rounded-full bg-m-green/60 border border-m-green" />
                    <span className="text-2xs text-m-text uppercase tracking-wider flex-1">{spawn.zone}</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-2xs text-m-text-muted">NO SPAWNS RECORDED</p>
            )}
          </div>

          {/* Save button */}
          {dirty.size > 0 && (
            <div className="p-4 border-t border-m-border">
              <button
                onClick={saveToDb}
                disabled={saving}
                className="w-full py-2 bg-m-yellow/20 border border-m-yellow text-m-yellow text-2xs font-bold uppercase tracking-[0.15em] hover:bg-m-yellow/30 transition-colors disabled:opacity-50"
              >
                {saving ? 'SAVING...' : `SAVE ${dirty.size} CHANGE${dirty.size > 1 ? 'S' : ''}`}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function StatRow({ label, value, color }: { label: string; value: string; color?: 'green' | 'red' | 'yellow' | 'cyan' }) {
  const c = color === 'green' ? 'text-m-green' : color === 'red' ? 'text-m-red' : color === 'yellow' ? 'text-m-yellow' : color === 'cyan' ? 'text-m-cyan' : 'text-m-text'
  return (
    <div className="flex justify-between">
      <span className="label-tag text-m-text-muted">{label}</span>
      <span className={`text-2xs font-mono ${c}`}>{value}</span>
    </div>
  )
}

function TooltipStat({ label, value, color }: { label: string; value: string; color?: 'green' | 'red' | 'yellow' | 'cyan' }) {
  const c = color === 'green' ? 'text-m-green' : color === 'red' ? 'text-m-red' : color === 'yellow' ? 'text-m-yellow' : color === 'cyan' ? 'text-m-cyan' : 'text-m-text'
  return (
    <div className="flex justify-between gap-4">
      <span className="text-[9px] text-m-text-muted">{label}</span>
      <span className={`text-[9px] font-mono ${c}`}>{value}</span>
    </div>
  )
}
