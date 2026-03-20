import { useEffect, useState, useRef, useCallback } from 'react'
import axios from 'axios'
import { apiBase } from '../lib/api'
import { useStore } from '../lib/store'
import { LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, ResponsiveContainer } from 'recharts'

interface SessionSummary {
  session_id: number
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
  maps_played?: string[]
  shells_used?: string[]
  best_run?: { grade: string; map: string; kills: number; loot: number }
}

interface TrendPoint {
  label: string
  value: number
  run_count?: number
  date?: string
}

interface ChatMsg {
  role: 'user' | 'assistant'
  content: string
}

export default function Uplink() {
  const [summary, setSummary] = useState<SessionSummary | null>(null)
  const { uplinkMessages: messages, setUplinkMessages: setMessages, uplinkBriefing: briefing, setUplinkBriefing: setBriefing } = useStore()
  const [briefingLoading, setBriefingLoading] = useState(false)
  const [survivalTrend, setSurvivalTrend] = useState<TrendPoint[]>([])
  const [lootTrend, setLootTrend] = useState<TrendPoint[]>([])
  const [trendMap, setTrendMap] = useState('all')
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [totalRuns, setTotalRuns] = useState(0)
  const chatRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // Load session summary + trends on mount
  useEffect(() => {
    axios.get(`${apiBase}/api/uplink/session-summary`).then(({ data }) => {
      setSummary(data)
    }).catch(() => {})

    axios.get(`${apiBase}/api/uplink/trends?stat=survival&range=all&group_by=session`).then(({ data }) => {
      setSurvivalTrend(data)
    }).catch(() => {})

    axios.get(`${apiBase}/api/uplink/trends?stat=loot&range=all&group_by=session`).then(({ data }) => {
      setLootTrend(data)
    }).catch(() => {})

    // Check total runs for empty state
    axios.get(`${apiBase}/api/runs/recent`).then(({ data }) => {
      setTotalRuns(data.length)
    }).catch(() => {})
  }, [])

  // Auto-generate briefing when session data changes
  const briefingRunCount = useRef(0)
  useEffect(() => {
    const currentRuns = summary?.run_count ?? 0
    // Skip if already have briefing for this run count, or loading
    if (briefingLoading) return
    if (briefing && currentRuns === briefingRunCount.current) return
    // Update tracking
    briefingRunCount.current = currentRuns
    if (currentRuns === 0 && briefing) return  // Don't re-fetch if no new runs
    setBriefingLoading(true)
    setBriefing(null)  // Clear old briefing

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
          // Parse SSE data lines
          for (const line of chunk.split('\n')) {
            if (line.startsWith('data: ')) {
              const payload = line.slice(6)
              if (payload === '[DONE]') continue
              try {
                const parsed = JSON.parse(payload)
                fullText += parsed.text || ''
                setBriefing(fullText)
              } catch {}
            }
          }
        }
        setBriefingLoading(false)
      })
      .catch(() => setBriefingLoading(false))
  }, [summary?.run_count])

  // Send chat message
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
        body: JSON.stringify({
          message: userMsg,
          history: messages.map(m => ({ role: m.role, content: m.content })),
        }),
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
            try {
              const parsed = JSON.parse(payload)
              aiText += parsed.text || ''
              setMessages([...newMessages, { role: 'assistant', content: aiText }])
            } catch {}
          }
        }
      }
    } catch (e) {
      setMessages([...newMessages, { role: 'assistant', content: 'UPLINK ERROR — Connection lost.' }])
    }
    setStreaming(false)
    // Refocus input so user can keep typing
    setTimeout(() => inputRef.current?.focus(), 50)
  }, [input, messages, streaming])

  // Auto-scroll chat
  useEffect(() => {
    if (chatRef.current) {
      chatRef.current.scrollTop = chatRef.current.scrollHeight
    }
  }, [messages])

  const hasSessionData = summary && summary.run_count > 0
  const hasAnyData = totalRuns > 0

  return (
    <div className="max-w-7xl mx-auto h-full flex flex-col">
      {/* Header */}
      <div className="mb-4">
        <p className="label-tag text-m-green">LIVE // UPLINK</p>
        <h2 className="text-xl font-display font-black tracking-wider text-m-text mt-1">UPLINK</h2>
      </div>

      {/* Two-column layout */}
      <div className="flex gap-5 flex-1 min-h-0">
        {/* LEFT COLUMN — 60% scrollable */}
        <div className="w-[60%] overflow-y-auto space-y-4 pr-2">
          {/* Session debrief — hero stats */}
          <div className="grid grid-cols-5 gap-[1px] bg-m-border">
            {hasSessionData ? (
              <>
                <StatBlock label="RUNS" value={String(summary!.run_count)} sub="session" />
                <StatBlock label="SURVIVAL" value={`${summary!.survival_rate ?? 0}%`}
                  sub={`${summary!.survived ?? 0} of ${summary!.run_count}`}
                  color={(summary!.survival_rate ?? 0) >= 50 ? 'green' : 'red'} />
                <StatBlock label="R.KILLS" value={String(summary!.total_runner_kills ?? 0)}
                  sub={`${summary!.avg_runner_kills_per_run ?? 0}/run`} />
                <StatBlock label="PVE" value={String(summary!.total_pve_kills ?? 0)}
                  sub={`${summary!.avg_pve_kills_per_run ?? 0}/run`} />
                <StatBlock label="LOOT" value={`$${(summary!.total_loot ?? 0).toLocaleString()}`}
                  sub="extracted" color="yellow" />
              </>
            ) : (
              <>
                <StatBlock label="RUNS" value="—" sub="session" />
                <StatBlock label="SURVIVAL" value="—%" sub="— of —" />
                <StatBlock label="R.KILLS" value="—" sub="—/run" />
                <StatBlock label="PVE" value="—" sub="—/run" />
                <StatBlock label="LOOT" value="$—" sub="awaiting" />
              </>
            )}
          </div>

          {/* Briefing */}
          <div className="bg-m-card border border-m-border relative overflow-hidden">
            {/* Scanline effect */}
            <div className="absolute inset-0 opacity-[0.02] pointer-events-none"
              style={{ backgroundImage: 'repeating-linear-gradient(0deg, transparent, transparent 3px, rgba(200,255,0,0.4) 3px, rgba(200,255,0,0.4) 4px)' }} />

            <div className="px-4 py-3 border-b border-m-border flex justify-between relative z-10">
              <span className="label-tag text-m-text-muted">
                BRIEFING // {(summary as any)?.session_code || ':??:'}
              </span>
              <span className="label-tag text-m-text-muted">
                {summary?.date ? summary.date.replace(/-/g, '.').toUpperCase() : ''}
              </span>
            </div>

            <div className="px-4 py-3 relative z-10">
              {briefingLoading && !briefing ? (
                <div className="space-y-2">
                  <div className="h-3 bg-m-border/30 w-4/5 animate-pulse" />
                  <div className="h-3 bg-m-border/30 w-3/5 animate-pulse" />
                  <div className="h-3 bg-m-border/30 w-4/6 animate-pulse" />
                </div>
              ) : briefing ? (
                <div className="text-xs font-mono text-m-text leading-relaxed whitespace-pre-wrap">
                  {briefing.split('\n').map((line, i) => {
                    if (line.includes('TREND:')) {
                      return <p key={i} className="mt-2"><span className="text-m-green font-bold">{line}</span></p>
                    }
                    if (line.includes('ALERT:')) {
                      return <p key={i} className="mt-2"><span className="text-m-yellow font-bold">{line}</span></p>
                    }
                    return <p key={i} className="mt-1">{line}</p>
                  })}
                </div>
              ) : (
                <p className="text-xs font-mono text-m-text-muted">Awaiting data, Runner.</p>
              )}
            </div>
          </div>

          {/* Survival trend chart */}
          {survivalTrend.length > 1 ? (
            <div className="bg-m-card border border-m-border">
              <div className="px-4 py-3 border-b border-m-border">
                <span className="label-tag text-m-text-muted">TRENDS // SURVIVAL</span>
              </div>
              <div className="px-4 py-3" style={{ height: 200 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={survivalTrend}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1a1a2e" />
                    <XAxis dataKey="label" tick={{ fontSize: 9, fill: '#555' }} />
                    <YAxis domain={[0, 100]} tick={{ fontSize: 9, fill: '#555' }} />
                    <Tooltip
                      contentStyle={{ background: '#0a0a0f', border: '1px solid #1a1a2e', fontSize: 10, fontFamily: 'monospace' }}
                      labelStyle={{ color: '#777' }}
                    />
                    <Line type="monotone" dataKey="value" stroke="#c8ff00" strokeWidth={2} dot={{ r: 3, fill: '#c8ff00' }} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>
          ) : (
            <div className="bg-m-card border border-m-border">
              <div className="px-4 py-3 border-b border-m-border">
                <span className="label-tag text-m-text-muted">TRENDS // SURVIVAL</span>
              </div>
              <div className="px-4 py-3 relative overflow-hidden" style={{ height: 200 }}>
                {/* Decorative grid + ambient data */}
                <div className="absolute inset-0 opacity-[0.04]" style={{
                  backgroundImage: 'linear-gradient(to right, rgba(200,255,0,0.3) 1px, transparent 1px), linear-gradient(to bottom, rgba(200,255,0,0.3) 1px, transparent 1px)',
                  backgroundSize: '20% 25%',
                }} />
                <div className="absolute inset-0 flex items-center justify-center">
                  <div className="text-center space-y-2">
                    <p className="text-[8px] font-mono text-m-text-muted/20 tracking-[0.3em]">// AWAITING SIGNAL //</p>
                    <p className="text-[7px] font-mono text-m-border/30 tracking-widest">0x4E554C4C // DATA.STREAM.PENDING</p>
                  </div>
                </div>
                {/* Fake axis labels */}
                <div className="absolute left-3 top-3 text-[7px] font-mono text-m-border/20">100%</div>
                <div className="absolute left-3 bottom-3 text-[7px] font-mono text-m-border/20">0%</div>
                <div className="absolute right-3 bottom-3 text-[7px] font-mono text-m-border/20">S.01</div>
              </div>
            </div>
          )}

          {/* Loot trend chart */}
          {lootTrend.length > 1 ? (
            <div className="bg-m-card border border-m-border">
              <div className="px-4 py-3 border-b border-m-border">
                <span className="label-tag text-m-text-muted">TRENDS // LOOT.EXTRACTED</span>
              </div>
              <div className="px-4 py-3" style={{ height: 200 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={lootTrend}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1a1a2e" />
                    <XAxis dataKey="label" tick={{ fontSize: 9, fill: '#555' }} />
                    <YAxis tick={{ fontSize: 9, fill: '#555' }} />
                    <Tooltip
                      contentStyle={{ background: '#0a0a0f', border: '1px solid #1a1a2e', fontSize: 10, fontFamily: 'monospace' }}
                      labelStyle={{ color: '#777' }}
                    />
                    <Line type="monotone" dataKey="value" stroke="#c8ff00" strokeWidth={2} dot={{ r: 3, fill: '#c8ff00' }} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>
          ) : (
            <div className="bg-m-card border border-m-border">
              <div className="px-4 py-3 border-b border-m-border">
                <span className="label-tag text-m-text-muted">TRENDS // LOOT.EXTRACTED</span>
              </div>
              <div className="px-4 py-3 relative overflow-hidden" style={{ height: 200 }}>
                {/* Decorative grid + ambient data */}
                <div className="absolute inset-0 opacity-[0.04]" style={{
                  backgroundImage: 'linear-gradient(to right, rgba(200,255,0,0.3) 1px, transparent 1px), linear-gradient(to bottom, rgba(200,255,0,0.3) 1px, transparent 1px)',
                  backgroundSize: '20% 25%',
                }} />
                <div className="absolute inset-0 flex items-center justify-center">
                  <div className="text-center space-y-2">
                    <p className="text-[8px] font-mono text-m-text-muted/20 tracking-[0.3em]">// AWAITING SIGNAL //</p>
                    <p className="text-[7px] font-mono text-m-border/30 tracking-widest">0x4E554C4C // DATA.STREAM.PENDING</p>
                  </div>
                </div>
                {/* Fake axis labels */}
                <div className="absolute left-3 top-3 text-[7px] font-mono text-m-border/20">100%</div>
                <div className="absolute left-3 bottom-3 text-[7px] font-mono text-m-border/20">0%</div>
                <div className="absolute right-3 bottom-3 text-[7px] font-mono text-m-border/20">S.01</div>
              </div>
            </div>
          )}
        </div>

        {/* RIGHT COLUMN — 40% chat */}
        <div className="w-[40%] bg-m-card border border-m-border flex flex-col">
          {/* Chat header */}
          <div className="px-4 py-3 border-b border-m-border">
            <span className="label-tag text-m-green">COMMS // UPLINK</span>
          </div>

          {/* Messages */}
          <div ref={chatRef} className="flex-1 overflow-y-auto px-4 py-3 space-y-4">
            {messages.length === 0 && !streaming && (
              <div className="flex items-center justify-center h-full">
                <div className="text-center space-y-2">
                  <p className="text-sm font-mono text-m-green animate-pulse">UPLINK ACTIVE</p>
                  <p className="text-xs font-mono text-m-text-muted">Awaiting query, Runner.</p>
                </div>
              </div>
            )}

            {messages.map((msg, i) => (
              <div key={i} className={`${msg.role === 'user' ? 'text-right' : 'text-left'}`}>
                <div className={`inline-block max-w-[90%] text-xs font-mono text-m-text leading-relaxed whitespace-pre-wrap ${
                  msg.role === 'user'
                    ? 'border-r-2 border-m-green pr-3 text-right'
                    : 'border-l-2 border-m-text-muted/30 pl-3'
                }`}>
                  {msg.content}
                  {streaming && i === messages.length - 1 && msg.role === 'assistant' && (
                    <span className="animate-pulse text-m-green">_</span>
                  )}
                </div>
              </div>
            ))}
          </div>

          {/* Input */}
          <div className="px-4 py-3 border-t border-m-border">
            <div className="flex items-center gap-2">
              <span className="text-m-green font-mono text-sm">&gt;</span>
              <input
                ref={inputRef}
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && sendMessage()}
                placeholder="query uplink..."
                disabled={streaming}
                className="flex-1 bg-transparent text-xs font-mono text-m-text placeholder:text-m-text-muted/40 focus:outline-none disabled:opacity-40"
              />
              <button
                onClick={sendMessage}
                disabled={streaming || !input.trim()}
                className="text-m-green font-mono text-sm disabled:opacity-30 hover:text-m-green/80 transition-all"
              >
                {'\u25B6'}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function StatBlock({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
  const valueColor = color === 'green' ? 'text-m-green' : color === 'red' ? 'text-m-red' : color === 'yellow' ? 'text-m-yellow' : 'text-m-text'
  return (
    <div className="bg-m-card px-4 py-3">
      <p className="label-tag text-m-text-muted mb-1">{label}</p>
      <p className={`text-2xl font-mono font-bold ${valueColor}`}>{value}</p>
      {sub && <p className="text-xs text-m-text-muted mt-0.5">{sub}</p>}
    </div>
  )
}
