import { useEffect, useState, useRef, useCallback } from 'react'
import { getSettings, setApiKey, testApiKey, removeApiKey, updateConfig, migrateStorage, browseFolder, getCliStatus, cliLogin, cliLogout, getCliLatestVersion, cliUpdate, setAutoPhase } from '../lib/api'
import type { AppSettings } from '../lib/api'
import type { OverlaySettings } from '../lib/types'

type KeyStatus = 'idle' | 'testing' | 'valid' | 'invalid' | 'saving' | 'saved' | 'error'

const CORNERS = [
  { value: 'top-left', label: 'TL' },
  { value: 'top-center', label: 'TC' },
  { value: 'top-right', label: 'TR' },
  { value: 'bottom-left', label: 'BL' },
  { value: 'bottom-center', label: 'BC' },
  { value: 'bottom-right', label: 'BR' },
] as const

function SectionHeader({ tag, title: _title, desc }: { tag: string; title: string; desc: string }) {
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

function ToggleButton({ options, value, onChange, disabledValues }: {
  options: { value: string | number; label: string }[]
  value: string | number
  onChange: (v: string | number) => void
  disabledValues?: (string | number)[]
}) {
  return (
    <div className="flex">
      {options.map((opt, i) => {
        const isDisabled = disabledValues?.includes(opt.value)
        return (
          <button
            key={opt.value}
            onClick={() => !isDisabled && onChange(opt.value)}
            disabled={isDisabled}
            className={`px-3 py-1 text-2xs font-mono tracking-widest border transition-all ${
              i > 0 ? '-ml-px' : ''
            } ${
              isDisabled
                ? 'border-m-border text-m-text-muted/30 bg-m-surface cursor-not-allowed'
                : value === opt.value
                  ? 'border-m-green/40 text-m-green bg-m-green/10 relative z-10'
                  : 'border-m-border text-m-text-muted bg-m-surface hover:text-m-text'
            }`}
          >
            {opt.label}
          </button>
        )
      })}
    </div>
  )
}

function Slider({ min, max, step, value, onChange, unit, marks: _marks }: {
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
  const [cliStatus, setCliStatus] = useState<{ installed: boolean; authenticated: boolean; path: string | null; version: string | null } | null>(null)
  const [cliLatest, setCliLatest] = useState<string | null>(null)
  const [cliLoginPending, setCliLoginPending] = useState(false)
  const [cliUpdating, setCliUpdating] = useState(false)
  const [migrating, setMigrating] = useState(false)
  const [migrateResult, setMigrateResult] = useState<string | null>(null)
  // Snapshot of original values for restart-required keys. Populated on the
  // first change of each key. If the user dismisses the toast without
  // restarting, every key in this map is reverted (UI + backend) to its
  // snapshotted original. Keyed empty = no pending changes.
  const [restartOriginals, setRestartOriginals] = useState<Record<string, any>>({})
  const restartDirty = Object.keys(restartOriginals).length > 0

  useEffect(() => {
    getSettings().then(setConfig).catch((e) => console.error('[Settings] fetch settings failed:', e))
    checkCli()

    const runlog = (window as any).runlog
    if (runlog?.getOverlaySettings) {
      runlog.getOverlaySettings().then((s: OverlaySettings) => {
        setOverlayEnabled(s.enabled ?? true)
        const corner = s.corner ?? 'top-left'
        setOverlayCorner(corner)
        setOverlayOpacity(s.opacity ?? 88)
        setOverlaySize(s.size ?? 'medium')
        // Set initial preview position from saved settings
        if (s.customX != null && s.customY != null) {
          // Custom drag position — use exact saved percentages
          setOverlayPos({ x: s.customX, y: s.customY })
        } else {
          const posMap: Record<string, { x: number; y: number }> = {
            'top-left': { x: 0, y: 0 }, 'top-center': { x: 35, y: 0 }, 'top-right': { x: 70, y: 0 },
            'bottom-left': { x: 0, y: 88 }, 'bottom-center': { x: 35, y: 88 }, 'bottom-right': { x: 70, y: 88 },
          }
          setOverlayPos(posMap[corner] || { x: 0, y: 0 })
        }
      }).catch((e: unknown) => console.error('[Settings] fetch overlay settings failed:', e))
    }
  }, [])

  // Settings whose effects only land at engine/process startup. Changing any
  // of these reveals a sticky bottom-right RESTART REQUIRED toast.
  const RESTART_KEYS = new Set(['p1_workers', 'p2_workers', 'storage_path'])

  function saveConfig(key: string, value: any) {
    if (RESTART_KEYS.has(key)) {
      // Track originals so a dismiss can revert. Only snapshot the very first
      // change per key — subsequent changes still revert to the truly-original
      // value, not an intermediate. If the new value equals the snapshot we've
      // already taken, the change is a revert and the snapshot can be dropped.
      setRestartOriginals(prev => {
        if (key in prev) {
          if (prev[key] === value) {
            const { [key]: _, ...rest } = prev
            return rest
          }
          return prev
        }
        const original = config ? (config as any)[key] : undefined
        if (original === value) return prev
        return { ...prev, [key]: original }
      })
    }
    updateConfig(key, value).catch((e) => console.error('[Settings] save config failed:', e))
    setConfig(prev => prev ? { ...prev, [key]: value } : prev)
  }

  function dismissRestart() {
    // Revert every pending restart-key change back to its original value
    // (both backend and local UI). Then clear the pending set so the toast hides.
    Object.entries(restartOriginals).forEach(([key, originalValue]) => {
      updateConfig(key, originalValue).catch((e) =>
        console.error('[Settings] revert failed:', e)
      )
      setConfig(prev => prev ? { ...prev, [key]: originalValue } : prev)
    })
    setRestartOriginals({})
  }

  function relaunchApp() {
    const runlog = (window as any).runlog
    if (runlog?.relaunchApp) runlog.relaunchApp()
    else window.location.reload()  // dev-mode fallback (no Electron bridge)
  }

  function restartNow() {
    // The new values were already persisted on each saveConfig call; the
    // restart just makes them take effect. Clear the originals map so React
    // doesn't trigger a revert if the relaunch is interrupted.
    setRestartOriginals({})
    relaunchApp()
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
    } catch (err: unknown) {
      setStatus('invalid')
      const axiosErr = err as { response?: { data?: { detail?: string } } }
      setStatusMsg(axiosErr.response?.data?.detail || 'INVALID KEY')
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
      // Fetch latest version if CLI is installed
      if (status.installed) {
        getCliLatestVersion()
          .then(({ latest }) => setCliLatest(latest))
          .catch(() => setCliLatest(null))
      }
    } catch {
      setCliStatus({ installed: false, authenticated: false, path: null, version: null })
    }
  }

  async function handleCliLogin() {
    setCliLoginPending(true)
    try {
      await cliLogin()
      // Poll for auth status — login opens browser, user may take a moment
      const pollInterval = setInterval(async () => {
        try {
          const status = await getCliStatus()
          setCliStatus(status)
          if (status.authenticated) {
            clearInterval(pollInterval)
            setCliLoginPending(false)
          }
        } catch { /* keep polling */ }
      }, 3000)
      // Stop polling after 2 minutes
      setTimeout(() => {
        clearInterval(pollInterval)
        setCliLoginPending(false)
      }, 120000)
    } catch {
      setCliLoginPending(false)
    }
  }

  async function handleCliLogout() {
    try {
      await cliLogout()
      await checkCli()
    } catch (err) {
      console.error('CLI logout failed:', err)
    }
  }

  async function handleCliUpdate() {
    setCliUpdating(true)
    try {
      const result = await cliUpdate()
      // Refresh status to pick up new version
      await checkCli()
      if (result.version) {
        setCliLatest(result.version)
      }
    } catch (err) {
      console.error('CLI update failed:', err)
    } finally {
      setCliUpdating(false)
    }
  }

  // Auto-select the only available provider
  const hasApi = config?.has_api_key
  const hasCli = cliStatus?.installed && cliStatus?.authenticated
  useEffect(() => {
    if (!config) return
    if (hasApi && !hasCli && config.auth_mode !== 'api') {
      saveConfig('auth_mode', 'api')
    } else if (hasCli && !hasApi && config.auth_mode !== 'cli') {
      saveConfig('auth_mode', 'cli')
    }
  }, [hasApi, hasCli, config?.auth_mode])

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

            <SettingRow label="RESOLUTION">
              <ToggleButton
                options={[
                  { value: 'native', label: 'NATIVE' },
                  { value: '1440p', label: '1440P' },
                  { value: '1080p', label: '1080P' },
                  { value: '720p', label: '720P' },
                ]}
                value={config.resolution || 'native'}
                onChange={v => saveConfig('resolution', v)}
              />
            </SettingRow>

            <div className="pt-1 border-t border-m-border/30">
              <p className="text-[9px] font-mono text-m-text-muted tracking-wider">
                APPLIES TO NEXT RECORDING — OCR UNAFFECTED
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

            <div className="pt-2 border-t border-m-border/30 space-y-3">
              <SettingRow label="AUTO-RUN P1">
                <ToggleButton
                  options={[{ value: 'on', label: 'ON' }, { value: 'off', label: 'OFF' }]}
                  value={config.auto_p1 ? 'on' : 'off'}
                  onChange={v => {
                    const enabled = v === 'on'
                    saveConfig('auto_p1', enabled)
                    setAutoPhase(1, enabled).catch(console.error)
                  }}
                />
              </SettingRow>
              <SettingRow label="AUTO-RUN P2">
                <ToggleButton
                  options={[{ value: 'on', label: 'ON' }, { value: 'off', label: 'OFF' }]}
                  value={config.auto_p2 ? 'on' : 'off'}
                  onChange={v => {
                    const enabled = v === 'on'
                    saveConfig('auto_p2', enabled)
                    setAutoPhase(2, enabled).catch(console.error)
                  }}
                />
              </SettingRow>
              <SettingRow label="GAME GUARD">
                <ToggleButton
                  options={[{ value: 'on', label: 'ON' }, { value: 'off', label: 'OFF' }]}
                  value={config.pause_processing_while_game_running ? 'on' : 'off'}
                  onChange={v => saveConfig('pause_processing_while_game_running', v === 'on')}
                />
              </SettingRow>
            </div>

            <div className="pt-1 border-t border-m-border/30">
              <p className="text-[9px] font-mono text-m-text-muted tracking-wider">
                P1 = FRAMES + STATS — P2 = NARRATIVE + CLIPS<br/>
                <span className="text-m-yellow/40">WORKER COUNTS REQUIRE RESTART · OTHER TOGGLES TAKE EFFECT IMMEDIATELY</span>
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* ═══ STORAGE + (empty right half) ═══ */}
      <div className="flex gap-5">
        <div className="flex-1 border border-m-border bg-m-card">
          <SectionHeader tag="STOR.CONFIG" title="STORAGE" desc="Where recordings, clips, and screenshots are saved." />
          <div className="px-5 py-4 space-y-4">
            <SettingRow label="MEDIA PATH">
              <button
                className="px-3 py-1 text-2xs font-mono border border-m-border hover:border-m-green hover:text-m-green text-m-text-muted transition-colors"
                onClick={async () => {
                  const path = await browseFolder()
                  if (path) {
                    setConfig(prev => prev ? { ...prev, storage_path: path } : prev)
                    saveConfig('storage_path', path)
                  }
                }}
              >
                BROWSE
              </button>
            </SettingRow>

            {config.storage_path && (
              <div className="flex items-center gap-2">
                <p className="flex-1 text-[9px] font-mono text-m-green tracking-wider truncate">
                  {config.storage_path}
                </p>
                <button
                  className="px-2 py-0.5 text-[9px] font-mono border border-m-border/50 hover:border-m-red hover:text-m-red text-m-text-muted/40 transition-colors"
                  onClick={() => {
                    setConfig(prev => prev ? { ...prev, storage_path: '' } : prev)
                    saveConfig('storage_path', '')
                    setMigrateResult(null)
                  }}
                >
                  CLEAR
                </button>
              </div>
            )}

            {config.storage_path && (
              <SettingRow label="MIGRATE DATA">
                <button
                  className="px-3 py-1 text-2xs font-mono border border-m-border hover:border-m-green hover:text-m-green text-m-text-muted disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                  disabled={migrating}
                  onClick={async () => {
                    if (!config.storage_path) return
                    setMigrating(true)
                    setMigrateResult(null)
                    try {
                      const res = await migrateStorage(config.storage_path)
                      const parts = [`${res.moved_runs} runs, ${res.moved_recordings} recordings moved`]
                      if (res.db_paths_updated > 0) parts.push(`${res.db_paths_updated} DB paths updated`)
                      if (res.errors?.length) parts.push(`${res.errors.length} errors`)
                      setMigrateResult(parts.join(' · '))
                    } catch (e: any) {
                      setMigrateResult(`ERROR: ${e?.response?.data?.detail || e.message}`)
                    } finally {
                      setMigrating(false)
                    }
                  }}
                >
                  {migrating ? 'MIGRATING...' : 'MOVE EXISTING DATA'}
                </button>
              </SettingRow>
            )}

            {migrateResult && (
              <p className={`text-[9px] font-mono tracking-wider ${migrateResult.startsWith('ERROR') ? 'text-m-red' : 'text-m-green'}`}>
                {migrateResult}
              </p>
            )}

            <div className="pt-1 border-t border-m-border/30">
              <p className="text-[9px] font-mono text-m-text-muted tracking-wider">
                ACTIVE: <span className="text-m-green">{config.storage_path_active || config.storage_path_default || '...'}</span><br/>
                <span className="text-m-yellow/40">RESTART REQUIRED FOR CHANGES</span>
              </p>
            </div>
          </div>
        </div>

        {/* Processor Mode */}
        <div className="flex-1 border border-m-border bg-m-card">
          <SectionHeader tag="PROC.MODE" title="PROCESSOR" desc="Analysis engine for stat extraction and highlights." />
          <div className="px-5 py-4 space-y-4">
            <SettingRow label="ENGINE">
              <ToggleButton
                options={[
                  { value: 'alpha', label: 'ALPHA' },
                  { value: 'hybrid', label: 'HYBRID' },
                  { value: 'claude', label: 'CLAUDE' },
                ]}
                value={config.processor_mode || 'alpha'}
                onChange={v => saveConfig('processor_mode', v)}
              />
            </SettingRow>

            <div className="pt-1 border-t border-m-border/30">
              <p className="text-[9px] font-mono text-m-text-muted tracking-wider">
                ALPHA = LOCAL OCR + ML (FREE, OFFLINE, &lt;2s)<br/>
                HYBRID = LOCAL FIRST, CLAUDE FALLBACK (~$0.01/RUN)<br/>
                CLAUDE = API/CLI ONLY (PAID, MOST ACCURATE)<br/>
                <span className="text-m-green">ALPHA RECOMMENDED FOR MOST USERS</span>
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
                  aria-label={overlayEnabled ? 'Disable overlay' : 'Enable overlay'}
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
                <button
                  aria-label="Preview overlay position"
                  onClick={() => (window as any).runlog?.previewOverlay?.()}
                  className="px-3 py-1 text-2xs font-mono tracking-widest border border-m-border text-m-text-muted bg-m-surface hover:text-m-text transition-all"
                >
                  PREVIEW
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
                    setOverlaySize(String(v));
                    window.runlog?.setOverlaySize?.(String(v))
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
                <div className="grid grid-cols-3 gap-0">
                  {CORNERS.map((c) => {
                    const posMap: Record<string, { x: number; y: number }> = {
                      'top-left': { x: 2, y: 4 }, 'top-center': { x: 50, y: 4 }, 'top-right': { x: 98, y: 4 },
                      'bottom-left': { x: 2, y: 100 }, 'bottom-center': { x: 50, y: 100 }, 'bottom-right': { x: 98, y: 100 },
                    }
                    const row = c.value.startsWith('top') ? 0 : 1
                    const col = c.value.endsWith('left') ? 0 : c.value.endsWith('center') ? 1 : 2
                    return (
                      <button
                        key={c.value}
                        aria-label={`Position overlay ${c.value.replace('-', ' ')}`}
                        onClick={() => {
                          setOverlayCorner(c.value)
                          const pos = posMap[c.value]
                          setOverlayPos(pos);
                          (window as any).runlog?.setOverlayCorner?.(c.value)
                        }}
                        className={`px-2 py-1 text-2xs font-mono tracking-widest border transition-all ${
                          col > 0 ? '-ml-px' : ''
                        } ${
                          row > 0 ? '-mt-px' : ''
                        } ${
                          overlayCorner === c.value
                            ? 'border-m-green/40 text-m-green bg-m-green/10 relative z-10'
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
                role="slider"
                aria-label="Drag to reposition overlay"
                aria-valuetext={`X: ${Math.round(overlayPos.x)}%, Y: ${Math.round(overlayPos.y)}%`}
                className="relative border border-m-border/50 bg-m-black/80 aspect-video overflow-hidden cursor-crosshair select-none"
                onPointerDown={(e) => {
                  e.preventDefault()
                  e.currentTarget.setPointerCapture(e.pointerId)
                  setDraggingOverlay(true)
                  const rect = posRef.current?.getBoundingClientRect()
                  if (!rect) return
                  const xPct = Math.max(0, Math.min(100, (e.clientX - rect.left) / rect.width * 100))
                  const yPct = Math.max(0, Math.min(100, (e.clientY - rect.top) / rect.height * 100))
                  setOverlayPos({ x: xPct, y: yPct })
                  setOverlayCorner('custom')
                  sendOverlayPos(xPct, yPct)
                }}
                onPointerMove={(e) => {
                  if (!draggingOverlay || !posRef.current) return
                  const rect = posRef.current.getBoundingClientRect()
                  const xPct = Math.max(0, Math.min(100, (e.clientX - rect.left) / rect.width * 100))
                  const yPct = Math.max(0, Math.min(100, (e.clientY - rect.top) / rect.height * 100))
                  setOverlayPos({ x: xPct, y: yPct })
                  sendOverlayPos(xPct, yPct)
                }}
                onPointerUp={() => {
                  if (draggingOverlay) {
                    setDraggingOverlay(false)
                    ;(window as any).runlog?.setOverlayPosition?.(overlayPos.x, overlayPos.y)
                  }
                }}
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
        <div className="px-5 py-4 space-y-4">
          <div className="flex gap-0">
            {/* Left — Config toggles */}
            <div className="flex-1 pr-5 space-y-4">
              {/* AI Provider */}
              <div className="flex items-center justify-between">
                <div>
                  <span className="label-tag text-m-cyan">AI.PROVIDER</span>
                  <p className="text-[7px] font-mono text-m-text-muted tracking-wider mt-0.5">PREFERRED CONNECTION METHOD</p>
                </div>
                <ToggleButton
                  options={[{ value: 'api', label: 'API KEY' }, { value: 'cli', label: 'CLI' }]}
                  value={config.auth_mode || 'api'}
                  onChange={v => saveConfig('auth_mode', v)}
                  disabledValues={[
                    ...(!config.has_api_key ? ['api'] : []),
                    ...(!(cliStatus?.installed && cliStatus?.authenticated) ? ['cli'] : []),
                  ]}
                />
              </div>

              <div className="border-t border-m-border/20" />

              {/* Capture Model */}
              <div className="flex items-center justify-between">
                <div>
                  <span className="label-tag text-m-green">CAPTURE.MODEL</span>
                  <p className="text-[7px] font-mono text-m-text-muted tracking-wider mt-0.5">RUN ANALYSIS + STATS</p>
                </div>
                <ToggleButton
                  options={[{ value: 'sonnet', label: 'SONNET' }, { value: 'haiku', label: 'HAIKU' }]}
                  value={config.model}
                  onChange={v => saveConfig('model', v)}
                />
              </div>

              <div className="border-t border-m-border/20" />

              {/* Uplink Model */}
              <div className="flex items-center justify-between">
                <div>
                  <span className="label-tag text-m-green">UPLINK.MODEL</span>
                  <p className="text-[7px] font-mono text-m-text-muted tracking-wider mt-0.5">CHAT + BRIEFINGS</p>
                </div>
                <ToggleButton
                  options={[{ value: 'sonnet', label: 'SONNET' }, { value: 'haiku', label: 'HAIKU' }]}
                  value={config.uplink_model || 'haiku'}
                  onChange={v => saveConfig('uplink_model', v)}
                />
              </div>
            </div>

            {/* Divider */}
            <div className="w-px bg-m-border/30" />

            {/* Right — Auth credentials */}
            <div className="flex-1 pl-5 space-y-4">
              {/* API Key */}
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <span className="label-tag text-m-cyan">API KEY</span>
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

                {config.has_api_key ? (
                  <>
                    <p className="text-[9px] font-mono text-m-text-muted truncate">{config.api_key_masked}</p>
                    <button onClick={handleRemove}
                      className="px-3 py-1.5 text-[9px] tracking-widest uppercase text-m-red/40 hover:text-m-red border border-m-red/20 hover:border-m-red/40 transition-all">
                      REMOVE
                    </button>
                  </>
                ) : (
                  <>
                    <input
                      type="password"
                      value={keyInput}
                      onChange={(e) => { setKeyInput(e.target.value); setStatus('idle'); setStatusMsg('') }}
                      placeholder="sk-ant-api03-..."
                      className="w-full px-3 py-1.5 text-xs font-mono bg-m-black text-m-text border border-m-border focus:border-m-green focus:outline-none placeholder:text-m-text-muted"
                    />

                    {statusMsg && (
                      <div className={`text-[9px] font-mono tracking-wider ${statusColor}`}>{statusMsg}</div>
                    )}

                    <button onClick={handleTestAndSave} disabled={!keyInput.trim() || status === 'testing' || status === 'saving'}
                      className="px-3 py-1.5 text-[9px] tracking-widest uppercase bg-m-green/10 text-m-green border border-m-green/30 hover:bg-m-green/20 transition-all disabled:opacity-30 disabled:cursor-not-allowed">
                      {status === 'testing' ? 'TESTING...' : status === 'saving' ? 'SAVING...' : 'TEST & SAVE'}
                    </button>

                    <div className="pt-1 border-t border-m-border/20">
                      <p className="text-[8px] font-mono text-m-text-muted tracking-wider leading-relaxed">
                        01 — GO TO CONSOLE.ANTHROPIC.COM<br/>
                        02 — GENERATE AN API KEY<br/>
                        03 — PASTE ABOVE AND TEST & SAVE
                      </p>
                    </div>
                  </>
                )}
              </div>

              <div className="border-t border-m-border/20" />

              {/* Claude CLI */}
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <span className="label-tag text-m-cyan">CLAUDE.CLI</span>
                  {cliStatus === null ? (
                    <button onClick={checkCli}
                      className="px-2 py-0.5 text-[9px] font-mono tracking-widest border border-m-border text-m-text-muted hover:text-m-cyan hover:border-m-cyan/40 transition-all">
                      CHECK
                    </button>
                  ) : cliStatus.installed && cliStatus.authenticated ? (
                    <div className="flex items-center gap-2">
                      <div className="flex items-center gap-1.5">
                        <span className="w-1.5 h-1.5 bg-m-green rounded-full" />
                        <span className="text-[9px] font-mono text-m-green">CONNECTED</span>
                      </div>
                      <button onClick={handleCliLogout}
                        className="px-2 py-0.5 text-[9px] font-mono tracking-widest text-m-red/40 hover:text-m-red transition-colors">
                        LOGOUT
                      </button>
                    </div>
                  ) : cliStatus.installed && !cliStatus.authenticated ? (
                    <div className="flex items-center gap-2">
                      <div className="flex items-center gap-1.5">
                        <span className="w-1.5 h-1.5 bg-m-yellow rounded-full" />
                        <span className="text-[9px] font-mono text-m-yellow">NOT LOGGED IN</span>
                      </div>
                      <button onClick={checkCli}
                        className="px-2 py-0.5 text-[9px] font-mono tracking-widest border border-m-border text-m-text-muted hover:text-m-cyan hover:border-m-cyan/40 transition-all">
                        CHECK
                      </button>
                    </div>
                  ) : (
                    <div className="flex items-center gap-1.5">
                      <span className="w-1.5 h-1.5 bg-m-red rounded-full" />
                      <span className="text-[9px] font-mono text-m-red">NOT FOUND</span>
                    </div>
                  )}
                </div>

                {cliStatus && cliStatus.installed && (
                  <div className="space-y-1">
                    <p className="text-[9px] font-mono text-m-text-muted truncate">{cliStatus.path}</p>
                    <div className="flex items-center gap-2">
                      <span className="text-[9px] font-mono text-m-text-muted">v{cliStatus.version || '?'}</span>
                      {cliLatest && cliStatus.version && cliLatest !== cliStatus.version ? (
                        <div className="flex items-center gap-2">
                          <span className="text-[8px] font-mono text-m-yellow">UPDATE AVAILABLE: v{cliLatest}</span>
                          <button onClick={handleCliUpdate} disabled={cliUpdating}
                            className="px-2 py-0.5 text-[8px] font-mono tracking-widest bg-m-yellow/10 text-m-yellow border border-m-yellow/30 hover:bg-m-yellow/20 transition-all disabled:opacity-30 disabled:cursor-not-allowed">
                            {cliUpdating ? 'UPDATING...' : 'UPDATE'}
                          </button>
                        </div>
                      ) : cliLatest && cliStatus.version && cliLatest === cliStatus.version ? (
                        <span className="text-[8px] font-mono text-m-green">LATEST</span>
                      ) : null}
                    </div>
                  </div>
                )}

                {cliStatus && cliStatus.installed && !cliStatus.authenticated && (
                  <div className="bg-m-surface border border-m-yellow/20 px-3 py-2 space-y-2">
                    <p className="text-[9px] font-mono text-m-text-muted tracking-wider">
                      CLI FOUND BUT NOT LOGGED IN
                    </p>
                    <button onClick={handleCliLogin} disabled={cliLoginPending}
                      className="px-3 py-1.5 text-[9px] tracking-widest uppercase bg-m-cyan/10 text-m-cyan border border-m-cyan/30 hover:bg-m-cyan/20 transition-all disabled:opacity-30 disabled:cursor-not-allowed">
                      {cliLoginPending ? 'WAITING FOR LOGIN...' : 'LOGIN'}
                    </button>
                    {cliLoginPending && (
                      <p className="text-[8px] font-mono text-m-text-muted tracking-wider">
                        BROWSER OPENED — COMPLETE LOGIN THEN WAIT
                      </p>
                    )}
                  </div>
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
                  <p className="text-[8px] font-mono text-m-text-muted tracking-wider leading-relaxed">
                    01 — <span className="text-m-cyan cursor-pointer hover:underline" onClick={() => (window as any).runlog?.openUrl?.('https://docs.anthropic.com/en/docs/claude-code/overview')}>INSTALL CLAUDE CODE CLI</span><br/>
                    02 — RUN LOGIN ABOVE OR <span className="text-m-cyan">claude login</span> IN TERMINAL<br/>
                    03 — USES YOUR CLAUDE SUBSCRIPTION<br/>
                    <span className="text-m-text-muted">NO API TOKENS REQUIRED</span>
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Version info */}
      <div className="flex justify-between text-2xs font-mono text-m-text-muted">
        <span>runlog.exe v1.0.0</span>
        <span>LOCAL-FIRST // NO CLOUD // NO TELEMETRY</span>
      </div>

      {/* Sticky RESTART REQUIRED toast — shown when a setting that's only read
          at engine/process startup has been changed since launch. */}
      {restartDirty && (
        <div className="fixed bottom-5 right-5 z-50 border border-m-yellow/60 bg-m-card shadow-[0_0_24px_-8px_rgba(200,255,0,0.5)]">
          <div className="px-4 py-3 flex items-center gap-4">
            <div>
              <p className="label-tag text-m-yellow">RESTART REQUIRED</p>
              <p className="text-2xs font-mono text-m-text-muted mt-0.5">
                Some changes only apply on app restart.
              </p>
            </div>
            <button
              onClick={restartNow}
              className="px-3 py-1.5 text-2xs font-mono tracking-widest border border-m-yellow/60 text-m-yellow bg-m-yellow/10 hover:bg-m-yellow/20 transition-colors"
            >
              RESTART NOW
            </button>
            <button
              onClick={dismissRestart}
              className="px-2 py-1.5 text-2xs font-mono text-m-text-muted hover:text-m-text"
              aria-label="Cancel and revert"
              title="Cancel and revert pending changes"
            >
              ×
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
