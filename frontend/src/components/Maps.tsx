import { useEffect, useState, useRef, useCallback } from 'react'
import { motion } from 'framer-motion'
import { getMapStats, getSpawnHeatmap } from '../lib/api'
import { useStore } from '../lib/store'
import { MAPS, MAP_LIST } from '../lib/map-data'
import type { SpawnRef } from '../lib/map-data'
import type { MapStats, SpawnHeatmap } from '../lib/types'
import axios from 'axios'
import { apiBase } from '../lib/api'

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
  const [lockedSpawn, setLockedSpawn] = useState<string | null>(null)  // click-locked tooltip
  const { runs } = useStore()
  const [spawns, setSpawns] = useState<SpawnRef[]>([])
  const [dragState, setDragState] = useState<DragState | null>(null)
  const [dirty, setDirty] = useState<Set<string>>(new Set())
  const [saving, setSaving] = useState(false)
  const [spawnSort, setSpawnSort] = useState<'name' | 'surv' | 'loot' | 'streak'>('name')
  const [renamingSpawn, setRenamingSpawn] = useState<string | null>(null)  // spawn.id being renamed
  const [renameValue, setRenameValue] = useState('')
  const mapRef = useRef<HTMLDivElement>(null)

  const mapData = MAPS[selectedMap]
  const currentStats = mapStats.find((s) => s.map === selectedMap)
  const currentHeatmap = heatmap.find((h) => h.map === selectedMap)
  const mapImage = mapData?.image ? MAP_IMAGES[mapData.image] : null

  // Load spawns: try DB first, fall back to map-data.ts
  useEffect(() => {
    const md = MAPS[selectedMap]
    const fallback = md ? md.spawns.map(s => ({ ...s })) : []

    axios.get(`${apiBase}/api/spawns`, { params: { map_name: selectedMap } })
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
            gameCoords: (s.game_coord_x != null && s.game_coord_y != null)
              ? [s.game_coord_x, s.game_coord_y] as [number, number]
              : undefined,
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
        if (spawn.dbId) {
          // Save by DB ID — exact match, no name ambiguity
          await axios.put(`${apiBase}/api/spawns/update-coords-by-id`, {
            id: spawn.dbId,
            x: spawn.x,
            y: spawn.y,
          })
        } else {
          await axios.put(`${apiBase}/api/spawns/update-coords`, {
            map_name: selectedMap,
            spawn_location: spawn.zone,
            x: spawn.x,
            y: spawn.y,
          })
        }
      }
      setDirty(new Set())
    } catch (err) {
      console.error('Failed to save:', err)
    }
    setSaving(false)
  }

  return (
    <div className="max-w-7xl mx-auto space-y-4">
      {/* Header */}
      <div>
        <p className="label-tag text-m-green">MAPS // {selectedMap.toUpperCase().replace(/ /g, '.')}</p>
        <h2 className="text-xl font-display font-black tracking-wider text-m-text mt-1">
          {selectedMap.toUpperCase()}
        </h2>
      </div>

      {/* Hero Stats */}
      {currentStats && (
        <div className="grid grid-cols-4 gap-[1px] bg-m-border">
          <StatBlock label="RUNS" value={String(currentStats.runs)} accent />
          <StatBlock label="SURVIVAL RATE" value={`${currentStats.survival_rate}%`}
            color={currentStats.survival_rate >= 50 ? 'green' : 'red'} />
          <StatBlock label="K/D" value={String(currentStats.kd)}
            color={currentStats.kd >= 1 ? 'green' : 'red'} />
          <StatBlock label="TOTAL TIME" value={formatTime(currentStats.time)} color="cyan" />
        </div>
      )}

      {/* Map + Spawn sidebar — map defines height, sidebar is pinned alongside */}
      <div className="relative" style={{ marginRight: 196 }}>
      <div
        ref={mapRef}
        className="relative w-full select-none"
        style={{ aspectRatio: '1.414', cursor: dragState ? 'grabbing' : 'default' }}
        onMouseMove={onMouseMove}
        onMouseUp={onMouseUp}
        onMouseLeave={onMouseUp}
        onClick={(e) => {
          // Click on map background dismisses locked tooltip
          if (e.target === mapRef.current || (e.target as HTMLElement)?.tagName === 'IMG') {
            setLockedSpawn(null)
            setRenamingSpawn(null)
          }
        }}
      >
        {mapImage ? (
          <img
            src={mapImage}
            alt={selectedMap}
            className="absolute inset-0 w-full h-full pointer-events-none"
            draggable={false}
          />
        ) : (
          <div className="absolute inset-0 flex items-center justify-center">
            <p className="label-tag text-m-text-muted">NO MAP IMAGE</p>
          </div>
        )}

        {/* Uncharted spawns staging bracket — horizontal top row */}
        {(() => {
          const unchartedSpawns = spawns.filter(s => s.zone.startsWith('VCTR//') || s.zone.startsWith('//VCTR.RDCT//'))
          if (unchartedSpawns.length === 0) return null
          return (
            <div
              className="absolute z-30 pointer-events-none"
              style={{ left: '2%', top: '2%' }}
            >
              {/* Bracket — top-left + bottom-right corners hugging the dots */}
              <div className="relative flex items-center justify-center gap-[8px] px-2">
                {/* Top-left bracket */}
                <div className="absolute -top-2 -left-2 w-3 h-3 border-t-2 border-l-2 border-m-cyan/60" />
                {/* Bottom-right bracket */}
                <div className="absolute -bottom-2 -right-3.5 w-3 h-3 border-b-2 border-r-2 border-m-cyan/60" />
                {/* Invisible spacers — actual pins render via spawn system */}
                {unchartedSpawns.map((_, i) => (
                  <div key={i} className="w-4 h-4" />
                ))}
              </div>
              {/* Label — below bracket */}
              <div className="flex items-center justify-center mt-3">
                <span className="text-[7px] font-mono text-m-cyan/40 tracking-[0.2em]">
                  STAGING // {unchartedSpawns.length}
                </span>
              </div>
            </div>
          )
        })()}

        {/* Spawn point markers — draggable */}
        {spawns.map((spawn) => {
          const isHovered = hoveredSpawn === spawn.id
          const isDragging = dragState?.spawnId === spawn.id
          const isDirty = dirty.has(spawn.id)
          const isUncharted = spawn.zone.startsWith('VCTR//') || spawn.zone.startsWith('//VCTR.RDCT//')
          const pinColor = isDirty ? 'yellow' : isUncharted ? 'cyan' : 'green'
          const borderClass = pinColor === 'yellow' ? 'border-m-yellow/50' : pinColor === 'cyan' ? 'border-m-cyan/50' : 'border-m-green/30'
          const bgClass = pinColor === 'yellow' ? 'border-m-yellow bg-m-yellow/30' : pinColor === 'cyan' ? 'border-m-cyan bg-m-cyan/30' : 'border-m-green bg-m-green/15'
          const dotClass = pinColor === 'yellow' ? 'bg-m-yellow' : pinColor === 'cyan' ? 'bg-m-cyan' : 'bg-m-green'
          return (
            <div
              key={spawn.id}
              className="absolute transform -translate-x-1/2 -translate-y-1/2"
              style={{
                left: `${spawn.x}%`,
                top: `${spawn.y}%`,
                cursor: isDragging ? 'grabbing' : 'grab',
                zIndex: isDragging ? 50 : (isHovered || lockedSpawn === spawn.id) ? 40 : 10,
              }}
              onMouseDown={(e) => onMouseDown(e, spawn)}
              onDoubleClick={(e) => {
                e.stopPropagation()
                setLockedSpawn(spawn.id)
                setRenameValue(spawn.zone)
                setRenamingSpawn(spawn.id)
              }}
              onMouseEnter={() => !dragState && setHoveredSpawn(spawn.id)}
              onMouseLeave={() => !dragState && !lockedSpawn && setHoveredSpawn(null)}
            >
              <motion.div
                className={`absolute rounded-full border ${borderClass}`}
                style={{ width: 28, height: 28, left: -14, top: -14 }}
                animate={{ opacity: [0.3, 0.6, 0.3], scale: [1, 1.2, 1] }}
                transition={{ duration: 2.5, repeat: Infinity }}
              />
              <div className={`relative w-4 h-4 -ml-2 -mt-2 rounded-full border-2 flex items-center justify-center transition-all ${bgClass} ${isHovered || isDragging || lockedSpawn === spawn.id ? 'scale-150' : ''}`}>
                <div className={`w-1.5 h-1.5 rounded-full ${dotClass}`} />
              </div>

              {/* Tooltip */}
              {(isHovered || isDragging || lockedSpawn === spawn.id) && (() => {
                const loc = currentHeatmap?.locations.find(l => l.location === spawn.zone)
                const totalRuns = loc ? loc.runs_survived + loc.runs_died : 0
                const survRate = totalRuns > 0 ? Math.round(loc!.runs_survived / totalRuns * 100) : null
                return (
                  <div className={`absolute top-full left-1/2 -translate-x-1/2 mt-3 bg-m-black/95 border ${isUncharted ? 'border-m-cyan/40' : 'border-m-green/40'} px-3 py-2 min-w-[140px] z-[100] ${renamingSpawn === spawn.id ? '' : 'pointer-events-none'}`}>
                    {renamingSpawn === spawn.id ? (
                      <form
                        className="pointer-events-auto"
                        onSubmit={(e) => {
                          e.preventDefault()
                          if (!renameValue.trim() || !spawn.dbId) return
                          axios.put(`${apiBase}/api/spawns/rename`, { id: spawn.dbId, spawn_location: renameValue.trim() })
                            .then(() => {
                              setSpawns(prev => prev.map(s => s.id === spawn.id ? { ...s, zone: renameValue.trim() } : s))
                              setRenamingSpawn(null)
                            })
                        }}
                      >
                        <input
                          autoFocus
                          value={renameValue}
                          onChange={e => setRenameValue(e.target.value.toUpperCase())}
                          onBlur={() => setRenamingSpawn(null)}
                          onKeyDown={e => e.key === 'Escape' && setRenamingSpawn(null)}
                          className="w-full bg-m-black text-[10px] font-mono text-m-green tracking-[0.15em] font-bold uppercase border border-m-green/40 px-1 py-0.5 focus:outline-none focus:border-m-green"
                          placeholder="ENTER NAME..."
                        />
                      </form>
                    ) : (
                      <p
                        className={`text-[10px] tracking-[0.15em] font-bold uppercase cursor-pointer pointer-events-auto hover:underline ${isUncharted ? 'text-m-cyan' : 'text-m-green'}`}
                        onClick={(e) => {
                          e.stopPropagation()
                          setRenameValue(spawn.zone)
                          setRenamingSpawn(spawn.id)
                        }}
                      >
                        {spawn.zone}
                      </p>
                    )}
                    {spawn.gameCoords && (
                      <p className="text-[10px] font-mono mt-1 text-m-cyan tracking-wide">
                        {spawn.gameCoords[0].toFixed(2)}, {spawn.gameCoords[1].toFixed(2)}
                      </p>
                    )}
                    {isDragging && (
                      <p className="text-[10px] font-mono text-m-yellow mt-1">x: {spawn.x} &nbsp; y: {spawn.y}</p>
                    )}
                    {!isDragging && loc && totalRuns > 0 && (() => {
                      const l = loc as any
                      const killedBy = l.killed_by?.length > 0 ? l.killed_by[l.killed_by.length - 1] : null
                      return (
                        <div className="mt-1.5 space-y-0.5">
                          <TooltipStat label="SPAWNS" value={`${loc.count}x`} />
                          <TooltipStat label="SURVIVAL" value={`${survRate}%`} color={survRate! >= 50 ? 'green' : 'red'} />
                          <TooltipStat label="WIN STREAK" value={(() => {
                            // Count consecutive exfils from the end (most recent)
                            // For now with 1 run per spawn, it's just survived ? 1 : 0
                            // Will improve when we have multiple runs per spawn
                            return String(loc.runs_survived > 0 && loc.runs_died === 0 ? loc.runs_survived : 0)
                          })()} color={loc.runs_survived > 0 && loc.runs_died === 0 ? 'green' : undefined} />
                          <div className="border-t border-m-border/30 my-1 pt-1" />
                          <TooltipStat label="AVG LOOT" value={`$${Math.round(loc.avg_loot ?? 0).toLocaleString()}`} color="yellow" />
                          <TooltipStat label="BEST LOOT" value={l.best_loot != null ? `$${l.best_loot.toLocaleString()}` : '—'} color="yellow" />
                          <TooltipStat label="WORST LOOT" value={l.worst_loot != null ? `$${l.worst_loot.toLocaleString()}` : '—'} color={l.worst_loot < 0 ? 'red' : undefined} />
                          <div className="border-t border-m-border/30 my-1 pt-1" />
                          <TooltipStat label="PVE KILLS" value={String(l.pve_kills ?? 0)} color={l.pve_kills ? 'green' : undefined} />
                          <TooltipStat label="RUNNER KILLS" value={String(l.runner_kills ?? 0)} color={l.runner_kills ? 'cyan' : undefined} />
                          <TooltipStat label="DEATHS" value={String(l.total_deaths ?? 0)} color={l.total_deaths ? 'red' : undefined} />
                          <TooltipStat label="REVIVES" value={String(l.total_revives ?? 0)} color={l.total_revives ? 'green' : undefined} />
                          <div className="border-t border-m-border/30 my-1 pt-1" />
                          <TooltipStat label="WEAPON" value={l.fav_weapon ?? '—'} />
                          <TooltipStat label="SHELL" value={l.fav_shell ?? '—'} />
                          {killedBy && (
                            <TooltipStat label="ENEMY" value={killedBy.name} color="red" />
                          )}
                        </div>
                      )
                    })()}
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

        {/* Save button overlay */}
        {dirty.size > 0 && (
          <div className="absolute bottom-4 left-1/2 -translate-x-1/2 z-50">
            <button
              onClick={saveToDb}
              disabled={saving}
              className="px-6 py-2 bg-m-yellow/20 border border-m-yellow text-m-yellow text-2xs font-bold uppercase tracking-[0.15em] hover:bg-m-yellow/30 transition-colors disabled:opacity-50 backdrop-blur-sm"
            >
              {saving ? 'SAVING...' : `SAVE ${dirty.size} CHANGE${dirty.size > 1 ? 'S' : ''}`}
            </button>
          </div>
        )}
      </div>

      {/* Spawn Points sidebar — absolutely positioned, locked to map height, scrollable */}
      <div className="absolute top-0 bottom-0 right-[-196px] w-[180px] bg-m-card flex flex-col overflow-hidden">
        <div className="px-3 py-2 border-b border-m-border shrink-0">
          <p className="label-tag text-m-green mb-2">SPAWN POINTS</p>
          <div className="border-t border-m-border pt-2 mt-2 -mx-3" />
          <div className="flex gap-[1px]">
            {([['name', 'AZ'], ['surv', 'SRV'], ['loot', 'LT'], ['streak', 'STRK']] as const).map(([key, label]) => (
              <button
                key={key}
                onClick={() => setSpawnSort(key)}
                className={`px-2 py-0.5 text-[8px] tracking-wider transition-all ${
                  spawnSort === key
                    ? 'bg-m-green/15 text-m-green'
                    : 'text-m-text-muted hover:text-m-text'
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        <div className="flex-1 overflow-y-auto min-h-0">
          {spawns.length > 0 ? (
            <div className="divide-y divide-m-border">
              {[...spawns].sort((a, b) => {
                const aLoc = currentHeatmap?.locations.find(l => l.location === a.zone)
                const bLoc = currentHeatmap?.locations.find(l => l.location === b.zone)
                const aTotal = aLoc ? aLoc.runs_survived + aLoc.runs_died : 0
                const bTotal = bLoc ? bLoc.runs_survived + bLoc.runs_died : 0
                const aSurv = aTotal > 0 ? aLoc!.runs_survived / aTotal : -1
                const bSurv = bTotal > 0 ? bLoc!.runs_survived / bTotal : -1
                const aStreak = aLoc && aLoc.runs_survived > 0 && aLoc.runs_died === 0 ? aLoc.runs_survived : 0
                const bStreak = bLoc && bLoc.runs_survived > 0 && bLoc.runs_died === 0 ? bLoc.runs_survived : 0
                switch (spawnSort) {
                  case 'name': return a.zone.localeCompare(b.zone)
                  case 'surv': return bSurv - aSurv
                  case 'loot': return ((bLoc as any)?.avg_loot ?? -Infinity) - ((aLoc as any)?.avg_loot ?? -Infinity)
                  case 'streak': return bStreak - aStreak
                  default: return 0
                }
              }).map((spawn) => {
                const loc = currentHeatmap?.locations.find(l => l.location === spawn.zone)
                const isUnchartedItem = spawn.zone.startsWith('//VCTR.RDCT//')
                const totalRuns = loc ? loc.runs_survived + loc.runs_died : 0
                const survRate = totalRuns > 0 ? Math.round(loc!.runs_survived / totalRuns * 100) : null
                return (
                  <div
                    key={spawn.id}
                    className={`px-3 py-2.5 cursor-pointer transition-colors ${
                      hoveredSpawn === spawn.id ? 'bg-m-surface' : ''
                    }`}
                    onMouseEnter={() => setHoveredSpawn(spawn.id)}
                    onMouseLeave={() => setHoveredSpawn(null)}
                  >
                    <p className={`text-2xs uppercase tracking-wider font-bold mb-1.5 ${isUnchartedItem ? 'text-m-cyan' : 'text-m-text'}`}>{spawn.zone}</p>
                    {loc && totalRuns > 0 && (() => {
                      const l = loc as any
                      const streak = loc!.runs_survived > 0 && loc!.runs_died === 0 ? loc!.runs_survived : 0
                      return (
                        <div className="ml-0 mt-1 space-y-0.5 text-[9px] font-mono">
                          <div className="flex justify-between">
                            <span className="text-m-text-muted">SURVIVE</span>
                            <span className={survRate !== null && survRate >= 50 ? 'text-m-green' : 'text-m-red'}>{survRate}%</span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-m-text-muted">AVG LOOT</span>
                            <span className="text-m-yellow">${Math.round(loc!.avg_loot ?? 0).toLocaleString()}</span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-m-text-muted">STREAK</span>
                            <span className={streak > 0 ? 'text-m-green' : 'text-m-text-muted'}>{streak}</span>
                          </div>
                        </div>
                      )
                    })()}
                  </div>
                )
              })}
            </div>
          ) : (
            <div className="px-3 py-4">
              <p className="text-2xs text-m-text-muted">NO SPAWNS RECORDED</p>
            </div>
          )}
        </div>
      </div>
      </div>

      {/* Detail Columns — below map */}
      {currentStats && (
        <div className="grid grid-cols-4 gap-[1px] bg-m-border">
          {/* Favorites */}
          <div className="bg-m-card">
            <div className="px-4 py-2 border-b border-m-border">
              <p className="label-tag text-m-green">FAVORITES</p>
            </div>
            <div className="divide-y divide-m-border">
              <ColStat label="SHELL" value={(() => {
                const mapRuns = runs.filter(r => r.map_name === selectedMap && r.shell_name)
                if (!mapRuns.length) return '—'
                const counts: Record<string, number> = {}
                mapRuns.forEach(r => { counts[r.shell_name!] = (counts[r.shell_name!] || 0) + 1 })
                return Object.entries(counts).sort((a, b) => b[1] - a[1])[0][0]
              })()} />
              <ColStat label="WEAPON" value={(() => {
                const mapRuns = runs.filter(r => r.map_name === selectedMap && r.primary_weapon)
                if (!mapRuns.length) return '—'
                const counts: Record<string, number> = {}
                mapRuns.forEach(r => { counts[r.primary_weapon!] = (counts[r.primary_weapon!] || 0) + 1 })
                return Object.entries(counts).sort((a, b) => b[1] - a[1])[0][0]
              })()} />
              <ColStat label="BEST SPAWN" value={(() => {
                if (!currentHeatmap?.locations.length) return '—'
                const best = [...currentHeatmap.locations]
                  .filter(l => l.runs_survived + l.runs_died > 0)
                  .sort((a, b) => (b.avg_loot ?? 0) - (a.avg_loot ?? 0))[0]
                return best?.location ?? '—'
              })()} />
              <ColStat label="SQUAD MATE" value={(() => {
                const mapRuns = runs.filter(r => r.map_name === selectedMap && r.squad_members?.length)
                if (!mapRuns.length) return '—'
                // Exclude the local player's gamertags (auto-detected from runs)
                const selfTags = new Set(runs.map(r => r.player_gamertag?.toLowerCase()).filter(Boolean))
                const counts: Record<string, number> = {}
                mapRuns.forEach(r => r.squad_members?.forEach(m => {
                  if (m && !selfTags.has(m.toLowerCase())) counts[m] = (counts[m] || 0) + 1
                }))
                const entries = Object.entries(counts)
                return entries.length > 0 ? entries.sort((a, b) => b[1] - a[1])[0][0] : '—'
              })()} />
            </div>
          </div>

          {/* Economy */}
          <div className="bg-m-card">
            <div className="px-4 py-2 border-b border-m-border">
              <p className="label-tag text-m-green">ECONOMY</p>
            </div>
            <div className="divide-y divide-m-border">
              <ColStat label="TOTAL LOOT" value={`$${currentStats.loot.toLocaleString()}`} color="yellow" />
              <ColStat label="AVG LOOT/RUN" value={`$${currentStats.avg_loot.toLocaleString()}`} color="yellow" />
              <ColStat label="BEST RUN" value={(() => {
                const mapRuns = runs.filter(r => r.map_name === selectedMap)
                return mapRuns.length > 0 ? `$${Math.max(...mapRuns.map(r => r.loot_value_total)).toLocaleString()}` : '—'
              })()} color="yellow" />
              <ColStat label="WORST RUN" value={(() => {
                const mapRuns = runs.filter(r => r.map_name === selectedMap)
                return mapRuns.length > 0 ? `$${Math.min(...mapRuns.map(r => r.loot_value_total)).toLocaleString()}` : '—'
              })()} color="red" />
            </div>
          </div>

          {/* Combat */}
          <div className="bg-m-card">
            <div className="px-4 py-2 border-b border-m-border">
              <p className="label-tag text-m-green">COMBAT</p>
            </div>
            <div className="divide-y divide-m-border">
              <ColStat label="PVE KILLS" value={String(currentStats.pve_kills)} color="green" />
              <ColStat label="RUNNER KILLS" value={String(currentStats.pvp_kills)} color="cyan" />
              <ColStat label="DEATHS" value={String(currentStats.deaths)} color={currentStats.deaths > 0 ? 'red' : undefined} />
              <ColStat label="REVIVES" value={String(runs.filter(r => r.map_name === selectedMap).reduce((sum, r) => sum + (r.crew_revives || 0), 0))} color="green" />
            </div>
          </div>

          {/* Time */}
          <div className="bg-m-card">
            <div className="px-4 py-2 border-b border-m-border">
              <p className="label-tag text-m-green">TIME</p>
            </div>
            <div className="divide-y divide-m-border">
              <ColStat label="TOTAL TIME" value={formatTime(currentStats.time)} color="cyan" />
              <ColStat label="AVG TIME" value={formatTime(currentStats.avg_time)} color="cyan" />
              <ColStat label="LONGEST RUN" value={(() => {
                const mapRuns = runs.filter(r => r.map_name === selectedMap && r.duration_seconds)
                return mapRuns.length > 0 ? formatTime(Math.max(...mapRuns.map(r => r.duration_seconds!))) : '—'
              })()} color="cyan" />
              <ColStat label="SHORTEST RUN" value={(() => {
                const mapRuns = runs.filter(r => r.map_name === selectedMap && r.duration_seconds)
                return mapRuns.length > 0 ? formatTime(Math.min(...mapRuns.map(r => r.duration_seconds!))) : '—'
              })()} />
            </div>
          </div>
        </div>
      )}
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

function StatBlock({ label, value, color, accent }: { label: string; value: string; color?: 'green' | 'red' | 'yellow' | 'cyan'; accent?: boolean }) {
  const c = { green: 'text-m-green', red: 'text-m-red', yellow: 'text-m-yellow', cyan: 'text-m-cyan' }[color as string] ?? 'text-m-text'
  return (
    <div className="bg-m-card p-5">
      <p className="label-tag text-m-text-muted">{label}</p>
      <p className={`text-2xl font-mono font-bold mt-1 ${c}`}>{value}</p>
    </div>
  )
}

function ColStat({ label, value, color }: { label: string; value: string; color?: 'green' | 'red' | 'yellow' | 'cyan' }) {
  const c = color ? { green: 'text-m-green', red: 'text-m-red', yellow: 'text-m-yellow', cyan: 'text-m-cyan' }[color] : 'text-m-text'
  return (
    <div className="flex justify-between items-center px-4 py-2.5">
      <span className="label-tag text-m-text-muted">{label}</span>
      <span className={`text-xs font-mono font-bold ${c}`}>{value}</span>
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
