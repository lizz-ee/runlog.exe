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

// Display order
const SHELL_ORDER = ['triage', 'vandal', 'recon', 'thief', 'destroyer', 'assassin']

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
      if (data.length > 0) {
        setSelected(data.sort((a, b) => b.runs - a.runs)[0].runner_name.toLowerCase())
      }
    })
  }, [])

  const selectedShell = shells.find(
    (s) => s.runner_name.toLowerCase() === selected
  )

  // Build ordered list: known shells first (in order), then any unknown ones
  const shellMap = new Map(shells.map((s) => [s.runner_name.toLowerCase(), s]))
  const orderedNames = [
    ...SHELL_ORDER,
    ...shells
      .map((s) => s.runner_name.toLowerCase())
      .filter((name) => !SHELL_ORDER.includes(name)),
  ]

  return (
    <div className="max-w-7xl mx-auto space-y-4">
      {/* Header */}
      <div>
        <p className="label-tag text-m-green">SYSTEM / SHELLS</p>
        <h2 className="text-xl font-display font-black tracking-wider text-m-text mt-1">
          SHELLS
        </h2>
      </div>

      {/* Shell portraits — always visible */}
      {(
        <>
          {/* Shell portraits — side by side */}
          <div className="grid grid-cols-6 gap-[1px] bg-m-border">
            {orderedNames.map((name) => {
              const shell = shellMap.get(name)
              const img = getShellImage(name)
              const isSelected = selected === name
              const hasData = !!shell

              return (
                <button
                  key={name}
                  onClick={() => hasData && setSelected(name)}
                  className={`relative overflow-hidden transition-all group ${
                    !hasData
                      ? 'opacity-30 cursor-not-allowed'
                      : isSelected
                        ? 'ring-1 ring-m-green'
                        : 'hover:ring-1 hover:ring-m-green/40'
                  }`}
                >
                  {/* Image */}
                  <div className={`relative aspect-[3/4] bg-m-card ${
                    isSelected ? 'brightness-110' : hasData ? 'brightness-75 group-hover:brightness-100' : 'brightness-50 grayscale'
                  } transition-all`}>
                    {img ? (
                      <img
                        src={img}
                        alt={name}
                        className="w-full h-full object-cover"
                      />
                    ) : (
                      <div className="w-full h-full flex items-center justify-center">
                        <span className="text-m-text-muted text-2xl font-bold uppercase">
                          {name[0]}
                        </span>
                      </div>
                    )}

                    {/* Gradient overlay */}
                    <div className="absolute inset-0 bg-gradient-to-t from-black/90 via-black/20 to-transparent" />

                    {/* Name + mini stats */}
                    <div className="absolute bottom-0 left-0 right-0 p-3">
                      <p className={`text-xs tracking-[0.15em] font-bold uppercase ${
                        isSelected ? 'text-m-green' : 'text-m-text'
                      }`}>
                        {name}
                      </p>
                      {hasData && (
                        <div className="flex gap-3 mt-1">
                          <span className="label-tag text-m-text-muted">
                            {shell!.runs} RUNS
                          </span>
                          <span className={`label-tag ${
                            shell!.survival_rate >= 50 ? 'text-m-green' : 'text-m-red'
                          }`}>
                            {shell!.survival_rate}%
                          </span>
                        </div>
                      )}
                      {!hasData && (
                        <p className="label-tag text-m-text-muted mt-1">NO DATA</p>
                      )}
                    </div>

                    {/* Selected indicator */}
                    {isSelected && (
                      <div className="absolute top-0 left-0 right-0 h-[2px] bg-m-green" />
                    )}
                  </div>
                </button>
              )
            })}

          </div>

          {/* Selected shell stats */}
          {selectedShell && (
            <>
              {/* Hero stats */}
              <div className="grid grid-cols-5 gap-[1px] bg-m-border">
                <StatBlock label="RUNS" value={String(selectedShell.runs)} accent />
                <StatBlock
                  label="SURVIVAL RATE"
                  value={`${selectedShell.survival_rate}%`}
                  color={selectedShell.survival_rate >= 50 ? 'green' : 'red'}
                />
                <StatBlock
                  label="K/D"
                  value={selectedShell.kd.toFixed(2)}
                  color={selectedShell.kd >= 1 ? 'green' : 'red'}
                />
                <StatBlock
                  label="AVG LOOT"
                  value={`$${selectedShell.avg_loot.toLocaleString()}`}
                  color="yellow"
                />
                <StatBlock
                  label="TOTAL TIME"
                  value={formatTime(selectedShell.time)}
                  color="cyan"
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
                    <ColStat label="PVE KILLS" value={String(selectedShell.pve_kills)} color="green" />
                    <ColStat label="RUNNER KILLS" value={String(selectedShell.pvp_kills)} color="cyan" />
                    <ColStat label="TOTAL KILLS" value={String(selectedShell.kills)} />
                    <ColStat
                      label="DEATHS"
                      value={String(selectedShell.deaths)}
                      color={selectedShell.deaths > 0 ? 'red' : undefined}
                    />
                    <ColStat
                      label="REVIVES"
                      value={String(selectedShell.revives)}
                      color={selectedShell.revives > 0 ? 'green' : undefined}
                    />
                  </div>
                </div>

                {/* Economy */}
                <div className="bg-m-card">
                  <div className="px-4 py-2 border-b border-m-border">
                    <p className="label-tag text-m-green">ECONOMY</p>
                  </div>
                  <div className="divide-y divide-m-border">
                    <ColStat
                      label="TOTAL LOOT"
                      value={`$${selectedShell.loot.toLocaleString()}`}
                      color="yellow"
                    />
                    <ColStat
                      label="AVG LOOT/RUN"
                      value={`$${selectedShell.avg_loot.toLocaleString()}`}
                      color="yellow"
                    />
                    <ColStat label="EXFILTRATED" value={String(selectedShell.survived)} color="green" />
                    <ColStat
                      label="KIA"
                      value={String(selectedShell.runs - selectedShell.survived)}
                      color={selectedShell.runs - selectedShell.survived > 0 ? 'red' : undefined}
                    />
                  </div>
                </div>

                {/* Info */}
                <div className="bg-m-card">
                  <div className="px-4 py-2 border-b border-m-border">
                    <p className="label-tag text-m-green">INFO</p>
                  </div>
                  <div className="divide-y divide-m-border">
                    <ColStat label="FAVORITE WEAPON" value={selectedShell.favorite_weapon ?? '—'} />
                    <ColStat label="AVG RUN TIME" value={formatDuration(selectedShell.avg_time)} color="cyan" />
                    <ColStat label="TOTAL TIME" value={formatTime(selectedShell.time)} color="cyan" />
                  </div>
                </div>
              </div>
            </>
          )}
        </>
      )}
    </div>
  )
}

function StatBlock({
  label,
  value,
  color,
  accent,
}: {
  label: string
  value: string
  color?: 'green' | 'red' | 'yellow' | 'cyan'
  accent?: boolean
}) {
  const colorClass =
    {
      green: 'text-m-green',
      red: 'text-m-red',
      yellow: 'text-m-yellow',
      cyan: 'text-m-cyan',
    }[color as string] ?? 'text-m-text'

  return (
    <div className="bg-m-card p-5">
      <p className="label-tag text-m-text-muted">{label}</p>
      <p className={`text-2xl font-mono font-bold mt-1 ${colorClass}`}>{value}</p>
    </div>
  )
}

function ColStat({
  label,
  value,
  color,
}: {
  label: string
  value: string
  color?: 'green' | 'red' | 'yellow' | 'cyan'
}) {
  const c = color
    ? { green: 'text-m-green', red: 'text-m-red', yellow: 'text-m-yellow', cyan: 'text-m-cyan' }[color]
    : 'text-m-text'
  return (
    <div className="flex justify-between items-center px-4 py-2.5">
      <span className="label-tag text-m-text-muted">{label}</span>
      <span className={`text-xs font-mono font-bold ${c}`}>{value}</span>
    </div>
  )
}
