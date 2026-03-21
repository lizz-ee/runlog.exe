import { useEffect, useState } from 'react'
import { getSquadStats } from '../lib/api'
import { useStore } from '../lib/store'

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

  const { captureStatus } = useStore()
  const lastRunId = captureStatus?.last_result?.run_id
  const doneCount = captureStatus?.processing_items?.filter(i => i.status === 'done').length ?? 0

  useEffect(() => {
    getSquadStats(7).then((data) => {
      setMates(data)
      if (!selected && data.length > 0) setSelected(data[0].gamertag)
    }).catch(() => {})
  }, [lastRunId, doneCount])

  const selectedMate = mates.find((m) => m.gamertag === selected)

  if (mates.length === 0) {
    return (
      <div className="max-w-7xl mx-auto space-y-4">
        <div>
          <p className="label-tag text-m-green"></p>
          <h2 className="text-xl font-display font-black tracking-wider text-m-text mt-1">RUNNERS</h2>
        </div>
        <div className="border border-1 border-m-border bg-m-card p-10 text-center">
          <p className="text-xs text-m-text-muted tracking-wider">NO RUNNER DATA — PLAY SOME RUNS WITH CREW</p>
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-7xl mx-auto space-y-4">
      {/* Header */}
      <div>
        <h2 className="text-xl font-display font-black tracking-wider text-m-text">RUNNERS</h2>
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
            <StatBlock label="RUNS" value={String(selectedMate.runs)} accent />
            <StatBlock
              label="SURVIVAL RATE"
              value={`${selectedMate.survival_rate}%`}
              color={selectedMate.survival_rate >= 50 ? 'green' : 'red'}
            />
            <StatBlock label="K/D" value={selectedMate.kd.toFixed(2)} color={selectedMate.kd >= 1 ? 'green' : 'red'} />
            <StatBlock label="AVG LOOT" value={`$${selectedMate.avg_loot.toLocaleString()}`} color="yellow" />
            <StatBlock label="TOTAL TIME" value={formatTime(selectedMate.time)} color="cyan" />
          </div>

          {/* Detail columns — COMBAT, ECONOMY, OPERATIONS */}
          <div className="grid grid-cols-3 gap-[1px] bg-m-border">
            <div className="bg-m-card">
              <div className="px-4 py-2 border-b border-m-border">
                <p className="label-tag text-m-green">COMBAT</p>
              </div>
              <div className="divide-y divide-m-border">
                <ColStat label="PVE KILLS" value={String(selectedMate.pve_kills)} color="green" />
                <ColStat label="RUNNER KILLS" value={String(selectedMate.pvp_kills)} color="cyan" />
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
                <ColStat label="EXFILTRATED" value={String(selectedMate.survived)} color="green" />
              </div>
            </div>
            <div className="bg-m-card">
              <div className="px-4 py-2 border-b border-m-border">
                <p className="label-tag text-m-green">OPERATIONS</p>
              </div>
              <div className="divide-y divide-m-border">
                <ColStat label="RUNS TOGETHER" value={String(selectedMate.runs)} />
                <ColStat label="AVG RUN TIME" value={formatDuration(selectedMate.avg_time)} color="cyan" />
                <ColStat label="TOTAL TIME" value={formatTime(selectedMate.time)} color="cyan" />
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
  const active = isSelected

  // Rarity colors based on rank: 1=gold, 2=purple, 3=blue, 4=green, 5-7=gray
  const rarityColor = rank === 1 ? '#FFD700' : rank === 2 ? '#A855F7' : rank === 3 ? '#3B82F6' : rank === 4 ? '#22C55E' : '#888888'
  const rarityGlow = 'none'

  return (
    <button
      onClick={onClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      className="relative aspect-[3/4] group focus:outline-none"
    >
      {/* Background — dark, only gradient on selected */}
      <div className="absolute inset-0 bg-m-card" />
      {isSelected && (
        <div className="absolute inset-0 bg-gradient-to-b from-[var(--rc)]/8 via-transparent to-transparent"
          style={{ '--rc': rarityColor } as any} />
      )}

      {/* Border — identical for all cards, only rarityColor differs */}
      <div className="absolute inset-0 transition-all duration-300"
        style={{
          border: isSelected ? `1px solid ${rarityColor}60` : `1px solid ${rarityColor}20`,
        }} />


      {/* Corner brackets — exact same as ShellCard (1.5 inset, 3px size) */}
      <div className="absolute top-1.5 left-1.5 w-3 h-3 border-l border-t z-[3] transition-colors duration-300"
        style={{ borderColor: isSelected ? `${rarityColor}90` : `${rarityColor}15` }} />
      <div className="absolute top-1.5 right-1.5 w-3 h-3 border-r border-t z-[3] transition-colors duration-300"
        style={{ borderColor: isSelected ? `${rarityColor}90` : `${rarityColor}15` }} />
      <div className="absolute bottom-1.5 left-1.5 w-3 h-3 border-l border-b z-[3] transition-colors duration-300"
        style={{ borderColor: isSelected ? `${rarityColor}90` : `${rarityColor}15` }} />
      <div className="absolute bottom-1.5 right-1.5 w-3 h-3 border-r border-b z-[3] transition-colors duration-300"
        style={{ borderColor: isSelected ? `${rarityColor}90` : `${rarityColor}15` }} />

      {/* Selected top bar — exact same as ShellCard */}
      {isSelected && (
        <div className="absolute top-0 left-0 right-0 h-[2px] z-[4]"
          style={{ backgroundColor: rarityColor, boxShadow: `0 0 8px ${rarityColor}80` }} />
      )}

      {/* Content — same structure as ShellCard */}
      <div className="absolute inset-0 z-[3] flex flex-col p-3">

        {/* Status dot — same as ShellCard */}
        <div className="flex items-center gap-1.5">
          <div className={`w-1 h-1 rounded-full transition-all duration-300 ${
            isSelected
              ? 'bg-[#c8ff00] shadow-[0_0_6px_rgba(200,255,0,0.8)]'
              : mate.survival_rate >= 50 ? 'bg-[#c8ff00]/30' : 'bg-red-500/30'
          }`} />
          <span className={`text-[7px] tracking-[0.2em] transition-colors duration-300 ${
            isSelected ? 'text-[#c8ff00]/60' : 'text-[#c8ff00]/15'
          }`}>
            RUNNER
          </span>
        </div>

        {/* Rank badge — same position/size as ShellCard */}
        <span className="absolute top-2.5 right-3 text-lg font-display font-black z-[3] transition-colors duration-300"
          style={{ color: `${rarityColor}${isSelected ? '25' : '10'}` }}>
          {rankStr}
        </span>

        <div className="flex-1" />

        {/* Divider — same as ShellCard */}
        <div className={`w-full h-px mb-2 transition-all duration-300 ${
          isSelected
            ? 'bg-gradient-to-r from-transparent via-[#c8ff00]/40 to-transparent'
            : 'bg-gradient-to-r from-transparent via-[#c8ff00]/10 to-transparent'
        }`} />

        {/* Gamertag — where shell name is */}
        <span className={`tracking-[0.15em] font-bold uppercase transition-all duration-300 truncate max-w-full block ${
          isSelected
            ? 'text-[#c8ff00] drop-shadow-[0_0_8px_rgba(200,255,0,0.3)] animate-rgb-split'
            : 'text-m-text group-hover:text-m-cyan'
        }`} style={{ fontSize: mate.gamertag.split('#')[0].length > 16 ? '7px' : mate.gamertag.split('#')[0].length > 12 ? '9px' : '12px' }}>
          {mate.gamertag.split('#')[0]}
        </span>
        {mate.gamertag.includes('#') && (
          <span className={`text-[7px] font-mono transition-colors duration-300 ${
            isSelected ? 'text-[#c8ff00]/40' : 'text-m-text-muted/40'
          }`}>
            #{mate.gamertag.split('#')[1]}
          </span>
        )}

        {/* Stats — same as ShellCard: runs + surv% inline */}
        <div className="flex gap-3 mt-1">
          <span className="text-[8px] font-mono text-m-text-muted">{mate.runs} RUNS</span>
          <span className={`text-[8px] font-mono ${
            mate.survival_rate >= 50 ? 'text-[#c8ff00]' : 'text-red-400'
          }`}>
            {mate.survival_rate}%
          </span>
        </div>

        {/* Survival micro bar — same as ShellCard */}
        <div className="w-full h-[3px] bg-[#ffffff05] rounded-full overflow-hidden mt-1.5">
          <div
            className={`h-full rounded-full transition-all duration-500 ${
              mate.survival_rate >= 50 ? 'bg-[#c8ff00]/40' : 'bg-red-400/40'
            }`}
            style={{ width: `${Math.max(3, mate.survival_rate)}%` }}
          />
        </div>
      </div>

    </button>
  )
}

/* ── Scan effect — full top-to-bottom, random speed each cycle ── */
function ScanEffect({ color }: { color: string }) {
  const [duration, setDuration] = useState(() => 5 + Math.random() * 6)
  const [key, setKey] = useState(0)

  useEffect(() => {
    const timer = setTimeout(() => {
      setDuration(5 + Math.random() * 6)
      setKey(k => k + 1)
    }, duration * 1000)
    return () => clearTimeout(timer)
  }, [key, duration])

  return (
    <div className="absolute inset-0 overflow-hidden pointer-events-none z-[2]">
      <div
        key={key}
        className="absolute left-0 right-0 h-[30px]"
        style={{
          background: `linear-gradient(to bottom, ${color}12, transparent)`,
          animation: `scanDown ${duration}s linear`,
          top: 0,
        }}
      />
    </div>
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
