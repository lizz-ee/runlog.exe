import { useEffect, useState } from 'react'
import { getShellStats } from '../lib/api'
import type { ShellStats } from '../lib/types'

import triageImg from '../assets/shells/triage.png'
import vandalImg from '../assets/shells/vandal.png'
import reconImg from '../assets/shells/recon.png'
import thiefImg from '../assets/shells/thief.png'
import destroyerImg from '../assets/shells/destroyer.png'
import assassinImg from '../assets/shells/assassin.png'

const SHELL_IMAGES: Record<string, string> = {
  triage: triageImg,
  vandal: vandalImg,
  recon: reconImg,
  thief: thiefImg,
  destroyer: destroyerImg,
  assassin: assassinImg,
}

const ALL_SHELLS = ['triage', 'vandal', 'recon', 'thief', 'destroyer', 'assassin']

const EMPTY_SHELL: ShellStats = {
  runner_id: 0, runner_name: '', runs: 0, survived: 0, survival_rate: 0,
  kills: 0, pve_kills: 0, pvp_kills: 0, deaths: 0, revives: 0, kd: 0,
  loot: 0, avg_loot: 0, time: 0, avg_time: 0, favorite_weapon: null,
}

function getShellImage(name: string): string | null {
  return SHELL_IMAGES[name.toLowerCase()] ?? null
}

function formatTime(seconds: number): string {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (h > 0) return `${h}h ${m}m`
  return `${m}m`
}

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

