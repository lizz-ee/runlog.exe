import { useEffect, useState } from 'react'
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

  // CLI status
  const [cliStatus, setCliStatus] = useState<{ installed: boolean; authenticated: boolean; path: string | null } | null>(null)

  useEffect(() => {
    getSettings().then(setConfig).catch(console.error)

    const runlog = (window as any).runlog
    if (runlog?.getOverlaySettings) {
      runlog.getOverlaySettings().then((s: any) => {
        setOverlayEnabled(s.enabled ?? true)
        setOverlayCorner(s.corner ?? 'top-left')
        setOverlayOpacity(s.opacity ?? 88)
        setOverlaySize(s.size ?? 'medium')
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

      {/* ═══ RECORDING ═══ */}
      <div className="border border-m-border bg-m-card">
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
              RESOLUTION // NATIVE WINDOW — CHANGES TAKE EFFECT ON NEXT RECORDING
            </p>
          </div>
        </div>
      </div>

      {/* ═══ PROCESSING ═══ */}
      <div className="border border-m-border bg-m-card">
        <SectionHeader tag="PROC.CONFIG" title="PROCESSING" desc="Concurrent analysis worker limits. Higher = faster but more CPU/API usage." />
        <div className="px-5 py-4 space-y-4">
          <SettingRow label="P1 WORKERS // STATS">
            <Slider min={1} max={8} step={1} value={config.p1_workers}
              onChange={v => saveConfig('p1_workers', v)} />
          </SettingRow>

          <SettingRow label="P2 WORKERS // NARRATIVE">
            <Slider min={1} max={4} step={1} value={config.p2_workers}
              onChange={v => saveConfig('p2_workers', v)} />
          </SettingRow>

          <div className="pt-1 border-t border-m-border/30">
            <p className="text-[9px] font-mono text-m-text-muted/40 tracking-wider">
              P1 = FRAME EXTRACTION + STAT ANALYSIS — P2 = VIDEO NARRATIVE + CLIP GENERATION
            </p>
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
            </div>

            {/* Divider */}
            <div className="w-px bg-m-border/30" />

            {/* Right half — interactive position display */}
            <div className="flex-1 pl-5 space-y-3">
              <span className="label-tag text-m-text-muted">POSITION</span>

              {/* Interactive screen preview — click zones to set position */}
              <div className="relative border border-m-border/50 bg-m-black/60 aspect-video overflow-hidden">
                {/* Scan lines */}
                <div className="absolute inset-0 opacity-[0.03] pointer-events-none"
                  style={{ backgroundImage: 'repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(200,255,0,0.3) 2px, rgba(200,255,0,0.3) 3px)' }} />

                {/* 6 clickable zones — 3x2 grid */}
                <div className="absolute inset-0 grid grid-cols-3 grid-rows-2">
                  {CORNERS.map((c) => {
                    const isActive = overlayCorner === c.value
                    return (
                      <button
                        key={c.value}
                        onClick={() => {
                          setOverlayCorner(c.value);
                          (window as any).runlog?.setOverlayCorner?.(c.value)
                        }}
                        className={`relative transition-all ${isActive ? 'bg-m-green/5' : 'hover:bg-m-green/3'}`}
                      >
                        {/* Zone label */}
                        <span className={`absolute text-[7px] font-mono tracking-wider transition-all ${
                          isActive ? 'text-m-green/50' : 'text-m-border/30'
                        } ${
                          c.value.includes('top') ? 'top-1' : 'bottom-1'
                        } ${
                          c.value.includes('left') ? 'left-1.5' : c.value.includes('right') ? 'right-1.5' : 'left-1/2 -translate-x-1/2'
                        }`}>
                          {c.label}
                        </span>
                      </button>
                    )
                  })}
                </div>

                {/* Overlay bar indicator — shows where the HUD actually is */}
                {(() => {
                  const pos = overlayCorner
                  const barStyle: React.CSSProperties = {
                    position: 'absolute',
                    width: overlaySize === 'small' ? '30%' : overlaySize === 'large' ? '50%' : '38%',
                    height: '12%',
                    transition: 'all 0.3s ease',
                  }
                  if (pos.includes('top')) barStyle.top = '4%'
                  else barStyle.bottom = '4%'
                  if (pos.includes('left')) barStyle.left = '3%'
                  else if (pos.includes('right')) barStyle.right = '3%'
                  else { barStyle.left = '50%'; barStyle.transform = 'translateX(-50%)' }

                  return (
                    <div style={barStyle} className="pointer-events-none">
                      <div className="w-full h-full bg-m-green/60 border border-m-green/80 shadow-[0_0_12px_rgba(200,255,0,0.3)]" />
                    </div>
                  )
                })()}

                {/* Center label */}
                <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                  <span className="text-[7px] font-mono text-m-border/30 tracking-[0.3em]">DISPLAY</span>
                </div>
              </div>

              {/* Nudge controls — inline */}
              <div className="flex items-center gap-3">
                <span className="text-[7px] font-mono text-m-text-muted/40 tracking-[0.2em]">NUDGE</span>
                <div className="flex items-center gap-px">
                  {(['left', 'up', 'down', 'right'] as const).map(dir => (
                    <button key={dir} onClick={() => (window as any).runlog?.nudgeOverlay?.(dir)}
                      className="w-6 h-5 text-m-text-muted border border-m-border/60 bg-m-surface hover:text-m-green hover:border-m-green/30 hover:bg-m-green/5 transition-all flex items-center justify-center">
                      <svg width="6" height="6" viewBox="0 0 8 8" fill="currentColor">
                        {dir === 'up' && <polygon points="4,1 7,6 1,6" />}
                        {dir === 'down' && <polygon points="4,7 1,2 7,2" />}
                        {dir === 'left' && <polygon points="1,4 6,1 6,7" />}
                        {dir === 'right' && <polygon points="7,4 2,1 2,7" />}
                      </svg>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ═══ AUTHENTICATION ═══ */}
      <div className="border border-m-border bg-m-card">
        <SectionHeader tag="AUTH.CONFIG" title="AUTHENTICATION" desc="Connect to Claude for AI-powered analysis." />
        <div className="px-5 py-4 space-y-4">
          {/* Model selection — shared across both auth modes */}
          <SettingRow label="MODEL">
            <ToggleButton
              options={[{ value: 'sonnet', label: 'SONNET' }, { value: 'haiku', label: 'HAIKU' }]}
              value={config.model}
              onChange={v => saveConfig('model', v)}
            />
          </SettingRow>

          {/* Side-by-side auth methods */}
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

            {/* Right — Claude CLI */}
            <div className="flex-1 pl-5 space-y-3">
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

      {/* Version info */}
      <div className="flex justify-between text-2xs font-mono text-m-text-muted/40">
        <span>runlog.exe v1.0.0</span>
        <span>LOCAL-FIRST // NO CLOUD // NO TELEMETRY</span>
      </div>
    </div>
  )
}
