import { useEffect, useState, useRef, useCallback } from 'react'
import { getSettings, setApiKey, testApiKey, removeApiKey, updateConfig, getCliStatus } from '../lib/api'
import type { AppSettings } from '../lib/api'

type KeyStatus = 'idle' | 'testing' | 'valid' | 'invalid' | 'saving' | 'saved' | 'error'

const CORNERS = [
  { value: 'top-left', label: 'TL' },
  { value: 'top-center', label: 'TC' },
  { value: 'top-right', label: 'TR' },
  { value: 'bottom-left', label: 'BL' },
  { value: 'bottom-center', label: 'BC' },
  { value: 'bottom-right', label: 'BR' },
] as const

function SectionHeader({ tag, title, desc }: { tag: string; title: string; desc: string }) {
  return (
    <div className="px-5 py-4 border-b border-m-border">
      <p className="label-tag text-m-green mb-1">{tag}</p>
      <p className="text-xs text-m-text-muted">{desc}</p>
    </div>
  )
}

function SettingRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between">
      <span className="label-tag text-m-text-muted">{label}</span>
      <div className="flex items-center gap-2">{children}</div>
    </div>
  )
}

function ToggleButton({ options, value, onChange }: {
  options: { value: string | number; label: string }[]
  value: string | number
  onChange: (v: any) => void
}) {
  return (
    <div className="flex">
      {options.map((opt, i) => (
        <button
          key={opt.value}
          onClick={() => onChange(opt.value)}
          className={`px-3 py-1 text-2xs font-mono tracking-widest border transition-all ${
            i > 0 ? 'border-l-0' : ''
          } ${
            value === opt.value
              ? 'border-m-green/40 text-m-green bg-m-green/10'
              : 'border-m-border text-m-text-muted bg-m-surface hover:text-m-text'
          }`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  )
}

function Slider({ min, max, step, value, onChange, unit, marks }: {
  min: number; max: number; step: number; value: number
  onChange: (v: number) => void; unit?: string; marks?: number[]
}) {
  return (
    <div className="flex items-center gap-3">
      <input
        type="range"
        min={min} max={max} step={step} value={value}
        onChange={e => onChange(Number(e.target.value))}
        className="w-32 accent-[#c8ff00] h-1 bg-m-border appearance-none cursor-pointer
          [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3
          [&::-webkit-slider-thumb]:bg-m-green [&::-webkit-slider-thumb]:border [&::-webkit-slider-thumb]:border-m-green/60
          [&::-webkit-slider-thumb]:cursor-pointer"
      />
      <span className="text-2xs font-mono text-m-green w-16 text-right">{value}{unit || ''}</span>
    </div>
  )
}

export default function Settings() {
  const [config, setConfig] = useState<AppSettings | null>(null)
  const [keyInput, setKeyInput] = useState('')
  const [status, setStatus] = useState<KeyStatus>('idle')
  const [statusMsg, setStatusMsg] = useState('')

  // Overlay settings
  const [overlayEnabled, setOverlayEnabled] = useState(true)
  const [overlayCorner, setOverlayCorner] = useState('top-left')
  const [overlayOpacity, setOverlayOpacity] = useState(88)
  const [overlaySize, setOverlaySize] = useState('medium')
  const [overlayPos, setOverlayPos] = useState({ x: 0, y: 0 })  // % position
  const [draggingOverlay, setDraggingOverlay] = useState(false)
  const posRef = useRef<HTMLDivElement>(null)
  const lastSendRef = useRef(0)

  const sendOverlayPos = useCallback((xPct: number, yPct: number) => {
    const now = Date.now()
    if (now - lastSendRef.current < 33) return  // throttle IPC to 30fps
    lastSendRef.current = now;
    (window as any).runlog?.setOverlayPosition?.(xPct, yPct)
  }, [])

  // CLI status
  const [cliStatus, setCliStatus] = useState<{ installed: boolean; authenticated: boolean; path: string | null } | null>(null)

  useEffect(() => {
    getSettings().then(setConfig).catch(console.error)

    const runlog = (window as any).runlog
    if (runlog?.getOverlaySettings) {
      runlog.getOverlaySettings().then((s: any) => {
        setOverlayEnabled(s.enabled ?? true)
        const corner = s.corner ?? 'top-left'
        setOverlayCorner(corner)
        setOverlayOpacity(s.opacity ?? 88)
        setOverlaySize(s.size ?? 'medium')
        // Set initial preview position from corner
        const posMap: Record<string, { x: number; y: number }> = {
          'top-left': { x: 0, y: 0 }, 'top-center': { x: 35, y: 0 }, 'top-right': { x: 70, y: 0 },
          'bottom-left': { x: 0, y: 88 }, 'bottom-center': { x: 35, y: 88 }, 'bottom-right': { x: 70, y: 88 },
        }
        setOverlayPos(posMap[corner] || { x: s.customX != null ? 50 : 0, y: s.customY != null ? 50 : 0 })
      }).catch(() => {})
    }
  }, [])

  function saveConfig(key: string, value: any) {
    updateConfig(key, value).catch(console.error)
    setConfig(prev => prev ? { ...prev, [key]: value } : prev)
  }

  async function handleTestAndSave() {
    if (!keyInput.trim()) return
    setStatus('testing')
    setStatusMsg('VALIDATING KEY...')
    try {
      await testApiKey(keyInput.trim())
      setStatus('saving')
      setStatusMsg('KEY VALID — SAVING...')
      await setApiKey(keyInput.trim())
      setStatus('saved')
      setStatusMsg('KEY SAVED — SYSTEM READY')
      setKeyInput('')
      const s = await getSettings()
      setConfig(s)
    } catch (err: any) {
      setStatus('invalid')
      setStatusMsg(err.response?.data?.detail || 'INVALID KEY')
    }
  }

  async function handleRemove() {
    try {
      await removeApiKey()
      const s = await getSettings()
      setConfig(s)
      setStatus('idle')
      setStatusMsg('')
    } catch (err) {
      console.error('Failed to remove key:', err)
    }
  }

  async function checkCli() {
    try {
      const status = await getCliStatus()
      setCliStatus(status)
    } catch {
      setCliStatus({ installed: false, authenticated: false, path: null })
    }
  }

  const statusColor =
    status === 'valid' || status === 'saved' ? 'text-m-green' :
    status === 'invalid' || status === 'error' ? 'text-m-red' :
    status === 'testing' || status === 'saving' ? 'text-m-yellow' :
    'text-m-text-muted'

  if (!config) return null

  return (
    <div className="max-w-7xl mx-auto space-y-5">
      {/* Page header */}
      <div>
        <p className="label-tag text-m-green">SYSTEM // SYS.CONFIG</p>
        <h2 className="text-xl font-display font-black tracking-wider text-m-text mt-1">
          SETTINGS
        </h2>
      </div>

      {/* ═══ RECORDING + PROCESSING — side by side ═══ */}
      <div className="flex gap-5">
        {/* Recording */}
        <div className="flex-1 border border-m-border bg-m-card">
          <SectionHeader tag="REC.CONFIG" title="RECORDING" desc="Video capture format, quality, and performance." />
          <div className="px-5 py-4 space-y-4">
            <SettingRow label="ENCODER">
              <ToggleButton
                options={[{ value: 'hevc', label: 'HEVC' }, { value: 'h264', label: 'H.264' }]}
                value={config.encoder}
                onChange={v => saveConfig('encoder', v)}
              />
            </SettingRow>

            <SettingRow label="BITRATE">
              <Slider min={10} max={100} step={5} value={config.bitrate} unit=" MBPS"
                onChange={v => saveConfig('bitrate', v)} />
            </SettingRow>

            <SettingRow label="FRAMERATE">
              <ToggleButton
                options={[{ value: 30, label: '30 FPS' }, { value: 60, label: '60 FPS' }]}
                value={config.fps}
                onChange={v => saveConfig('fps', v)}
              />
            </SettingRow>

            <div className="pt-1 border-t border-m-border/30">
              <p className="text-[9px] font-mono text-m-text-muted/40 tracking-wider">
                NATIVE WINDOW — NEXT RECORDING
              </p>
            </div>
          </div>
        </div>

        {/* Processing */}
        <div className="flex-1 border border-m-border bg-m-card">
          <SectionHeader tag="PROC.CONFIG" title="PROCESSING" desc="Concurrent analysis worker limits." />
          <div className="px-5 py-4 space-y-4">
            <SettingRow label="P1 // STATS">
              <Slider min={1} max={8} step={1} value={config.p1_workers}
                onChange={v => saveConfig('p1_workers', v)} />
            </SettingRow>

            <SettingRow label="P2 // NARRATIVE">
              <Slider min={1} max={4} step={1} value={config.p2_workers}
                onChange={v => saveConfig('p2_workers', v)} />
            </SettingRow>

            <div className="pt-1 border-t border-m-border/30">
              <p className="text-[9px] font-mono text-m-text-muted/40 tracking-wider">
                P1 = FRAMES + STATS — P2 = NARRATIVE + CLIPS
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* ═══ OVERLAY ═══ */}
      <div className="border border-m-border bg-m-card">
        <SectionHeader tag="HUD.OVERLAY" title="RECORDING OVERLAY" desc="Always-on-top status indicator during capture." />
        <div className="px-5 py-4">
          <div className="flex gap-0">
            {/* Left half — controls */}
            <div className="flex-1 space-y-4 pr-5">
              <SettingRow label="OVERLAY">
                <button
                  onClick={() => {
                    const next = !overlayEnabled
                    setOverlayEnabled(next)
                    const runlog = (window as any).runlog
                    runlog?.toggleOverlay?.(next)
                  }}
                  className={`px-3 py-1 text-2xs font-mono tracking-widest border transition-all ${
                    overlayEnabled
                      ? 'border-m-green/40 text-m-green bg-m-green/10'
                      : 'border-m-border text-m-text-muted bg-m-surface'
                  }`}
                >
                  {overlayEnabled ? 'ENABLED' : 'DISABLED'}
                </button>
              </SettingRow>

              <SettingRow label="SIZE">
                <ToggleButton
                  options={[
                    { value: 'small', label: 'SM' },
                    { value: 'medium', label: 'MD' },
                    { value: 'large', label: 'LG' },
                  ]}
                  value={overlaySize}
                  onChange={v => {
                    setOverlaySize(v);
                    (window as any).runlog?.setOverlaySize?.(v)
                  }}
                />
              </SettingRow>

              <SettingRow label="OPACITY">
                <Slider min={40} max={100} step={5} value={overlayOpacity} unit="%"
                  onChange={v => {
                    setOverlayOpacity(v);
                    (window as any).runlog?.setOverlayOpacity?.(v)
                  }}
                />
              </SettingRow>

              <SettingRow label="POSITION">
                <div className="flex">
                  {CORNERS.map((c, i) => {
                    const posMap: Record<string, { x: number; y: number }> = {
                      'top-left': { x: 2, y: 4 }, 'top-center': { x: 50, y: 4 }, 'top-right': { x: 98, y: 4 },
                      'bottom-left': { x: 2, y: 100 }, 'bottom-center': { x: 50, y: 100 }, 'bottom-right': { x: 98, y: 100 },
                    }
                    return (
                      <button
                        key={c.value}
                        onClick={() => {
                          setOverlayCorner(c.value)
                          const pos = posMap[c.value]
                          setOverlayPos(pos);
                          (window as any).runlog?.setOverlayCorner?.(c.value)
                        }}
                        className={`px-2 py-1 text-2xs font-mono tracking-widest border transition-all ${
                          i > 0 ? 'border-l-0' : ''
                        } ${
                          overlayCorner === c.value
                            ? 'border-m-green/40 text-m-green bg-m-green/10'
                            : 'border-m-border text-m-text-muted bg-m-surface hover:text-m-text'
                        }`}
                      >
                        {c.label}
                      </button>
                    )
                  })}
                </div>
              </SettingRow>
            </div>

            {/* Divider */}
            <div className="w-px bg-m-border/30" />

            {/* Right half — draggable position display */}
            <div className="flex-1 pl-5 space-y-3">
              <span className="label-tag text-m-text-muted">POSITION</span>

              {/* Interactive screen preview — drag the bar to reposition */}
              <div
                ref={posRef}
                className="relative border border-m-border/50 bg-m-black/80 aspect-video overflow-hidden cursor-crosshair select-none"
                onMouseDown={(e) => {
                  e.preventDefault()
                  setDraggingOverlay(true)
                  const rect = posRef.current?.getBoundingClientRect()
                  if (!rect) return
                  const xPct = Math.max(0, Math.min(100, (e.clientX - rect.left) / rect.width * 100))
                  const yPct = Math.max(0, Math.min(100, (e.clientY - rect.top) / rect.height * 100))
                  setOverlayPos({ x: xPct, y: yPct })
                  setOverlayCorner('custom')
                  sendOverlayPos(xPct, yPct)
                }}
                onMouseMove={(e) => {
                  if (!draggingOverlay || !posRef.current) return
                  const rect = posRef.current.getBoundingClientRect()
                  const xPct = Math.max(0, Math.min(100, (e.clientX - rect.left) / rect.width * 100))
                  const yPct = Math.max(0, Math.min(100, (e.clientY - rect.top) / rect.height * 100))
                  setOverlayPos({ x: xPct, y: yPct })
                  sendOverlayPos(xPct, yPct)
                }}
                onMouseUp={() => {
                  if (draggingOverlay) {
                    setDraggingOverlay(false)
                    // Final send on release
                    ;(window as any).runlog?.setOverlayPosition?.(overlayPos.x, overlayPos.y)
                  }
                }}
                onMouseLeave={() => setDraggingOverlay(false)}
              >
                {/* Grid lines for reference */}
                <div className="absolute inset-0 pointer-events-none"
                  style={{
                    backgroundImage: `
                      linear-gradient(to right, rgba(200,255,0,0.04) 1px, transparent 1px),
                      linear-gradient(to bottom, rgba(200,255,0,0.04) 1px, transparent 1px)`,
                    backgroundSize: '33.33% 50%',
                  }} />

                {/* Draggable overlay bar — centered on cursor */}
                <div
                  className="absolute pointer-events-none"
                  style={{
                    left: `clamp(0%, ${overlayPos.x}% - 15%, 70%)`,
                    top: `clamp(0%, ${overlayPos.y}% - 4%, 92%)`,
                    width: '30%',
                    height: '8%',
                  }}
                >
                  <div className="w-full h-full bg-m-green/70 border border-m-green shadow-[0_0_12px_rgba(200,255,0,0.4)] flex items-center justify-center">
                    <span className="text-[6px] font-mono text-m-black/60 tracking-widest font-bold">RUNLOG.EXE</span>
                  </div>
                </div>

                {/* Crosshair at cursor position */}
                {draggingOverlay && (
                  <>
                    <div className="absolute pointer-events-none bg-m-green/20" style={{ left: `${overlayPos.x}%`, top: 0, width: 1, height: '100%' }} />
                    <div className="absolute pointer-events-none bg-m-green/20" style={{ left: 0, top: `${overlayPos.y}%`, width: '100%', height: 1 }} />
                  </>
                )}

                {/* Label */}
                {!draggingOverlay && (
                  <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                    <span className="text-[8px] font-mono text-m-border/40 tracking-[0.2em]">CLICK & DRAG TO POSITION</span>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ═══ AUTHENTICATION ═══ */}
      <div className="border border-m-border bg-m-card">
        <SectionHeader tag="AUTH.CONFIG" title="AUTHENTICATION" desc="Connect to Claude for AI-powered analysis." />
        <div className="px-5 py-4">
          <div className="flex gap-0">
            {/* Left — API Key */}
            <div className="flex-1 pr-5 space-y-3">
              <div className="flex items-center justify-between">
                <span className="label-tag text-m-green">API KEY</span>
                {config.has_api_key ? (
                  <div className="flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 bg-m-green rounded-full" />
                    <span className="text-[9px] font-mono text-m-green">ACTIVE</span>
                  </div>
                ) : (
                  <div className="flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 bg-m-border rounded-full" />
                    <span className="text-[9px] font-mono text-m-text-muted">NOT SET</span>
                  </div>
                )}
              </div>

              {config.has_api_key && (
                <p className="text-[9px] font-mono text-m-text-muted/60 truncate">{config.api_key_masked}</p>
              )}

              <input
                type="password"
                value={keyInput}
                onChange={(e) => { setKeyInput(e.target.value); setStatus('idle'); setStatusMsg('') }}
                placeholder="sk-ant-api03-..."
                className="w-full px-3 py-1.5 text-xs font-mono bg-m-black text-m-text border border-m-border focus:border-m-green focus:outline-none placeholder:text-m-text-muted/30"
              />

              {statusMsg && (
                <div className={`text-[9px] font-mono tracking-wider ${statusColor}`}>{statusMsg}</div>
              )}

              <div className="flex gap-2">
                <button onClick={handleTestAndSave} disabled={!keyInput.trim() || status === 'testing' || status === 'saving'}
                  className="px-3 py-1.5 text-[9px] tracking-widest uppercase bg-m-green/10 text-m-green border border-m-green/30 hover:bg-m-green/20 transition-all disabled:opacity-30 disabled:cursor-not-allowed">
                  {status === 'testing' ? 'TESTING...' : status === 'saving' ? 'SAVING...' : 'TEST & SAVE'}
                </button>
                {config.has_api_key && (
                  <button onClick={handleRemove}
                    className="px-3 py-1.5 text-[9px] tracking-widest uppercase text-m-red/40 hover:text-m-red transition-colors">
                    REMOVE
                  </button>
                )}
              </div>

              <div className="pt-1 border-t border-m-border/20">
                <p className="text-[8px] font-mono text-m-text-muted/30 tracking-wider leading-relaxed">
                  01 — GO TO CONSOLE.ANTHROPIC.COM<br/>
                  02 — GENERATE AN API KEY<br/>
                  03 — PASTE ABOVE AND TEST & SAVE
                </p>
              </div>
            </div>

            {/* Divider */}
            <div className="w-px bg-m-border/30" />

            {/* Right — Model + Claude CLI */}
            <div className="flex-1 pl-5 space-y-4">
              {/* Model selector at top */}
              <div>
                <div className="flex items-center justify-between">
                  <span className="label-tag text-m-text-muted">MODEL</span>
                  <ToggleButton
                    options={[{ value: 'sonnet', label: 'SONNET' }, { value: 'haiku', label: 'HAIKU' }]}
                    value={config.model}
                    onChange={v => saveConfig('model', v)}
                  />
                </div>
                <p className="text-[8px] font-mono text-m-text-muted/30 tracking-wider mt-1.5">
                  SONNET = HIGHER ACCURACY — HAIKU = LOWER COST
                </p>
              </div>

              {/* Divider */}
              <div className="border-t border-m-border/20" />

              {/* Claude CLI below model */}
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <span className="label-tag text-m-cyan">CLAUDE CLI</span>
                  {cliStatus === null ? (
                    <button onClick={checkCli}
                      className="px-2 py-0.5 text-[9px] font-mono tracking-widest border border-m-border text-m-text-muted hover:text-m-cyan hover:border-m-cyan/40 transition-all">
                      CHECK
                    </button>
                  ) : cliStatus.installed ? (
                    <div className="flex items-center gap-1.5">
                      <span className="w-1.5 h-1.5 bg-m-green rounded-full" />
                      <span className="text-[9px] font-mono text-m-green">CONNECTED</span>
                    </div>
                  ) : (
                    <div className="flex items-center gap-1.5">
                      <span className="w-1.5 h-1.5 bg-m-red rounded-full" />
                      <span className="text-[9px] font-mono text-m-red">NOT FOUND</span>
                    </div>
                  )}
                </div>

                {cliStatus && cliStatus.installed && cliStatus.path && (
                  <p className="text-[9px] font-mono text-m-text-muted/60 truncate">{cliStatus.path}</p>
                )}

                {cliStatus && !cliStatus.installed && (
                  <div className="bg-m-surface border border-m-border/30 px-3 py-2 space-y-1.5">
                    <p className="text-[9px] font-mono text-m-text-muted tracking-wider">
                      CLI NOT FOUND — INSTALL:
                    </p>
                    <p className="text-[10px] font-mono text-m-cyan">
                      npm install -g @anthropic-ai/claude-code
                    </p>
                  </div>
                )}

                <div className="pt-1 border-t border-m-border/20">
                  <p className="text-[8px] font-mono text-m-text-muted/30 tracking-wider leading-relaxed">
                    01 — INSTALL CLAUDE CODE CLI<br/>
                    02 — RUN <span className="text-m-cyan/50">claude login</span> IN TERMINAL<br/>
                    03 — USES YOUR CLAUDE SUBSCRIPTION<br/>
                    <span className="text-m-text-muted/20">NO API TOKENS REQUIRED</span>
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Version info */}
      <div className="flex justify-between text-2xs font-mono text-m-text-muted/40">
        <span>runlog.exe v1.0.0</span>
        <span>LOCAL-FIRST // NO CLOUD // NO TELEMETRY</span>
      </div>
    </div>
  )
}