export default function Shells() {
  const [shells, setShells] = useState<ShellStats[]>([])
  const [selected, setSelected] = useState<string | null>(null)

  useEffect(() => {
    getShellStats().then((data) => {
      setShells(data)
      // Select the best shell (most runs) by default
      if (data.length > 0) {
        const sorted = [...data].sort((a, b) => b.runs - a.runs)
        setSelected(sorted[0].runner_name.toLowerCase())
      } else {
        setSelected('triage')
      }
    })
  }, [])

  // Build shell map and sort: shells with data sorted by runs (best first), then shells with no data
  const shellMap = new Map(shells.map((s) => [s.runner_name.toLowerCase(), s]))
  const withData = ALL_SHELLS
    .filter((name) => shellMap.has(name))
    .sort((a, b) => (shellMap.get(b)?.runs ?? 0) - (shellMap.get(a)?.runs ?? 0))
  const withoutData = ALL_SHELLS.filter((name) => !shellMap.has(name))
  // Also include any unknown shells from data
  const unknown = shells
    .map((s) => s.runner_name.toLowerCase())
    .filter((name) => !ALL_SHELLS.includes(name))
  const orderedNames = [...withData, ...unknown, ...withoutData]

  const getShellData = (name: string): ShellStats => {
    return shellMap.get(name) ?? { ...EMPTY_SHELL, runner_name: name }
  }

  const selectedShell = getShellData(selected ?? '')

  return (
    <div className="max-w-7xl mx-auto space-y-4">
      {/* Header */}
      <div>
        <p className="label-tag text-m-green">SYSTEM // SHELLS</p>
        <h2 className="text-xl font-display font-black tracking-wider text-m-text mt-1">
          SHELLS
        </h2>
      </div>

      {/* Shell cards */}
      <div className="grid grid-cols-6 gap-3">
        {orderedNames.map((name, i) => {
          const shell = shellMap.get(name)
          const img = getShellImage(name)
          const isSelected = selected === name
          const hasData = !!shell

          return (
            <ShellCard
              key={name}
              name={name}
              img={img}
              runs={shell?.runs ?? 0}
              survivalRate={shell?.survival_rate ?? 0}
              hasData={hasData}
              isSelected={isSelected}
              rank={hasData ? withData.indexOf(name) + 1 : 0}
              onClick={() => setSelected(name)}
            />
          )
        })}
      </div>

      {/* Selected shell stats */}
      {selected && (
        <>
          {/* Hero stats */}
          <div className="grid grid-cols-5 gap-[1px] bg-m-border">
            <StatBlock label="RUNS" value={String(selectedShell.runs)} accent />
            <StatBlock
              label="SURVIVAL RATE"
              value={`${selectedShell.survival_rate}%`}
              color={selectedShell.survival_rate >= 50 ? 'green' : selectedShell.runs > 0 ? 'red' : undefined}
            />
            <StatBlock
              label="K/D"
              value={selectedShell.kd.toFixed(2)}
              color={selectedShell.kd >= 1 ? 'green' : selectedShell.runs > 0 ? 'red' : undefined}
            />
            <StatBlock
              label="AVG LOOT"
              value={`$${selectedShell.avg_loot.toLocaleString()}`}
              color={selectedShell.runs > 0 ? 'yellow' : undefined}
            />
            <StatBlock
              label="TOTAL TIME"
              value={formatTime(selectedShell.time)}
              color={selectedShell.runs > 0 ? 'cyan' : undefined}
            />
          </div>

          {/* Detail columns */}
          <div className="grid grid-cols-3 gap-[1px] bg-m-border">
            {/* Combat */}
            <div className="bg-m-card">
              <div className="px-4 py-2 border-b border-m-border">
                <p className="label-tag text-m-green">COMBAT</p>
              </div>
              <div className="divide-y divide-m-border">
                <ColStat label="PVE KILLS" value={String(selectedShell.pve_kills)} color={selectedShell.pve_kills > 0 ? 'green' : undefined} />
                <ColStat label="RUNNER KILLS" value={String(selectedShell.pvp_kills)} color={selectedShell.pvp_kills > 0 ? 'cyan' : undefined} />
                <ColStat label="TOTAL KILLS" value={String(selectedShell.kills)} />
                <ColStat label="DEATHS" value={String(selectedShell.deaths)} color={selectedShell.deaths > 0 ? 'red' : undefined} />
                <ColStat label="REVIVES" value={String(selectedShell.revives)} color={selectedShell.revives > 0 ? 'green' : undefined} />
              </div>
            </div>

            {/* Economy */}
            <div className="bg-m-card">
              <div className="px-4 py-2 border-b border-m-border">
                <p className="label-tag text-m-green">ECONOMY</p>
              </div>
              <div className="divide-y divide-m-border">
                <ColStat label="TOTAL LOOT" value={`$${selectedShell.loot.toLocaleString()}`} color={selectedShell.loot > 0 ? 'yellow' : undefined} />
                <ColStat label="AVG LOOT/RUN" value={`$${selectedShell.avg_loot.toLocaleString()}`} color={selectedShell.avg_loot > 0 ? 'yellow' : undefined} />
                <ColStat label="EXFILTRATED" value={String(selectedShell.survived)} color={selectedShell.survived > 0 ? 'green' : undefined} />
                <ColStat label="KIA" value={String(selectedShell.runs - selectedShell.survived)} color={selectedShell.runs - selectedShell.survived > 0 ? 'red' : undefined} />
              </div>
            </div>

            {/* Info */}
            <div className="bg-m-card">
              <div className="px-4 py-2 border-b border-m-border">
                <p className="label-tag text-m-green">INFO</p>
              </div>
              <div className="divide-y divide-m-border">
                <ColStat label="FAVORITE WEAPON" value={selectedShell.favorite_weapon ?? '—'} />
                <ColStat label="AVG RUN TIME" value={formatDuration(selectedShell.avg_time)} color={selectedShell.avg_time > 0 ? 'cyan' : undefined} />
                <ColStat label="TOTAL TIME" value={formatTime(selectedShell.time)} color={selectedShell.time > 0 ? 'cyan' : undefined} />
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  )
}

/* ── Shell Card with cyberpunk treatment ── */

function ShellCard({ name, img, runs, survivalRate, hasData, isSelected, rank, onClick }: {
  name: string; img: string | null; runs: number; survivalRate: number
  hasData: boolean; isSelected: boolean; rank: number; onClick: () => void
}) {
  const [hovered, setHovered] = useState(false)
  const active = isSelected || hovered

  return (
    <button
      onClick={onClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      className="relative aspect-[3/4] group focus:outline-none overflow-hidden"
    >
      {/* Shell image */}
      <div className={`absolute inset-0 transition-all duration-300 ${
        isSelected ? 'brightness-110' : hasData ? 'brightness-[0.6] group-hover:brightness-90' : 'brightness-[0.3] grayscale-[50%] group-hover:brightness-[0.4] group-hover:grayscale-0'
      }`}>
        {img ? (
          <img src={img} alt={name} className="w-full h-full object-cover" />
        ) : (
          <div className="w-full h-full bg-m-card flex items-center justify-center">
            <span className="text-m-text-muted text-2xl font-bold uppercase">{name[0]}</span>
          </div>
        )}
      </div>

      {/* Gradient overlay */}
      <div className="absolute inset-0 bg-gradient-to-t from-black/95 via-black/40 to-black/10 z-[1]" />

      {/* Scan line on hover/select */}
      <div className={`absolute inset-0 overflow-hidden pointer-events-none z-[2] ${active ? 'opacity-100' : 'opacity-0'} transition-opacity`}>
        <div className="absolute top-0 left-0 right-0 h-[40px] bg-gradient-to-b from-[#c8ff00]/8 to-transparent animate-[scanDown_2s_linear_infinite]" />
      </div>

      {/* Corner brackets */}
      <div className={`absolute top-1.5 left-1.5 w-3 h-3 border-l border-t z-[3] transition-colors duration-300 ${
        active ? 'border-[#c8ff00]/60' : 'border-[#c8ff00]/10'
      }`} />
      <div className={`absolute top-1.5 right-1.5 w-3 h-3 border-r border-t z-[3] transition-colors duration-300 ${
        active ? 'border-[#c8ff00]/60' : 'border-[#c8ff00]/10'
      }`} />
      <div className={`absolute bottom-1.5 left-1.5 w-3 h-3 border-l border-b z-[3] transition-colors duration-300 ${
        active ? 'border-[#c8ff00]/60' : 'border-[#c8ff00]/10'
      }`} />
      <div className={`absolute bottom-1.5 right-1.5 w-3 h-3 border-r border-b z-[3] transition-colors duration-300 ${
        active ? 'border-[#c8ff00]/60' : 'border-[#c8ff00]/10'
      }`} />

      {/* Selected top bar with glow */}
      {isSelected && (
        <div className="absolute top-0 left-0 right-0 h-[2px] bg-[#c8ff00] shadow-[0_0_8px_rgba(200,255,0,0.5)] z-[4]" />
      )}

      {/* Rank badge */}
      {rank > 0 && (
        <span className={`absolute top-2.5 right-3 text-lg font-display font-black z-[3] transition-colors duration-300 ${
          isSelected ? 'text-[#c8ff00]/25' : 'text-m-text-muted/10'
        }`}>
          {String(rank).padStart(2, '0')}
        </span>
      )}

      {/* Content overlay */}
      <div className="absolute inset-0 z-[3] flex flex-col p-3">
        {/* Status dot */}
        <div className="flex items-center gap-1.5">
          <div className={`w-1 h-1 rounded-full transition-all duration-300 ${
            isSelected
              ? 'bg-[#c8ff00] shadow-[0_0_6px_rgba(200,255,0,0.8)]'
              : hasData ? (survivalRate >= 50 ? 'bg-[#c8ff00]/30' : 'bg-red-500/30') : 'bg-m-text-muted/20'
          }`} />
          <span className={`text-[7px] tracking-[0.2em] transition-colors duration-300 ${
            isSelected ? 'text-[#c8ff00]/60' : 'text-[#c8ff00]/15'
          }`}>
            SHELL
          </span>
        </div>

        <div className="flex-1" />

        {/* Divider */}
        <div className={`w-full h-px mb-2 transition-all duration-300 ${
          active
            ? 'bg-gradient-to-r from-transparent via-[#c8ff00]/40 to-transparent'
            : 'bg-gradient-to-r from-transparent via-[#c8ff00]/10 to-transparent'
        }`} />

        {/* Name */}
        <p className={`text-xs tracking-[0.15em] font-bold uppercase transition-all duration-300 ${
          isSelected
            ? 'text-[#c8ff00] drop-shadow-[0_0_8px_rgba(200,255,0,0.3)]'
            : 'text-m-text group-hover:text-[#c8ff00]/80'
        }`}>
          {name}
        </p>

        {/* Stats */}
        <div className="flex gap-3 mt-1">
          <span className="text-[8px] font-mono text-m-text-muted">
            {runs} RUNS
          </span>
          {hasData ? (
            <span className={`text-[8px] font-mono ${
              survivalRate >= 50 ? 'text-[#c8ff00]' : 'text-red-400'
            }`}>
              {survivalRate}%
            </span>
          ) : (
            <span className="text-[8px] font-mono text-m-text-muted/40">NO DATA</span>
          )}
        </div>

        {/* Survival micro bar */}
        <div className="w-full h-[3px] bg-[#ffffff05] rounded-full overflow-hidden mt-1.5">
          <div
            className={`h-full rounded-full transition-all duration-500 ${
              survivalRate >= 50 ? 'bg-[#c8ff00]/40' : 'bg-red-400/40'
            }`}
            style={{ width: `${hasData ? Math.max(3, survivalRate) : 0}%` }}
          />
        </div>
      </div>

      {/* Outer border */}
      <div className={`absolute inset-0 border z-[4] transition-all duration-300 pointer-events-none ${
        isSelected
          ? 'border-[#c8ff00]/30'
          : 'border-m-border/30 group-hover:border-[#c8ff00]/20'
      }`} />
    </button>
  )
}

/* ── Shared stat components ── */

function StatBlock({ label, value, color, accent }: {
  label: string; value: string; color?: 'green' | 'red' | 'yellow' | 'cyan'; accent?: boolean
}) {
  const colorClass = { green: 'text-m-green', red: 'text-m-red', yellow: 'text-m-yellow', cyan: 'text-m-cyan' }[color as string] ?? 'text-m-text'
  return (
    <div className="bg-m-card p-5">
      <p className="label-tag text-m-text-muted">{label}</p>
      <p className={`text-2xl font-mono font-bold mt-1 ${colorClass}`}>{value}</p>
    </div>
  )
}

function ColStat({ label, value, color }: {
  label: string; value: string; color?: 'green' | 'red' | 'yellow' | 'cyan'
}) {
  const c = color ? { green: 'text-m-green', red: 'text-m-red', yellow: 'text-m-yellow', cyan: 'text-m-cyan' }[color] : 'text-m-text'
  return (
    <div className="flex justify-between items-center px-4 py-2.5">
      <span className="label-tag text-m-text-muted">{label}</span>
      <span className={`text-xs font-mono font-bold ${c}`}>{value}</span>
    </div>
  )
}
