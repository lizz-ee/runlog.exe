import { useEffect, useState } from 'react'
import { getClips, getClipUrl } from '../lib/api'
import type { Clip } from '../lib/types'

const TYPE_COLORS: Record<string, string> = {
  kill: 'text-m-red border-m-red/30 bg-m-red-glow',
  death: 'text-m-red border-m-red/30',
  extraction: 'text-m-green border-m-green/30 bg-m-green-glow',
  loot: 'text-m-yellow border-m-yellow/30',
  close_call: 'text-m-cyan border-m-cyan/30',
  funny: 'text-m-text border-m-border',
  highlight: 'text-m-text border-m-border',
}

function formatDate(epoch: number): string {
  const d = new Date(epoch * 1000)
  return d.toLocaleDateString('en-US', {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

export default function Highlights() {
  const [clips, setClips] = useState<Clip[]>([])
  const [playing, setPlaying] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function load() {
      try {
        const c = await getClips()
        setClips(c)
      } catch (e) {
        console.error('Failed to load clips:', e)
      }
      setLoading(false)
    }
    load()
  }, [])

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-end justify-between">
        <div>
          <p className="label-tag text-m-green">CAPTURE / HIGHLIGHTS</p>
          <h2 className="text-xl font-display font-black tracking-wider text-m-text mt-1">
            HIGHLIGHTS
          </h2>
        </div>
        <p className="label-tag text-m-text-muted">
          {clips.length} CLIP{clips.length !== 1 ? 'S' : ''}
        </p>
      </div>

      {/* Now Playing */}
      {playing && (
        <div className="bg-m-card border border-m-green/40 p-2">
          <video
            src={getClipUrl(playing)}
            controls
            autoPlay
            className="w-full max-h-[500px]"
            onEnded={() => setPlaying(null)}
          />
          <div className="flex items-center justify-between px-2 py-2">
            <span className="text-xs font-mono text-m-text">{playing}</span>
            <button
              onClick={() => setPlaying(null)}
              className="label-tag text-m-text-muted hover:text-m-red transition-colors"
            >
              CLOSE
            </button>
          </div>
        </div>
      )}

      {/* Clips Grid */}
      {loading ? (
        <div className="bg-m-card border border-m-border p-10 text-center">
          <p className="text-m-text-muted text-sm">LOADING CLIPS...</p>
        </div>
      ) : clips.length === 0 ? (
        <div className="bg-m-card border border-m-border p-10 text-center">
          <p className="text-m-text-muted text-sm">NO HIGHLIGHTS YET</p>
          <p className="label-tag text-m-text-muted mt-2">
            CLIPS ARE AUTO-GENERATED AFTER EACH RUN IS PROCESSED BY SONNET
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-4">
          {clips.map((clip) => {
            const colorClass = TYPE_COLORS[clip.type] || TYPE_COLORS.highlight
            return (
              <button
                key={clip.filename}
                onClick={() => setPlaying(clip.filename)}
                className={`bg-m-card border border-m-border p-4 text-left transition-all hover:border-m-green/40 hover:bg-m-surface ${
                  playing === clip.filename ? 'border-m-green/60' : ''
                }`}
              >
                <div className="flex items-center justify-between mb-2">
                  <span className={`label-tag px-2 py-0.5 border ${colorClass}`}>
                    {clip.type.toUpperCase().replace('_', ' ')}
                  </span>
                  <span className="label-tag text-m-text-muted">
                    {clip.size_mb} MB
                  </span>
                </div>
                <p className="text-xs font-mono text-m-text truncate">
                  {clip.filename}
                </p>
                <p className="label-tag text-m-text-muted mt-1">
                  {formatDate(clip.created)}
                </p>
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
