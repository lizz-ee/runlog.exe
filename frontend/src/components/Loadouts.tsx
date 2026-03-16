import { useState } from 'react'
import { useStore } from '../lib/store'
import { createLoadout, getLoadouts } from '../lib/api'

export default function Loadouts() {
  const { loadouts, setLoadouts, runners } = useStore()
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState({
    name: '',
    runner_id: null as number | null,
    primary_weapon: '',
    secondary_weapon: '',
    heavy_weapon: '',
    notes: '',
  })

  async function handleSave() {
    await createLoadout({
      name: form.name || 'UNNAMED LOADOUT',
      runner_id: form.runner_id,
      primary_weapon: form.primary_weapon || null,
      secondary_weapon: form.secondary_weapon || null,
      heavy_weapon: form.heavy_weapon || null,
      notes: form.notes || null,
    })
    const updated = await getLoadouts()
    setLoadouts(updated)
    setShowForm(false)
    setForm({ name: '', runner_id: null, primary_weapon: '', secondary_weapon: '', heavy_weapon: '', notes: '' })
  }

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <p className="label-tag text-m-text-muted">SYSTEM / LOADOUTS</p>
          <h2 className="text-xl font-display font-black tracking-wider text-m-text mt-1">
            LOADOUTS
          </h2>
        </div>
        <button
          onClick={() => setShowForm(!showForm)}
          className={`px-4 py-2 text-xs tracking-widest uppercase border border-1 transition-all ${
            showForm
              ? 'border-m-red/30 text-m-red hover:bg-m-red/10'
              : 'border-m-green text-m-green hover:bg-m-green hover:text-m-black'
          }`}
        >
          {showForm ? 'CANCEL' : '+ NEW LOADOUT'}
        </button>
      </div>

      {showForm && (
        <div className="border border-1 border-m-border bg-m-card p-5 space-y-4">
          <input
            type="text"
            placeholder="LOADOUT NAME"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            className="w-full bg-m-surface border border-1 border-m-border px-3 py-2 text-xs font-mono text-m-text tracking-wider uppercase focus:outline-none focus:border-m-green/50"
          />

          <div className="grid grid-cols-3 gap-4">
            {(['primary_weapon', 'secondary_weapon', 'heavy_weapon'] as const).map((field) => (
              <div key={field}>
                <label className="label-tag text-m-text-muted block mb-1.5">
                  {field.replace('_', ' ').toUpperCase()}
                </label>
                <input
                  type="text"
                  value={form[field]}
                  onChange={(e) => setForm({ ...form, [field]: e.target.value })}
                  className="w-full bg-m-surface border border-1 border-m-border px-3 py-2 text-xs font-mono text-m-text focus:outline-none focus:border-m-green/50"
                />
              </div>
            ))}
          </div>

          <textarea
            placeholder="NOTES..."
            value={form.notes}
            onChange={(e) => setForm({ ...form, notes: e.target.value })}
            rows={2}
            className="w-full bg-m-surface border border-1 border-m-border px-3 py-2 text-xs font-mono text-m-text focus:outline-none focus:border-m-green/50 resize-none"
          />

          <button
            onClick={handleSave}
            className="w-full py-3 bg-m-green text-m-black text-xs tracking-[0.2em] font-bold uppercase hover:bg-m-green-dim transition-all"
          >
            SAVE LOADOUT
          </button>
        </div>
      )}

      {loadouts.length === 0 && !showForm ? (
        <div className="border border-1 border-m-border bg-m-card p-10 text-center">
          <p className="text-xs text-m-text-muted tracking-wider">NO LOADOUTS SAVED</p>
        </div>
      ) : (
        <div className="grid gap-[1px] bg-m-border md:grid-cols-2">
          {loadouts.map((lo) => (
            <div key={lo.id} className="bg-m-card p-4 space-y-3">
              <div className="flex items-center justify-between">
                <h3 className="text-xs font-bold tracking-wider text-m-text uppercase">{lo.name}</h3>
                <span className="label-tag text-m-text-muted">#{lo.id}</span>
              </div>
              <div className="space-y-1">
                {lo.primary_weapon && (
                  <div className="flex justify-between text-xs">
                    <span className="label-tag text-m-text-muted">PRIMARY</span>
                    <span className="text-m-text font-mono">{lo.primary_weapon}</span>
                  </div>
                )}
                {lo.secondary_weapon && (
                  <div className="flex justify-between text-xs">
                    <span className="label-tag text-m-text-muted">SECONDARY</span>
                    <span className="text-m-text font-mono">{lo.secondary_weapon}</span>
                  </div>
                )}
                {lo.heavy_weapon && (
                  <div className="flex justify-between text-xs">
                    <span className="label-tag text-m-text-muted">HEAVY</span>
                    <span className="text-m-text font-mono">{lo.heavy_weapon}</span>
                  </div>
                )}
              </div>
              {lo.notes && <p className="label-tag text-m-text-dim">{lo.notes}</p>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
