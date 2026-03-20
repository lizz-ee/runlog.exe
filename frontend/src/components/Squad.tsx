import { useEffect, useState } from 'react'
import { getSquadStats } from '../lib/api'

interface SquadMate {
  gamertag: string
  runs: number
  survived: number
  survival_rate: number
  survival_diff: number
  pve_kills: number
  pvp_kills: number
  kills: number
  deaths: number
  revives: number
  kd: number
  loot: number
  avg_loot: number
  avg_kills: number
  avg_time: number
  time: number
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

export default function Squad() {
  const [mates, setMates] = useState<SquadMate[]>([])
  const [selected, setSelected] = useState<string | null>(null)

  useEffect(() => {
    getSquadStats(7).then((data) => {
      setMates(data)
      if (data.length > 0) setSelected(data[0].gamertag)
    }).catch(console.error)
  }, [])

  const selectedMate = mates.find((m) => m.gamertag === selected)

  if (mates.length === 0) {
    return (
      <div className="max-w-7xl mx-auto space-y-4">
        <div>
          <p className="label-tag text-m-green">SYSTEM // SQUAD</p>
          <h2 className="text-xl font-display font-black tracking-wider text-m-text mt-1">SQUAD</h2>
        </div>
        <div className="border border-1 border-m-border bg-m-card p-10 text-center">
          <p className="text-xs text-m-text-muted tracking-wider">NO SQUAD DATA — PLAY SOME RUNS WITH CREW</p>
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-7xl mx-auto space-y-4">
      {/* Header */}
      <div>
        <p className="label-tag text-m-green">SYSTEM // SQUAD</p>
        <h2 className="text-xl font-display font-black tracking-wider text-m-text mt-1">SQUAD</h2>
      </div>

      {/* Squad mate cards */}
      <div className="grid grid-cols-7 gap-3">
        {mates.map((mate, i) => (
          <SquadCard
            key={mate.gamertag}
            mate={mate}
            rank={i + 1}
            isSelected={selected === mate.gamertag}
            onClick={() => setSelected(mate.gamertag)}
          />
        ))}
        {/* Fill empty slots */}
        {Array.from({ length: Math.max(0, 7 - mates.length) }).map((_, i) => (
          <div key={`empty-${i}`} className="aspect-[3/4] border border-m-border/20 bg-m-card/30 flex items-center justify-center">
            <span className="text-m-text-muted/10 text-[9px] tracking-[0.3em]">VACANT</span>
          </div>
        ))}
      </div>

      {/* Selected mate stats */}
      {selectedMate && (
        <>
          {/* Hero stats */}
          <div className="grid grid-cols-5 gap-[1px] bg-m-border">
            <StatBlock label="RUNS TOGETHER" value={String(selectedMate.runs)} accent />
            <StatBlock
              label="SURVIVAL RATE"
              value={`${selectedMate.survival_rate}%`}
              color={selectedMate.survival_rate >= 50 ? 'green' : 'red'}
            />
            <StatBlock
              label="VS OVERALL"
              value={`${selectedMate.survival_diff >= 0 ? '+' : ''}${selectedMate.survival_diff}%`}
              color={selectedMate.survival_diff >= 0 ? 'green' : 'red'}
            />
            <StatBlock label="K/D" value={selectedMate.kd.toFixed(2)} color={selectedMate.kd >= 1 ? 'green' : 'red'} />
            <StatBlock label="AVG LOOT" value={`$${selectedMate.avg_loot.toLocaleString()}`} color="yellow" />
          </div>

          {/* Detail columns */}
          <div className="grid grid-cols-3 gap-[1px] bg-m-border">
            <div className="bg-m-card">
              <div className="px-4 py-2 border-b border-m-border">
                <p className="label-tag text-m-green">OPERATIONS</p>
              </div>
              <div className="divide-y divide-m-border">
                <ColStat label="RUNS TOGETHER" value={String(selectedMate.runs)} />
                <ColStat label="EXFILTRATED" value={String(selectedMate.survived)} color="green" />
                <ColStat label="KIA" value={String(selectedMate.runs - selectedMate.survived)} color={selectedMate.runs - selectedMate.survived > 0 ? 'red' : undefined} />
                <ColStat label="AVG RUN TIME" value={formatDuration(selectedMate.avg_time)} color="cyan" />
                <ColStat label="TOTAL TIME" value={formatTime(selectedMate.time)} color="cyan" />
              </div>
            </div>
            <div className="bg-m-card">
              <div className="px-4 py-2 border-b border-m-border">
                <p className="label-tag text-m-green">COMBAT</p>
              </div>
              <div className="divide-y divide-m-border">
                <ColStat label="PVE KILLS" value={String(selectedMate.pve_kills)} color="green" />
                <ColStat label="RUNNER KILLS" value={String(selectedMate.pvp_kills)} color="cyan" />
                <ColStat label="TOTAL KILLS" value={String(selectedMate.kills)} />
                <ColStat label="DEATHS" value={String(selectedMate.deaths)} color={selectedMate.deaths > 0 ? 'red' : undefined} />
                <ColStat label="REVIVES" value={String(selectedMate.revives)} color={selectedMate.revives > 0 ? 'green' : undefined} />
              </div>
            </div>
            <div className="bg-m-card">
              <div className="px-4 py-2 border-b border-m-border">
                <p className="label-tag text-m-green">ECONOMY</p>
              </div>
              <div className="divide-y divide-m-border">
                <ColStat label="TOTAL LOOT" value={`$${selectedMate.loot.toLocaleString()}`} color="yellow" />
                <ColStat label="AVG LOOT/RUN" value={`$${selectedMate.avg_loot.toLocaleString()}`} color="yellow" />
                <ColStat label="AVG KILLS/RUN" value={String(selectedMate.avg_kills)} />
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  )
}

/* ── Squad Card ── */

function SquadCard({ mate, rank, isSelected, onClick }: {
  mate: SquadMate; rank: number; isSelected: boolean; onClick: () => void
}) {
  const rankStr = String(rank).padStart(2, '0')
  const [hovered, setHovered] = useState(false)
  const active = isSelected || hovered

  // Rarity colors based on rank: 1=gold, 2=purple, 3=blue, 4=green, 5-7=gray
  const rarityColor = rank === 1 ? '#FFD700' : rank === 2 ? '#A855F7' : rank === 3 ? '#3B82F6' : rank === 4 ? '#22C55E' : '#555'
  const rarityGlow = rank <= 4 ? `0 0 12px ${rarityColor}40` : 'none'

  return (
    <button
      onClick={onClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      className="relative aspect-[3/4] group focus:outline-none"
    >
      {/* Background */}
      <div className={`absolute inset-0 transition-all duration-300 ${
        isSelected
          ? 'bg-gradient-to-b from-[var(--rc)]/10 via-[var(--rc)]/5 to-transparent'
          : 'bg-m-card'
      }`} style={{ '--rc': rarityColor } as any} />

      {/* Rarity border */}
      <div className="absolute inset-0 border transition-all duration-300"
        style={{
          borderColor: active ? `${rarityColor}90` : `${rarityColor}30`,
          boxShadow: active ? rarityGlow : 'none',
        }} />

      {/* Scan line on hover/select */}
      <div className={`absolute inset-0 overflow-hidden pointer-events-none ${active ? 'opacity-100' : 'opacity-0'} transition-opacity`}>
        <div className="absolute top-0 left-0 right-0 h-[40px] bg-gradient-to-b to-transparent animate-[scanDown_2s_linear_infinite]"
          style={{ background: `linear-gradient(to bottom, ${rarityColor}15, transparent)` }} />
      </div>

      {/* Corner brackets — rarity colored */}
      <div className="absolute top-1 left-1 w-2.5 h-2.5 border-l border-t transition-colors duration-300"
        style={{ borderColor: active ? `${rarityColor}90` : `${rarityColor}25` }} />
      <div className="absolute top-1 right-1 w-2.5 h-2.5 border-r border-t transition-colors duration-300"
        style={{ borderColor: active ? `${rarityColor}90` : `${rarityColor}25` }} />
      <div className="absolute bottom-1 left-1 w-2.5 h-2.5 border-l border-b transition-colors duration-300"
        style={{ borderColor: active ? `${rarityColor}90` : `${rarityColor}25` }} />
      <div className="absolute bottom-1 right-1 w-2.5 h-2.5 border-r border-b transition-colors duration-300"
        style={{ borderColor: active ? `${rarityColor}90` : `${rarityColor}25` }} />

      {/* Selected top bar glow — rarity colored */}
      {isSelected && (
        <div className="absolute top-0 left-0 right-0 h-[2px] z-[4]"
          style={{ backgroundColor: rarityColor, boxShadow: `0 0 8px ${rarityColor}80` }} />
      )}

      {/* Content */}
      <div className="relative h-full flex flex-col p-3 z-10">

        {/* Rank — large faded background number, rarity colored */}
        <span className="absolute top-2 right-3 text-2xl font-display font-black transition-colors duration-300"
          style={{ color: `${rarityColor}${isSelected ? '25' : '10'}` }}>
          {rankStr}
        </span>

        {/* Status dot */}
        <div className="flex items-center gap-1.5">
          <div className={`w-1 h-1 rounded-full transition-all duration-300 ${
            isSelected
              ? 'bg-[#c8ff00] shadow-[0_0_6px_rgba(200,255,0,0.8)]'
              : mate.survival_rate >= 50 ? 'bg-[#c8ff00]/30' : 'bg-red-500/30'
          }`} />
          <span className={`text-[7px] tracking-[0.2em] transition-colors duration-300 ${
            isSelected ? 'text-[#c8ff00]/60' : 'text-[#c8ff00]/20'
          }`}>
            RUNNER
          </span>
        </div>

        {/* Gamertag — center */}
        <div className="flex-1 flex flex-col items-center justify-center">
          <span className={`font-mono font-bold tracking-wider text-center leading-tight transition-all duration-300 truncate max-w-full px-1 ${
            isSelected
              ? 'text-[#c8ff00] drop-shadow-[0_0_8px_rgba(200,255,0,0.3)]'
              : 'text-m-text group-hover:text-[#c8ff00]/80'
          }`} style={{ fontSize: mate.gamertag.split('#')[0].length > 14 ? '8px' : mate.gamertag.split('#')[0].length > 10 ? '9px' : '11px' }}>
            {mate.gamertag.split('#')[0]}
          </span>
          {mate.gamertag.includes('#') && (
            <span className={`text-[7px] font-mono mt-0.5 transition-colors duration-300 ${
              isSelected ? 'text-[#c8ff00]/40' : 'text-m-text-muted/40'
            }`}>
              #{mate.gamertag.split('#')[1]}
            </span>
          )}
        </div>

        {/* Divider line with glow */}
        <div className={`w-full h-px mb-2 transition-all duration-300 ${
          active
            ? 'bg-gradient-to-r from-transparent via-[#c8ff00]/40 to-transparent'
            : 'bg-gradient-to-r from-transparent via-[#c8ff00]/10 to-transparent'
        }`} />

        {/* Bottom stats */}
        <div className="space-y-1.5">
          <div className="flex justify-between items-center">
            <span className="text-[7px] tracking-[0.15em] text-m-text-muted/60">OPS</span>
            <span className={`text-[10px] font-mono font-bold transition-colors duration-300 ${
              isSelected ? 'text-m-text' : 'text-m-text/70'
            }`}>{mate.runs}</span>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-[7px] tracking-[0.15em] text-m-text-muted/60">SURV</span>
            <span className={`text-[10px] font-mono font-bold ${
              mate.survival_rate >= 50 ? 'text-[#c8ff00]' : 'text-red-400'
            }`}>
              {mate.survival_rate}%
            </span>
          </div>
          {/* Survival micro bar — rarity colored */}
          <div className="w-full h-[3px] bg-[#ffffff05] rounded-full overflow-hidden">
            <div
              className="h-full rounded-full transition-all duration-500"
              style={{
                width: `${Math.min(100, Math.max(5, 50 + mate.survival_diff))}%`,
                backgroundColor: mate.survival_diff >= 0 ? `${rarityColor}60` : '#f8717160',
              }}
            />
          </div>
        </div>
      </div>

    </button>
  )
}

/* ── Shared stat components ── */

function StatBlock({ label, value, color, accent }: { label: string; value: string; color?: 'green' | 'red' | 'yellow' | 'cyan'; accent?: boolean }) {
  const colorClass = { green: 'text-m-green', red: 'text-m-red', yellow: 'text-m-yellow', cyan: 'text-m-cyan' }[color as string] ?? 'text-m-text'
  return (
    <div className="bg-m-card p-5">
      <p className="label-tag text-m-text-muted">{label}</p>
      <p className={`text-2xl font-mono font-bold mt-1 ${colorClass}`}>{value}</p>
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
