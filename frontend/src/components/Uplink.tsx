import { useEffect, useState, useRef, useCallback } from 'react'
import axios from 'axios'
import { apiBase } from '../lib/api'
import { useStore } from '../lib/store'
import { LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, ResponsiveContainer, Area, AreaChart } from 'recharts'

interface SessionSummary {
  session_id: number
  session_code?: string
  date: string | null
  run_count: number
  survived?: number
  survival_rate?: number
  total_runner_kills?: number
  total_pve_kills?: number
  total_deaths?: number
  total_revives?: number
  total_loot?: number
  total_time_minutes?: number
  avg_runner_kills_per_run?: number
  avg_pve_kills_per_run?: number
}

interface TrendPoint {
  label: string
  value: number
  run_count?: number
  date?: string
}

// ═══════════════════════════════════════════════════════
// CRT TERMINAL STYLES — shared across all UPLINK panels
// ═══════════════════════════════════════════════════════
const CRT_BG = '#030306'
const CRT_SCANLINES = {
  backgroundImage: 'repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(200,255,0,0.025) 2px, rgba(200,255,0,0.025) 3px)',
}
const CRT_VIGNETTE = {
  boxShadow: 'inset 0 0 60px rgba(0,0,0,0.5), inset 0 0 120px rgba(0,0,0,0.3)',
}
const PHOSPHOR_GLOW = {
  textShadow: '0 0 8px rgba(200,255,0,0.15)',
}

