import { useState, useCallback, useEffect } from 'react'
import { useDropzone } from 'react-dropzone'
import { motion, AnimatePresence } from 'framer-motion'
import { parseScreenshots, createRun } from '../lib/api'
import { useStore } from '../lib/store'
import type { ParsedScreenshot } from '../lib/types'

export default function LogRun() {
  const { addRun, setView, pendingCapture, setPendingCapture } = useStore()
  const [parsing, setParsing] = useState(false)
  const [parsed, setParsed] = useState<ParsedScreenshot | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [previewUrls, setPreviewUrls] = useState<string[]>([])
  const [saving, setSaving] = useState(false)

  const [form, setForm] = useState({
    survived: null as boolean | null,
    kills: 0,
    combatant_eliminations: 0,
    runner_eliminations: 0,
    deaths: 0,
    assists: 0,
    map_name: '',
    duration_seconds: null as number | null,
    loot_value_total: 0,
    primary_weapon: '',
    secondary_weapon: '',
    notes: '',
  })

  // Auto-populate from hotkey/steam capture
  useEffect(() => {
    if (pendingCapture?.type === 'run' && pendingCapture.data) {
      const result = pendingCapture.data as ParsedScreenshot
      setParsed(result)
      setForm({
        survived: result.survived,
        kills: result.kills,
        combatant_eliminations: result.combatant_eliminations,
        runner_eliminations: result.runner_eliminations,
        deaths: result.deaths,
        assists: result.assists,
        map_name: result.map_name ?? '',
        duration_seconds: result.duration_seconds,
        loot_value_total: result.loot_value_total,
        primary_weapon: result.primary_weapon ?? '',
        secondary_weapon: result.secondary_weapon ?? '',
        notes: '',
      })
      setPendingCapture(null)
    }
  }, [pendingCapture])

  const onDrop = useCallback(async (files: File[]) => {
    if (!files.length) return
    setError(null)
    setParsed(null)
    setParsing(true)
    setPreviewUrls(files.map((f) => URL.createObjectURL(f)))

    try {
      const result = await parseScreenshots(files)
      setParsed(result)
      setForm({
        survived: result.survived,
        kills: result.kills,
        combatant_eliminations: result.combatant_eliminations,
        runner_eliminations: result.runner_eliminations,
        deaths: result.deaths,
        assists: result.assists,
        map_name: result.map_name ?? '',
        duration_seconds: result.duration_seconds,
        loot_value_total: result.loot_value_total,
        primary_weapon: result.primary_weapon ?? '',
        secondary_weapon: result.secondary_weapon ?? '',
        notes: '',
      })
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? 'Failed to parse screenshot')
    } finally {
      setParsing(false)
    }
  }, [])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { 'image/*': ['.png', '.jpg', '.jpeg', '.webp'] },
    maxFiles: 3,
  })

  async function handleSave() {
    setSaving(true)
    try {
      const run = await createRun({
        survived: form.survived,
        kills: form.kills,
        deaths: form.deaths,
        assists: form.assists,
        map_name: form.map_name || null,
        duration_seconds: form.duration_seconds,
        loot_value_total: form.loot_value_total,
        loot_extracted: parsed?.loot_extracted,
        notes: form.notes || null,
      })
      addRun(run)
      setView('dashboard')
    } catch {
      setError('Failed to save run')
    } finally {
      setSaving(false)
    }
  }

  const formatDuration = (secs: number | null) => {
    if (!secs) return '—'
    return `${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, '0')}`
  }

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div>
        <p className="label-tag text-m-text-muted">SYSTEM / LOG</p>
        <h2 className="text-xl font-display font-black tracking-wider text-m-text mt-1">
          LOG RUN
        </h2>
      </div>

      {/* Drop Zone */}
      <div
        {...getRootProps()}
        className={`border border-1 cursor-pointer transition-all ${
          isDragActive
            ? 'border-m-green bg-m-green-glow'
            : 'border-m-border hover:border-m-green/30 bg-m-card'
        } ${parsing ? '' : ''}`}
      >
        <input {...getInputProps()} />
        <div className="p-10 text-center">
          {parsing ? (
            <div className="space-y-3">
              <div className="w-6 h-6 border border-1 border-m-green border-t-transparent rounded-full animate-spin mx-auto" />
              <p className="text-xs tracking-widest text-m-green uppercase">
                PARSING WITH CLAUDE VISION...
              </p>
            </div>
          ) : (
            <div className="space-y-3">
              <div className="w-10 h-10 border border-1 border-m-border flex items-center justify-center mx-auto">
                <span className="text-m-text-muted text-lg">+</span>
              </div>
              <p className="text-xs tracking-wider text-m-text uppercase">
                DROP RESULTS SCREENSHOTS
              </p>
              <p className="label-tag text-m-text-muted">
                STATS + LOADOUT TABS — UP TO 3 IMAGES
              </p>
            </div>
          )}
        </div>
      </div>

      {error && (
        <div className="border border-1 border-m-red/30 bg-m-red-glow p-4">
          <p className="text-xs text-m-red">{error}</p>
        </div>
      )}

      <AnimatePresence>
        {parsed && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="space-y-4"
          >
            {/* Previews */}
            {previewUrls.length > 0 && (
              <div className={`grid gap-[1px] bg-m-border ${previewUrls.length > 1 ? 'grid-cols-2' : 'grid-cols-1'}`}>
                {previewUrls.map((url, i) => (
                  <div key={i} className="bg-m-black">
                    <img src={url} alt={`Screenshot ${i + 1}`} className="w-full max-h-56 object-contain" />
                  </div>
                ))}
              </div>
            )}

            {/* Confidence */}
            <div className="flex items-center gap-3">
              <span className={`label-tag px-2 py-1 border border-1 ${
                parsed.confidence === 'high'
                  ? 'border-m-green/30 text-m-green'
                  : parsed.confidence === 'medium'
                  ? 'border-m-yellow/30 text-m-yellow'
                  : 'border-m-red/30 text-m-red'
              }`}>
                {parsed.confidence?.toUpperCase()} CONFIDENCE
              </span>
              <span className="label-tag text-m-text-muted">REVIEW PARSED DATA</span>
            </div>

            {/* Form */}
            <div className="border border-1 border-m-border bg-m-card">
              {/* Outcome */}
              <div className="grid grid-cols-2 gap-[1px] bg-m-border">
                <button
                  onClick={() => setForm({ ...form, survived: true })}
                  className={`py-4 text-xs tracking-[0.2em] font-bold transition-all ${
                    form.survived === true
                      ? 'bg-m-green/10 text-m-green border-b-2 border-m-green'
                      : 'bg-m-card text-m-text-muted hover:text-m-green'
                  }`}
                >
                  EXFILTRATED
                </button>
                <button
                  onClick={() => setForm({ ...form, survived: false })}
                  className={`py-4 text-xs tracking-[0.2em] font-bold transition-all ${
                    form.survived === false
                      ? 'bg-m-red/10 text-m-red border-b-2 border-m-red'
                      : 'bg-m-card text-m-text-muted hover:text-m-red'
                  }`}
                >
                  KIA
                </button>
              </div>

              <div className="p-5 space-y-4">
                {/* K/D/A */}
                <div className="grid grid-cols-4 gap-4">
                  <Field label="COMBATANT ELIMS" value={form.combatant_eliminations} onChange={(v) => setForm({ ...form, combatant_eliminations: v, kills: v + form.runner_eliminations })} />
                  <Field label="RUNNER ELIMS" value={form.runner_eliminations} onChange={(v) => setForm({ ...form, runner_eliminations: v, kills: form.combatant_eliminations + v })} />
                  <Field label="DEATHS" value={form.deaths} onChange={(v) => setForm({ ...form, deaths: v })} />
                  <Field label="CREW REVIVES" value={form.assists} onChange={(v) => setForm({ ...form, assists: v })} />
                </div>

                {/* Weapons */}
                <div className="grid grid-cols-2 gap-4">
                  <TextInput label="PRIMARY WEAPON" value={form.primary_weapon} onChange={(v) => setForm({ ...form, primary_weapon: v })} />
                  <TextInput label="SECONDARY WEAPON" value={form.secondary_weapon} onChange={(v) => setForm({ ...form, secondary_weapon: v })} />
                </div>

                {/* Map, Loot, Duration */}
                <div className="grid grid-cols-3 gap-4">
                  <TextInput label="MAP" value={form.map_name} onChange={(v) => setForm({ ...form, map_name: v })} />
                  <Field label="INVENTORY VALUE" value={form.loot_value_total} onChange={(v) => setForm({ ...form, loot_value_total: v })} />
                  <div>
                    <label className="label-tag text-m-text-muted block mb-1.5">RUN TIME</label>
                    <div className="bg-m-surface border border-1 border-m-border px-3 py-2 text-xs font-mono text-m-text">
                      {formatDuration(form.duration_seconds)}
                    </div>
                  </div>
                </div>

                {/* Notes */}
                <div>
                  <label className="label-tag text-m-text-muted block mb-1.5">NOTES</label>
                  <textarea
                    value={form.notes}
                    onChange={(e) => setForm({ ...form, notes: e.target.value })}
                    rows={2}
                    placeholder="..."
                    className="w-full bg-m-surface border border-1 border-m-border px-3 py-2 text-xs font-mono text-m-text focus:outline-none focus:border-m-green/50 resize-none"
                  />
                </div>

                {/* Loot Items */}
                {parsed.loot_extracted && parsed.loot_extracted.length > 0 && (
                  <div>
                    <label className="label-tag text-m-text-muted block mb-2">LOOT MANIFEST</label>
                    <div className="border border-1 border-m-border divide-y divide-m-border">
                      {parsed.loot_extracted.map((item, i) => (
                        <div key={i} className="flex justify-between text-xs px-3 py-1.5 bg-m-surface">
                          <span className="text-m-text">{item.name}</span>
                          <span className="text-m-yellow font-mono">${item.value}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Save */}
                <button
                  onClick={handleSave}
                  disabled={saving}
                  className="w-full py-3 bg-m-green text-m-black text-xs tracking-[0.2em] font-bold uppercase hover:bg-m-green-dim transition-all disabled:opacity-50"
                >
                  {saving ? 'SAVING...' : 'CONFIRM & SAVE RUN'}
                </button>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

function Field({ label, value, onChange }: { label: string; value: number; onChange: (v: number) => void }) {
  return (
    <div>
      <label className="label-tag text-m-text-muted block mb-1.5">{label}</label>
      <input
        type="number"
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full bg-m-surface border border-1 border-m-border px-3 py-2 text-xs font-mono text-m-text text-center focus:outline-none focus:border-m-green/50"
      />
    </div>
  )
}

function TextInput({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <div>
      <label className="label-tag text-m-text-muted block mb-1.5">{label}</label>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full bg-m-surface border border-1 border-m-border px-3 py-2 text-xs font-mono text-m-text focus:outline-none focus:border-m-green/50"
      />
    </div>
  )
}
