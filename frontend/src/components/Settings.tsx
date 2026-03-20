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
        <div className="px-5 py-4 space-y-4">
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

          {/* Position selector + nudge */}
          <div className="space-y-2">
            <span className="label-tag text-m-text-muted">POSITION</span>
            <div className="flex gap-6 items-start">
              {/* Corner grid */}
              <div className="grid grid-cols-3 gap-1">
                {CORNERS.map((c) => (
                  <button
                    key={c.value}
                    onClick={() => {
                      setOverlayCorner(c.value);
                      (window as any).runlog?.setOverlayCorner?.(c.value)
                    }}
                    className={`w-10 h-7 text-2xs font-mono tracking-widest border transition-all ${
                      overlayCorner === c.value
                        ? 'border-m-green/40 text-m-green bg-m-green/10'
                        : 'border-m-border text-m-text-muted bg-m-surface hover:text-m-text'
                    }`}
                  >
                    {c.label}
                  </button>
                ))}
              </div>

              {/* Nudge D-pad */}
              <div className="flex flex-col items-center">
                <span className="text-[7px] font-mono text-m-text-muted/40 tracking-[0.2em] mb-1">NUDGE</span>
                <div className="grid grid-cols-3 gap-px">
                  <div />
                  <button onClick={() => (window as any).runlog?.nudgeOverlay?.('up')}
                    className="w-7 h-6 text-[10px] font-mono text-m-text-muted border border-m-border/60 bg-m-surface hover:text-m-green hover:border-m-green/30 hover:bg-m-green/5 transition-all flex items-center justify-center">
                    <svg width="8" height="6" viewBox="0 0 8 6" fill="currentColor"><polygon points="4,0 8,6 0,6" /></svg>
                  </button>
                  <div />
                  <button onClick={() => (window as any).runlog?.nudgeOverlay?.('left')}
                    className="w-7 h-6 text-[10px] font-mono text-m-text-muted border border-m-border/60 bg-m-surface hover:text-m-green hover:border-m-green/30 hover:bg-m-green/5 transition-all flex items-center justify-center">
                    <svg width="6" height="8" viewBox="0 0 6 8" fill="currentColor"><polygon points="0,4 6,0 6,8" /></svg>
                  </button>
                  <div className="w-7 h-6 border border-m-border/20 bg-m-border/5 flex items-center justify-center">
                    <div className="w-1.5 h-1.5 bg-m-green/30 rounded-full" />
                  </div>
                  <button onClick={() => (window as any).runlog?.nudgeOverlay?.('right')}
                    className="w-7 h-6 text-[10px] font-mono text-m-text-muted border border-m-border/60 bg-m-surface hover:text-m-green hover:border-m-green/30 hover:bg-m-green/5 transition-all flex items-center justify-center">
                    <svg width="6" height="8" viewBox="0 0 6 8" fill="currentColor"><polygon points="6,4 0,0 0,8" /></svg>
                  </button>
                  <div />
                  <button onClick={() => (window as any).runlog?.nudgeOverlay?.('down')}
                    className="w-7 h-6 text-[10px] font-mono text-m-text-muted border border-m-border/60 bg-m-surface hover:text-m-green hover:border-m-green/30 hover:bg-m-green/5 transition-all flex items-center justify-center">
                    <svg width="8" height="6" viewBox="0 0 8 6" fill="currentColor"><polygon points="4,6 0,0 8,0" /></svg>
                  </button>
                  <div />
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
          {/* Auth mode selector */}
          <SettingRow label="AUTH MODE">
            <ToggleButton
              options={[{ value: 'api', label: 'API KEY' }, { value: 'cli', label: 'CLAUDE ACCT' }]}
              value={config.auth_mode}
              onChange={v => {
                saveConfig('auth_mode', v)
                if (v === 'cli' && !cliStatus) checkCli()
              }}
            />
          </SettingRow>

          {/* Model selection */}
          <SettingRow label="MODEL">
            <ToggleButton
              options={[{ value: 'sonnet', label: 'SONNET' }, { value: 'haiku', label: 'HAIKU' }]}
              value={config.model}
              onChange={v => saveConfig('model', v)}
            />
          </SettingRow>

          {/* API Key mode */}
          {config.auth_mode === 'api' && (
            <div className="space-y-3 pt-2 border-t border-m-border/30">
              <SettingRow label="STATUS">
                {config.has_api_key ? (
                  <div className="flex items-center gap-2">
                    <span className="w-1.5 h-1.5 bg-m-green rounded-full" />
                    <span className="text-2xs font-mono text-m-green">CONFIGURED</span>
                  </div>
                ) : (
                  <div className="flex items-center gap-2">
                    <span className="w-1.5 h-1.5 bg-m-red rounded-full" />
                    <span className="text-2xs font-mono text-m-red">NOT SET</span>
                  </div>
                )}
              </SettingRow>

              {config.has_api_key && (
                <SettingRow label="ACTIVE KEY">
                  <span className="text-2xs font-mono text-m-text-muted">{config.api_key_masked}</span>
                </SettingRow>
              )}

              <div className="space-y-2">
                <label className="label-tag text-m-text-muted">
                  {config.has_api_key ? 'REPLACE KEY' : 'ENTER KEY'}
                </label>
                <input
                  type="password"
                  value={keyInput}
                  onChange={(e) => { setKeyInput(e.target.value); setStatus('idle'); setStatusMsg('') }}
                  placeholder="sk-ant-api03-..."
                  className="w-full px-3 py-2 text-xs font-mono bg-m-black text-m-text border border-m-border focus:border-m-green focus:outline-none placeholder:text-m-text-muted/30"
                />
              </div>

              {statusMsg && (
                <div className={`text-2xs font-mono tracking-wider ${statusColor}`}>{statusMsg}</div>
              )}

              <div className="flex gap-2">
                <button onClick={handleTestAndSave} disabled={!keyInput.trim() || status === 'testing' || status === 'saving'}
                  className="px-4 py-2 text-xs tracking-widest uppercase bg-m-green/10 text-m-green border border-m-green/30 hover:bg-m-green/20 transition-all disabled:opacity-30 disabled:cursor-not-allowed">
                  {status === 'testing' ? 'TESTING...' : status === 'saving' ? 'SAVING...' : 'TEST & SAVE'}
                </button>
                {config.has_api_key && (
                  <button onClick={handleRemove}
                    className="px-4 py-2 text-xs tracking-widest uppercase text-m-red/40 hover:text-m-red transition-colors ml-auto">
                    REMOVE KEY
                  </button>
                )}
              </div>
            </div>
          )}

          {/* CLI mode */}
          {config.auth_mode === 'cli' && (
            <div className="space-y-3 pt-2 border-t border-m-border/30">
              <SettingRow label="CLI STATUS">
                {cliStatus === null ? (
                  <button onClick={checkCli}
                    className="px-3 py-1 text-2xs font-mono tracking-widest border border-m-border text-m-text-muted hover:text-m-cyan hover:border-m-cyan/40 transition-all">
                    CHECK
                  </button>
                ) : cliStatus.installed ? (
                  <div className="flex items-center gap-2">
                    <span className="w-1.5 h-1.5 bg-m-green rounded-full" />
                    <span className="text-2xs font-mono text-m-green">CONNECTED</span>
                  </div>
                ) : (
                  <div className="flex items-center gap-2">
                    <span className="w-1.5 h-1.5 bg-m-red rounded-full" />
                    <span className="text-2xs font-mono text-m-red">NOT FOUND</span>
                  </div>
                )}
              </SettingRow>

              {cliStatus && cliStatus.installed && cliStatus.path && (
                <SettingRow label="BINARY">
                  <span className="text-2xs font-mono text-m-text-muted truncate max-w-[250px]">{cliStatus.path}</span>
                </SettingRow>
              )}

              {cliStatus && !cliStatus.installed && (
                <div className="bg-m-surface border border-m-border/40 px-4 py-3 space-y-2">
                  <p className="text-[10px] font-mono text-m-text-muted tracking-wider">
                    CLAUDE CLI NOT FOUND — INSTALL VIA:
                  </p>
                  <p className="text-xs font-mono text-m-cyan">
                    npm install -g @anthropic-ai/claude-code
                  </p>
                  <p className="text-[10px] font-mono text-m-text-muted tracking-wider">
                    THEN RUN <span className="text-m-cyan">claude login</span> TO AUTHENTICATE
                  </p>
                </div>
              )}

              <div className="pt-1">
                <p className="text-[9px] font-mono text-m-text-muted/40 tracking-wider">
                  USES YOUR CLAUDE SUBSCRIPTION — NO API TOKENS REQUIRED
                </p>
              </div>
            </div>
          )}
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