export default function Uplink() {
  const [summary, setSummary] = useState<SessionSummary | null>(null)
  const { uplinkMessages: messages, setUplinkMessages: setMessages, uplinkBriefing: briefing, setUplinkBriefing: setBriefing } = useStore()
  const [briefingLoading, setBriefingLoading] = useState(false)
  const [survivalTrend, setSurvivalTrend] = useState<TrendPoint[]>([])
  const [lootTrend, setLootTrend] = useState<TrendPoint[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [totalRuns, setTotalRuns] = useState(0)
  const chatRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const briefingRunCount = useRef(0)

  useEffect(() => {
    axios.get(`${apiBase}/api/uplink/session-summary`).then(({ data }) => setSummary(data)).catch(() => {})
    axios.get(`${apiBase}/api/uplink/trends?stat=survival&range=all&group_by=session`).then(({ data }) => setSurvivalTrend(data)).catch(() => {})
    axios.get(`${apiBase}/api/uplink/trends?stat=loot&range=all&group_by=session`).then(({ data }) => setLootTrend(data)).catch(() => {})
    axios.get(`${apiBase}/api/runs/recent`).then(({ data }) => setTotalRuns(data.length)).catch(() => {})
  }, [])

  useEffect(() => {
    const currentRuns = summary?.run_count ?? 0
    if (briefingLoading) return
    if (briefing && currentRuns === briefingRunCount.current) return
    briefingRunCount.current = currentRuns
    if (currentRuns === 0 && briefing) return
    setBriefingLoading(true)
    setBriefing(null)

    fetch(`${apiBase}/api/uplink/briefing`, { method: 'POST' })
      .then(async (response) => {
        const reader = response.body?.getReader()
        if (!reader) return
        const decoder = new TextDecoder()
        let fullText = ''
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          const chunk = decoder.decode(value)
          for (const line of chunk.split('\n')) {
            if (line.startsWith('data: ')) {
              const payload = line.slice(6)
              if (payload === '[DONE]') continue
              try { fullText += JSON.parse(payload).text || ''; setBriefing(fullText) } catch {}
            }
          }
        }
        setBriefingLoading(false)
      }).catch(() => setBriefingLoading(false))
  }, [summary?.run_count])

  const sendMessage = useCallback(async () => {
    if (!input.trim() || streaming) return
    const userMsg = input.trim()
    setInput('')
    const newMessages = [...messages, { role: 'user' as const, content: userMsg }]
    setMessages(newMessages)
    setStreaming(true)
    try {
      const response = await fetch(`${apiBase}/api/uplink/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: userMsg, history: messages.map(m => ({ role: m.role, content: m.content })) }),
      })
      const reader = response.body?.getReader()
      if (!reader) return
      const decoder = new TextDecoder()
      let aiText = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        const chunk = decoder.decode(value)
        for (const line of chunk.split('\n')) {
          if (line.startsWith('data: ')) {
            const payload = line.slice(6)
            if (payload === '[DONE]') continue
            try { aiText += JSON.parse(payload).text || ''; setMessages([...newMessages, { role: 'assistant', content: aiText }]) } catch {}
          }
        }
      }
    } catch { setMessages([...newMessages, { role: 'assistant', content: 'SIGNAL LOST — RECONNECTING...' }]) }
    setStreaming(false)
    setTimeout(() => inputRef.current?.focus(), 50)
  }, [input, messages, streaming])

  useEffect(() => { chatRef.current && (chatRef.current.scrollTop = chatRef.current.scrollHeight) }, [messages])

  const hasSessionData = summary && summary.run_count > 0

  return (
    <div className="max-w-7xl mx-auto h-full flex flex-col">
      {/* ═══ HEADER ═══ */}
      <div className="mb-4">
        <p className="label-tag text-m-green">LIVE // UPLINK</p>
        <h2 className="text-xl font-display font-black tracking-wider text-m-text mt-1">
          UPLINK
        </h2>
      </div>

      {/* ═══ TWO-COLUMN LAYOUT ═══ */}
      <div className="flex gap-4 flex-1 min-h-0">

        {/* ═══════════════════════════════════════ */}
        {/* LEFT COLUMN — 60% intel panels         */}
        {/* ═══════════════════════════════════════ */}
        <div className="w-[60%] overflow-y-auto space-y-3 pr-1">

          {/* ─── SESSION DEBRIEF — stat blocks ─── */}
          <div className="relative overflow-hidden">
            <div className="grid grid-cols-6 gap-px relative z-10">
              {hasSessionData ? (
                <>
                  <HexStat label="RUNS" value={String(summary!.run_count)} sub="SESSION" />
                  <HexStat label="SURV%" value={`${summary!.survival_rate ?? 0}%`} sub={`${summary!.survived ?? 0}/${summary!.run_count}`}
                    color={(summary!.survival_rate ?? 0) >= 50 ? '#c8ff00' : '#ff4444'} />
                  <HexStat label="R.KILL" value={String(summary!.total_runner_kills ?? 0)} sub={`${summary!.avg_runner_kills_per_run ?? 0}/RUN`} />
                  <HexStat label="PVE" value={String(summary!.total_pve_kills ?? 0)} sub={`${summary!.avg_pve_kills_per_run ?? 0}/RUN`} />
                  <HexStat label="REVIVE" value={String(summary!.total_revives ?? 0)} sub="CREW" color="#c8ff00" />
                  <HexStat label="LOOT" value={`$${(summary!.total_loot ?? 0).toLocaleString()}`} sub="EXTRACTED" color="#ffcc00" />
                </>
              ) : (
                <>
                  <HexStat label="RUNS" value="—" sub="SESSION" />
                  <HexStat label="SURV%" value="—" sub="—/—" />
                  <HexStat label="R.KILL" value="—" sub="—/RUN" />
                  <HexStat label="PVE" value="—" sub="—/RUN" />
                  <HexStat label="REVIVE" value="—" sub="CREW" />
                  <HexStat label="LOOT" value="$—" sub="PENDING" />
                </>
              )}
            </div>
          </div>

          {/* ─── BRIEFING — grey card with green accents ─── */}
          <div className="bg-m-card border border-m-border relative overflow-hidden">
            {/* Corner bracket accents */}
            <div className="absolute top-0 left-0 w-4 h-4 border-t-2 border-l-2 border-m-green/30 z-10" />
            <div className="absolute top-0 right-0 w-4 h-4 border-t-2 border-r-2 border-m-green/30 z-10" />
            <div className="absolute bottom-0 left-0 w-4 h-4 border-b-2 border-l-2 border-m-green/30 z-10" />
            <div className="absolute bottom-0 right-0 w-4 h-4 border-b-2 border-r-2 border-m-green/30 z-10" />
            {/* Subtle scanline overlay */}
            <div className="absolute inset-0 opacity-[0.015] pointer-events-none"
              style={{ backgroundImage: 'repeating-linear-gradient(0deg, transparent, transparent 3px, rgba(200,255,0,0.3) 3px, rgba(200,255,0,0.3) 4px)' }} />

            <div className="px-5 py-3 flex justify-between border-b border-m-border">
              <span className="label-tag text-m-green">
                BRIEFING // {summary?.session_code || ':??:'}
              </span>
              <span className="label-tag text-m-text-muted">
                {summary?.date?.replace(/-/g, '.') || ''}
              </span>
            </div>

            <div className="px-5 py-4 min-h-[80px]">
              {briefingLoading && !briefing ? (
                <div className="space-y-2.5">
                  <div className="h-2.5 bg-[#0a0a12] w-[85%] animate-pulse" />
                  <div className="h-2.5 bg-[#080810] w-[65%] animate-pulse" />
                  <div className="h-2.5 bg-[#0a0a12] w-[75%] animate-pulse" />
                </div>
              ) : briefing ? (
                <div className="text-xs font-mono text-m-text leading-relaxed whitespace-pre-wrap">
                  {briefing.split('\n').map((line, i) => {
                    if (!line.trim()) return <div key={i} className="h-2" />
                    if (line.includes('TREND:')) return <p key={i} className="text-m-cyan mt-2">{line}</p>
                    if (line.includes('ALERT:')) return <p key={i} className="text-m-yellow mt-2">{line}</p>
                    return <p key={i}>{line}</p>
                  })}
                </div>
              ) : (
                <p className="text-[10px] font-mono text-m-text-muted">
                  AWAITING OPERATIONAL DATA, RUNNER.
                </p>
              )}
            </div>
          </div>

          {/* ─── TREND CHARTS — oscilloscope style ─── */}
          <TrendPanel title="TRENDS // SURVIVAL.RATE" data={survivalTrend} domain={[0, 100]} suffix="%" />
          <TrendPanel title="TRENDS // LOOT.EXTRACTED" data={lootTrend} prefix="$" />
        </div>

        {/* ═══════════════════════════════════════ */}
        {/* RIGHT COLUMN — 40% CRT terminal        */}
        {/* ═══════════════════════════════════════ */}
        <div className="w-[40%] flex flex-col relative overflow-hidden border border-m-green/10"
          style={{ background: `radial-gradient(ellipse at center, #080812 0%, ${CRT_BG} 70%)` }}>
          {/* CRT effects */}
          <div className="absolute inset-0 pointer-events-none z-10" style={CRT_SCANLINES} />
          <div className="absolute inset-0 pointer-events-none z-10" style={CRT_VIGNETTE} />

          {/* Terminal header bar — grey card */}
          <div className="px-4 py-2 bg-m-card border-b border-m-border relative z-20 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className={`w-1.5 h-1.5 rounded-full ${streaming ? 'bg-m-green animate-pulse' : 'bg-m-green/40'}`} />
              <span className="text-[8px] font-mono text-m-green/60 tracking-[0.25em]">COMMS.UPLINK</span>
            </div>
            <span className="text-[7px] font-mono tracking-[0.2em]" style={{ color: streaming ? 'rgba(200,255,0,0.6)' : 'rgba(200,255,0,0.2)' }}>
              {streaming ? '> TRANSMITTING' : '> STANDBY'}
            </span>
          </div>

          {/* Terminal output area */}
          <div ref={chatRef} className="flex-1 overflow-y-auto px-4 py-3 space-y-4 relative z-20">
            {messages.length === 0 && !streaming && (
              <div className="flex items-center justify-center h-full">
                <div className="text-center space-y-4">
                  <div className="text-[10px] font-mono tracking-[0.4em] text-m-green/40 animate-pulse">
                    UPLINK ACTIVE
                  </div>
                  <div className="text-[9px] font-mono text-m-text-muted/30 tracking-[0.15em]">
                    AWAITING QUERY, RUNNER.
                  </div>
                  <div className="text-m-green/30 text-lg animate-pulse">_</div>
                </div>
              </div>
            )}

            {messages.map((msg, i) => (
              <div key={i}>
                {msg.role === 'user' ? (
                  <div className="text-right">
                    <span className="text-[7px] font-mono text-m-green/25 tracking-[0.2em] block mb-1">RUNNER //</span>
                    <p className="inline-block text-[11px] font-mono text-m-text/80 leading-relaxed whitespace-pre-wrap text-right border-r border-m-green/20 pr-3 max-w-[90%]">
                      {msg.content}
                    </p>
                  </div>
                ) : (
                  <div>
                    <span className="text-[7px] font-mono text-m-green/35 tracking-[0.2em] block mb-1">// UPLINK</span>
                    <p className="text-[11px] font-mono text-m-text/90 leading-[1.8] whitespace-pre-wrap max-w-[95%]">
                      {msg.content}
                      {streaming && i === messages.length - 1 && (
                        <span className="inline-block w-2 h-3.5 bg-m-green/60 ml-0.5 animate-pulse" />
                      )}
                    </p>
                  </div>
                )}
              </div>
            ))}

            {streaming && (messages.length === 0 || messages[messages.length - 1]?.role === 'user') && (
              <div>
                <span className="text-[7px] font-mono text-m-green/35 tracking-[0.2em] block mb-1">// UPLINK</span>
                <span className="inline-block w-2 h-3.5 bg-m-green/60 animate-pulse" />
              </div>
            )}
          </div>

          {/* Terminal input — grey card */}
          <div className="px-4 py-2.5 bg-m-card border-t border-m-border relative z-20">
            <div className="flex items-center gap-2">
              <span className="text-m-green/40 font-mono text-[10px]">&gt;&gt;</span>
              <input
                ref={inputRef}
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && sendMessage()}
                placeholder="query uplink..."
                disabled={streaming}
                className="flex-1 bg-transparent text-[11px] font-mono text-m-text placeholder:text-m-text-muted/30 focus:outline-none disabled:opacity-30"
                style={{ caretColor: '#c8ff00' }}
              />
              <button onClick={sendMessage} disabled={streaming || !input.trim()}
                className="text-[9px] font-mono tracking-[0.2em] disabled:opacity-15 hover:text-m-green transition-all"
                style={{ color: 'rgba(200,255,0,0.4)' }}>
                SEND
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════
// HEX STAT BLOCK — session debrief numbers
// ═══════════════════════════════════════════════════════
function HexStat({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div className="px-3 py-3 relative bg-m-card">
      <p className="text-[7px] font-mono tracking-[0.2em] mb-1 text-m-text-muted">{label}</p>
      <p className="text-xl font-mono font-bold" style={{ color: color || '#e0e0e8' }}>
        {value}
      </p>
      {sub && <p className="text-[7px] font-mono mt-0.5 text-m-text-muted/50">{sub}</p>}
    </div>
  )
}

// ═══════════════════════════════════════════════════════
// TREND PANEL — oscilloscope-style chart
// ═══════════════════════════════════════════════════════
function TrendPanel({ title, data, domain, suffix, prefix }: {
  title: string; data: TrendPoint[]; domain?: [number, number]; suffix?: string; prefix?: string
}) {
  const hasData = data.length > 1
  return (
    <div>
      {/* Header outside card — like PIPELINE.STATUS in detect.exe */}
      <div className="flex justify-between items-center mb-1.5">
        <span className="label-tag text-m-text-muted">{title}</span>
        {hasData && (
          <span className="text-[7px] font-mono text-m-text-muted/40 tracking-wider">
            {data.length} DATAPOINTS
          </span>
        )}
      </div>

      <div className="bg-m-card border border-m-border" style={{ height: 180 }}>
        {hasData ? (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data} margin={{ top: 5, right: 15, bottom: -10, left: -15 }}>
              <defs>
                <linearGradient id={`grad-${title.replace(/\s/g, '')}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#c8ff00" stopOpacity={0.15} />
                  <stop offset="100%" stopColor="#c8ff00" stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#1a1a2e" />
              <XAxis dataKey="label" tick={{ fontSize: 8, fill: '#555', fontFamily: 'monospace' }} axisLine={{ stroke: '#1a1a2e' }} tickLine={false} />
              <YAxis domain={domain} tick={{ fontSize: 8, fill: '#555', fontFamily: 'monospace' }} axisLine={{ stroke: '#1a1a2e' }} tickLine={false}
                tickFormatter={v => `${prefix || ''}${v}${suffix || ''}`} />
              <Tooltip
                contentStyle={{ background: '#0a0a0f', border: '1px solid #1a1a2e', fontSize: 10, fontFamily: 'monospace' }}
                labelStyle={{ color: '#777' }}
                formatter={(v: number) => [`${prefix || ''}${v}${suffix || ''}`, '']}
              />
              <Area type="monotone" dataKey="value" stroke="#c8ff00" strokeWidth={2} fill={`url(#grad-${title.replace(/\s/g, '')})`}
                dot={{ r: 3, fill: '#c8ff00', stroke: '#c8ff00', strokeWidth: 1 }}
                activeDot={{ r: 5, fill: '#c8ff00', stroke: '#050508', strokeWidth: 2 }} />
            </AreaChart>
          </ResponsiveContainer>
        ) : (
          <div className="h-full relative">
            <div className="absolute inset-0 opacity-[0.04]" style={{
              backgroundImage: 'linear-gradient(to right, rgba(200,255,0,0.3) 1px, transparent 1px), linear-gradient(to bottom, rgba(200,255,0,0.3) 1px, transparent 1px)',
              backgroundSize: '20% 25%',
            }} />
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="text-center space-y-2">
                <p className="text-[8px] font-mono text-m-text-muted/20 tracking-[0.3em]">// AWAITING SIGNAL //</p>
                <p className="text-[7px] font-mono text-m-text-muted/10 tracking-widest">0x4E554C4C // DATA.STREAM.PENDING</p>
              </div>
            </div>
            <div className="absolute left-3 top-2 text-[7px] font-mono text-m-text-muted/15">100%</div>
            <div className="absolute left-3 bottom-2 text-[7px] font-mono text-m-text-muted/15">0%</div>
          </div>
        )}
      </div>
    </div>
  )
}
