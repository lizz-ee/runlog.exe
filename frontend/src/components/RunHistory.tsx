import { useEffect, useState, useCallback, useRef } from 'react'
import { format } from 'date-fns'
import axios from 'axios'
import { getRuns, updateRun, getClips, getClipUrl, apiBase, toggleFavorite, cutClip, deleteClip, deleteKeptRecording } from '../lib/api'
import { useStore } from '../lib/store'
import { formatTime } from '../lib/utils'
import type { Run, Clip } from '../lib/types'
import rankedIcon from '../assets/ranked.png'

// Grade colors — rarity tier system matching NEURAL.LINK
// S=gold, A=purple, B=blue, C=green, D/F=grey
const GRADE_COLORS: Record<string, { text: string; border: string; bg: string }> = {
  S: { text: '#FFD700', border: '#FFD70060', bg: '#FFD70015' },
  A: { text: '#A855F7', border: '#A855F760', bg: '#A855F715' },
  B: { text: '#3B82F6', border: '#3B82F660', bg: '#3B82F615' },
  C: { text: '#22C55E', border: '#22C55E60', bg: '#22C55E15' },
  D: { text: '#888888', border: '#88888860', bg: '#88888815' },
  F: { text: '#888888', border: '#88888860', bg: '#88888815' },
}

const SHELLS = ['Triage', 'Assassin', 'Recon', 'Vandal', 'Destroyer', 'Thief', 'Rook']

/* ── Hexagon Favorite Icon ── */
function HexFavorite({ filled, onClick }: { filled: boolean; onClick: (e: React.MouseEvent) => void }) {
  return (
    <button
      onClick={onClick}
      className={`transition-all ${filled ? 'text-[#c8ff00]' : 'text-m-text-muted/30 hover:text-[#c8ff00]/50'}`}
      title={filled ? 'Unfavorite' : 'Favorite'}
    >
      <svg width="14" height="16" viewBox="0 0 14 16">
        {filled ? (
          <polygon points="7,0 13.5,4 13.5,12 7,16 0.5,12 0.5,4" fill="currentColor" />
        ) : (
          <polygon points="7,0 13.5,4 13.5,12 7,16 0.5,12 0.5,4" fill="none" stroke="currentColor" strokeWidth="1.2" />
        )}
      </svg>
    </button>
  )
}

/* ── Shell Picker (inline edit) ── */
function ShellPicker({ run, onUpdate }: { run: Run; onUpdate: () => void }) {
  const [editing, setEditing] = useState(false)
  const { runners } = useStore()

  const handleSelect = async (name: string) => {
    setEditing(false)
    const runner = runners.find(r => r.name.toLowerCase() === name.toLowerCase())
    try {
      await updateRun(run.id, { runner_id: runner?.id ?? null } as any)
      onUpdate()
    } catch (e) {
      console.error('Failed to update shell:', e)
    }
  }

  if (!editing) {
    return (
      <button
        onClick={(e) => { e.stopPropagation(); setEditing(true) }}
        className="text-[9px] font-mono text-m-text-muted/40 hover:text-m-green transition-colors ml-3 tracking-wider"
        title="Change shell"
      >
        CHANGE SHELL ✎
      </button>
    )
  }

  return (
    <div className="flex gap-1 flex-wrap mt-1" onClick={e => e.stopPropagation()}>
      {SHELLS.map(name => (
        <button
          key={name}
          onClick={(e) => { e.stopPropagation(); handleSelect(name) }}
          className={`text-[9px] font-mono px-1.5 py-0.5 border transition-all ${
            run.shell_name === name
              ? 'border-m-green text-m-green bg-m-green-glow'
              : 'border-m-border text-m-text-muted hover:text-m-text hover:border-m-text'
          }`}
        >
          {name.toUpperCase()}
        </button>
      ))}
      <button
        onClick={(e) => { e.stopPropagation(); setEditing(false) }}
        className="text-[9px] font-mono px-1 text-m-text-muted hover:text-m-red"
      >
        ✕
      </button>
    </div>
  )
}

/* ── Clip Timeline — video player with seekbar + IN/OUT editor ── */

function ClipTimeline({ src, clipPath, label: _label, onClose, onClipCreated, onPlayClip }: {
  src: string
  clipPath: string
  label: string
  onClose: () => void
  onClipCreated: () => void
  onPlayClip?: (clipPath: string) => void
}) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const timelineRef = useRef<HTMLDivElement>(null)
  const nameInputRef = useRef<HTMLInputElement>(null)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [isPaused, setIsPaused] = useState(false)
  const [isSeeking, setIsSeeking] = useState(false)
  const [inPoint, setInPoint] = useState<number | null>(null)
  const [outPoint, setOutPoint] = useState<number | null>(null)
  const [isNaming, setIsNaming] = useState(false)
  const [clipName, setClipName] = useState('')
  const [isCreating, setIsCreating] = useState(false)
  const [isLooping, setIsLooping] = useState(true)
  const [draggingMarker, setDraggingMarker] = useState<'in' | 'out' | null>(null)

  // Seek from mouse position on timeline
  const seekFromEvent = useCallback((e: MouseEvent | React.MouseEvent) => {
    if (!timelineRef.current || !videoRef.current || !duration) return
    const rect = timelineRef.current.getBoundingClientRect()
    const x = Math.max(0, Math.min(e.clientX - rect.left, rect.width))
    const time = (x / rect.width) * duration
    videoRef.current.currentTime = time
    setCurrentTime(time)
  }, [duration])

  // Convert mouse X to time on timeline
  const mouseToTime = useCallback((e: MouseEvent) => {
    if (!timelineRef.current || !duration) return null
    const rect = timelineRef.current.getBoundingClientRect()
    const x = Math.max(0, Math.min(e.clientX - rect.left, rect.width))
    return (x / rect.width) * duration
  }, [duration])

  // Global mouse handlers for timeline drag + marker drag
  useEffect(() => {
    if (!isSeeking && !draggingMarker) return
    const handleMove = (e: MouseEvent) => {
      if (draggingMarker) {
        const time = mouseToTime(e)
        if (time === null) return
        if (draggingMarker === 'in') {
          const clamped = outPoint !== null ? Math.min(time, outPoint - 0.1) : time
          setInPoint(Math.max(0, clamped))
        } else {
          const clamped = inPoint !== null ? Math.max(time, inPoint + 0.1) : time
          setOutPoint(Math.min(duration, clamped))
        }
      } else {
        seekFromEvent(e)
      }
    }
    const handleUp = () => {
      setIsSeeking(false)
      setDraggingMarker(null)
    }
    window.addEventListener('mousemove', handleMove)
    window.addEventListener('mouseup', handleUp)
    return () => {
      window.removeEventListener('mousemove', handleMove)
      window.removeEventListener('mouseup', handleUp)
    }
  }, [isSeeking, draggingMarker, seekFromEvent, mouseToTime, inPoint, outPoint, duration])

  // Focus name input when naming mode activates
  useEffect(() => {
    if (isNaming && nameInputRef.current) nameInputRef.current.focus()
  }, [isNaming])

  const handleSetIn = (e: React.MouseEvent) => {
    e.stopPropagation()
    const time = videoRef.current?.currentTime ?? 0
    setInPoint(time)
    if (outPoint !== null && outPoint <= time) setOutPoint(null)
  }

  const handleSetOut = (e: React.MouseEvent) => {
    e.stopPropagation()
    const time = videoRef.current?.currentTime ?? 0
    if (inPoint !== null && time <= inPoint) return
    setOutPoint(time)
    // Jump to IN and start looping preview
    if (inPoint !== null && videoRef.current) {
      videoRef.current.currentTime = inPoint
      videoRef.current.play()
    }
  }

  const handleClear = (e: React.MouseEvent) => {
    e.stopPropagation()
    setInPoint(null)
    setOutPoint(null)
    setIsNaming(false)
    setClipName('')
  }

  const handleCreateClick = (e: React.MouseEvent) => {
    e.stopPropagation()
    setIsNaming(true)
  }

  const handleNameSubmit = async () => {
    if (!clipName.trim() || inPoint === null || outPoint === null) return
    setIsCreating(true)
    try {
      const result = await cutClip(clipPath, inPoint, outPoint, clipName.trim())
      setInPoint(null)
      setOutPoint(null)
      setIsNaming(false)
      setClipName('')
      // Load the new clip into the player
      if (result.filename && onPlayClip) {
        onPlayClip(result.filename)
      }
      // Refresh clips list
      onClipCreated()
      setTimeout(() => onClipCreated(), 1500)
    } catch (err) {
      console.error('Clip creation failed:', err)
    } finally {
      setIsCreating(false)
    }
  }

  const handleNameKeyDown = (e: React.KeyboardEvent) => {
    e.stopPropagation()
    if (e.key === 'Enter') handleNameSubmit()
    if (e.key === 'Escape') { setIsNaming(false); setClipName('') }
  }

  return (
    <div className="mt-3 rounded-2xl overflow-hidden shadow-[0_4px_24px_rgba(0,0,0,0.6)] relative bg-m-black" onClick={e => e.stopPropagation()}>
      {/* Video */}
      <video
        ref={videoRef}
        src={src}
        autoPlay
        loop={isLooping}
        className="w-full"
        onTimeUpdate={() => {
          const t = videoRef.current?.currentTime ?? 0
          setCurrentTime(t)
          // Loop: between IN/OUT if both set, or whole video if no markers
          if (isLooping) {
            if (inPoint !== null && outPoint !== null && t >= outPoint) {
              videoRef.current!.currentTime = inPoint
            }
          }
        }}
        onLoadedMetadata={() => setDuration(videoRef.current?.duration ?? 0)}
        onPlay={() => setIsPaused(false)}
        onPause={() => setIsPaused(true)}
        onClick={(e) => {
          e.stopPropagation()
          const vid = videoRef.current
          if (vid) vid.paused ? vid.play() : vid.pause()
        }}
        style={{ cursor: 'pointer' }}
      />

      {/* CREATE CLIP — absolute center of the entire pill, above controls */}
      {inPoint !== null && outPoint !== null && duration > 0 && !isNaming && (
        <div className="absolute bottom-[90px] left-1/2 -translate-x-1/2 z-30">
          <button onClick={handleCreateClick}
            className="label-tag px-3 py-1 border border-[#c8ff00]/60 text-[#c8ff00] bg-[#c8ff00]/10 hover:bg-[#c8ff00]/20 transition-all whitespace-nowrap shadow-[0_2px_8px_rgba(0,0,0,0.6)]">
            CREATE CLIP // {formatTime(outPoint - inPoint)}
          </button>
        </div>
      )}
      {isNaming && inPoint !== null && outPoint !== null && duration > 0 && (
        <div className="absolute bottom-[90px] left-1/2 -translate-x-1/2 z-30 flex items-center gap-1.5">
          <input
            ref={nameInputRef}
            value={clipName}
            onChange={(e) => setClipName(e.target.value)}
            onKeyDown={handleNameKeyDown}
            onClick={(e) => e.stopPropagation()}
            placeholder="name this clip..."
            disabled={isCreating}
            className="text-[11px] font-mono tracking-wider bg-m-black/90 border border-[#c8ff00]/40 text-[#c8ff00] px-2 py-0.5 w-44 focus:outline-none placeholder:text-m-text-muted/40 shadow-[0_2px_8px_rgba(0,0,0,0.6)]"
          />
          {isCreating ? (
            <span className="label-tag text-[#c8ff00] animate-pulse">CUTTING...</span>
          ) : (
            <button onClick={(e) => { e.stopPropagation(); setIsNaming(false); setClipName('') }}
              className="label-tag text-m-text-muted hover:text-m-red transition-colors">
              ✕
            </button>
          )}
        </div>
      )}

      {/* Bottom controls overlay */}
      <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/90 via-black/60 to-transparent pt-10 pb-2 px-3 rounded-b-2xl">

        {/* Timeline */}
        <div
          ref={timelineRef}
          className="relative h-5 cursor-pointer mb-2 group/tl"
          onMouseDown={(e) => { e.stopPropagation(); setIsSeeking(true); seekFromEvent(e) }}
        >
          {/* Track background */}
          <div className="absolute left-0 right-0 top-1/2 -translate-y-1/2 h-[3px] bg-white/10 rounded-full" />

          {/* IN/OUT highlighted region */}
          {inPoint !== null && outPoint !== null && duration > 0 && (
            <div
              className="absolute top-1/2 -translate-y-1/2 h-[5px] bg-[#c8ff00]/40 rounded-full"
              style={{
                left: `${(inPoint / duration) * 100}%`,
                width: `${((outPoint - inPoint) / duration) * 100}%`,
              }}
            />
          )}

          {/* Played portion */}
          {duration > 0 && (
            <div
              className="absolute left-0 top-1/2 -translate-y-1/2 h-[3px] bg-m-cyan/50 rounded-full"
              style={{ width: `${(currentTime / duration) * 100}%` }}
            />
          )}

          {/* IN marker — draggable */}
          {inPoint !== null && duration > 0 && (
            <div
              className="absolute top-0 bottom-0 w-[2px] bg-[#c8ff00]"
              style={{ left: `${(inPoint / duration) * 100}%` }}
            >
              <span
                className={`absolute -top-4 left-1/2 -translate-x-1/2 text-[8px] font-mono font-bold tracking-widest cursor-ew-resize select-none px-1 py-0.5 rounded transition-colors ${
                  draggingMarker === 'in' ? 'text-m-cyan bg-m-cyan/10' : 'text-[#c8ff00] hover:text-m-cyan'
                }`}
                style={{ zIndex: 30, textShadow: '0 0 4px rgba(200,255,0,0.5)' }}
                onMouseDown={(e) => { e.stopPropagation(); e.preventDefault(); setDraggingMarker('in') }}
              >IN</span>
            </div>
          )}

          {/* OUT marker — draggable */}
          {outPoint !== null && duration > 0 && (
            <div
              className="absolute top-0 bottom-0 w-[2px] bg-[#c8ff00]"
              style={{ left: `${(outPoint / duration) * 100}%` }}
            >
              <span
                className={`absolute -top-4 left-1/2 -translate-x-1/2 text-[8px] font-mono font-bold tracking-widest cursor-ew-resize select-none px-1 py-0.5 rounded transition-colors ${
                  draggingMarker === 'out' ? 'text-m-cyan bg-m-cyan/10' : 'text-[#c8ff00] hover:text-m-cyan'
                }`}
                style={{ zIndex: 30, textShadow: '0 0 4px rgba(200,255,0,0.5)' }}
                onMouseDown={(e) => { e.stopPropagation(); e.preventDefault(); setDraggingMarker('out') }}
              >OUT</span>
            </div>
          )}

          {/* Playhead */}
          {duration > 0 && (
            <div
              className="absolute top-1/2 -translate-y-1/2 w-3 h-3 bg-m-cyan rounded-full border border-m-cyan -translate-x-1/2"
              style={{
                left: `${(currentTime / duration) * 100}%`,
                boxShadow: '0 0 8px rgba(0,221,255,0.6)',
              }}
            />
          )}
        </div>

        {/* Controls — CSS Grid full width, timecode absolutely positioned left */}
        <div className="relative" style={{ height: 30 }}>
          {/* Far left: timecode — absolute so it doesn't affect grid */}
          <span className="absolute left-0 top-1/2 -translate-y-1/2 text-[11px] font-mono text-m-text tabular-nums tracking-wider whitespace-nowrap">
            {formatTime(currentTime)} // {formatTime(duration)}
          </span>

          {/* Grid: 3 columns, PLAY locked center, takes full width */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr auto 1fr', alignItems: 'center', height: '100%' }}>
          {/* LEFT column — loop + IN, right-aligned */}
          <div className="flex items-center justify-end gap-2">
            <button onClick={(e) => {
              e.stopPropagation()
              const newLooping = !isLooping
              setIsLooping(newLooping)
              if (newLooping && videoRef.current) {
                // Restart: jump to IN if set, otherwise start of video
                videoRef.current.currentTime = inPoint ?? 0
                videoRef.current.play()
              }
            }}
              className={`label-tag px-2 py-1 border transition-all flex items-center ${
                isLooping
                  ? 'border-[#c8ff00]/60 text-[#c8ff00] bg-[#c8ff00]/10'
                  : 'border-m-border/40 text-m-text-muted hover:text-m-text'
              }`}
              title={isLooping ? 'Disable loop' : 'Enable loop'}>
              ⟳
            </button>
            <button onClick={handleSetIn}
              className={`label-tag px-3 py-1 border transition-all whitespace-nowrap flex items-center ${
                inPoint !== null
                  ? 'border-[#c8ff00]/60 text-[#c8ff00] bg-[#c8ff00]/10'
                  : 'border-m-border/60 text-m-text hover:text-[#c8ff00] hover:border-[#c8ff00]/40'
              }`}>
              [ IN {inPoint !== null ? formatTime(inPoint) : '—'}
            </button>
          </div>

          {/* CENTER column — PLAY only, never moves */}
          <div className="mx-2">
            <button onClick={(e) => {
              e.stopPropagation()
              const vid = videoRef.current
              if (vid) vid.paused ? vid.play() : vid.pause()
            }} className="label-tag px-4 py-1 border border-m-cyan/40 text-m-cyan hover:bg-m-cyan/10 transition-all whitespace-nowrap flex items-center">
              {isPaused ? '▶ PLAY' : '⏸ PAUSE'}
            </button>
          </div>

          {/* RIGHT column — OUT + clear + close, left-aligned */}
          <div className="flex items-center justify-start gap-2">
            <button onClick={handleSetOut}
              className={`label-tag px-3 py-1 border transition-all whitespace-nowrap flex items-center ${
                outPoint !== null
                  ? 'border-[#c8ff00]/60 text-[#c8ff00] bg-[#c8ff00]/10'
                  : 'border-m-border/60 text-m-text hover:text-[#c8ff00] hover:border-[#c8ff00]/40'
              }`}>
              OUT {outPoint !== null ? formatTime(outPoint) : '—'} ]
            </button>
            <button onClick={(inPoint !== null || outPoint !== null) ? handleClear : undefined}
              className={`label-tag px-2 py-1 border transition-all flex items-center ${
                inPoint !== null || outPoint !== null
                  ? 'border-m-red/40 text-m-red hover:bg-m-red/10 cursor-pointer'
                  : 'border-m-border/40 text-m-text-muted/30 cursor-default'
              }`}>
              ✕
            </button>
            <button onClick={(e) => { e.stopPropagation(); onClose() }}
              className="label-tag px-3 py-1 border border-m-border/60 text-m-text hover:text-m-red hover:border-m-red/40 transition-colors whitespace-nowrap flex items-center ml-auto">
              CLOSE
            </button>
          </div>
          </div>
        </div>
      </div>
    </div>
  )
}

/* ── Clip Pill — pill-shaped card with sprite scrub ── */
function ClipPill({ label, thumbnail, sprite, spriteCols, spriteRows, spriteFrames, isActive, onPlay, onDelete }: {
  label: string
  thumbnail: string | null
  sprite: string | null
  spriteCols: number | null
  spriteRows: number | null
  spriteFrames: number | null
  isActive: boolean
  onPlay: (e: React.MouseEvent) => void
  onDelete?: () => void
}) {
  const pillRef = useRef<HTMLDivElement>(null)
  const [scrubbing, setScrubbing] = useState(false)
  const [scrubProgress, setScrubProgress] = useState(0)
  const [spritePos, setSpritePos] = useState<{ x: number; y: number } | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [deleting, setDeleting] = useState(false)

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (!sprite || !spriteCols || !spriteRows || !spriteFrames || !pillRef.current) return
    const rect = pillRef.current.getBoundingClientRect()
    const x = Math.max(0, Math.min(e.clientX - rect.left, rect.width))
    const progress = x / Math.max(1, rect.width)
    const frameIdx = Math.min(Math.floor(progress * spriteFrames), spriteFrames - 1)
    const col = frameIdx % spriteCols
    const row = Math.floor(frameIdx / spriteCols)
    // Use percentage-based positioning so it scales to any pill size
    const xPct = (col / (spriteCols - 1 || 1)) * 100
    const yPct = (row / (spriteRows - 1 || 1)) * 100
    setSpritePos({ x: xPct, y: yPct })
    setScrubProgress(progress)
    setScrubbing(true)
  }, [sprite, spriteCols, spriteRows, spriteFrames])

  const handleMouseLeave = useCallback(() => {
    setScrubbing(false)
    setScrubProgress(0)
    setSpritePos(null)
  }, [])

  const hasThumbnail = !!thumbnail
  const hasSprite = !!sprite && !!spriteCols

  return (
    <div className="relative group/clip" ref={pillRef}
      onMouseMove={(e) => {
        if (hasSprite) handleMouseMove(e)
        else if (pillRef.current) {
          const rect = pillRef.current.getBoundingClientRect()
          const x = Math.max(0, Math.min(e.clientX - rect.left, rect.width))
          setScrubProgress(x / Math.max(1, rect.width))
          setScrubbing(true)
        }
      }}
      onMouseLeave={() => {
        if (hasSprite) handleMouseLeave()
        setScrubbing(false)
        setScrubProgress(0)
      }}
    >
      <button
        onClick={onPlay}
        className={`w-full rounded-2xl overflow-hidden text-left transition-all relative ${
          isActive
            ? 'ring-2 ring-m-cyan shadow-[0_0_15px_rgba(0,221,255,0.3)]'
            : 'shadow-[0_2px_12px_rgba(0,0,0,0.5)] hover:shadow-[0_4px_20px_rgba(0,0,0,0.7)]'
        }`}
        style={{ aspectRatio: '16/9' }}
      >
        {/* Background: thumbnail, sprite scrub, or placeholder */}
        {scrubbing && hasSprite ? (
          <div className="absolute inset-0 bg-m-black" style={{
            backgroundImage: `url(${sprite})`,
            backgroundPosition: spritePos ? `${spritePos.x}% ${spritePos.y}%` : '0% 0%',
            backgroundSize: `${(spriteCols || 1) * 100}% ${(spriteRows || 1) * 100}%`,
          }} />
        ) : hasThumbnail ? (
          <img src={thumbnail} alt="" className="absolute inset-0 w-full h-full object-cover"
            onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }} />
        ) : (
          <div className="absolute inset-0 bg-m-border/10 flex items-center justify-center">
            <div className="flex flex-col items-center gap-1">
              <svg width="20" height="20" viewBox="0 0 16 16" fill="currentColor" className="text-m-cyan/60">
                <path d="M4 2l10 6-10 6V2z"/>
              </svg>
              <span className="text-[9px] font-mono text-m-cyan/60 tracking-widest">FULL RECORDING</span>
            </div>
          </div>
        )}

        {/* Bottom bar: scrub track + label */}
        <div className="absolute bottom-0 left-0 right-0 pointer-events-none">
          {/* Gray track background */}
          <div className="relative h-6 bg-black/50 flex items-center justify-center">
            {/* Track line */}
            <div className="absolute left-0 right-0 h-[2px] bg-white/10 rounded-full" />
            {/* Green cursor — only visible while scrubbing */}
            {scrubbing && (
              <div
                className="absolute top-1 bottom-1 w-[2px] rounded-full"
                style={{
                  left: `${scrubProgress * 100}%`,
                  backgroundColor: '#c8ff00',
                  boxShadow: '0 0 6px rgba(200,255,0,0.6), 0 0 12px rgba(200,255,0,0.3)',
                }}
              />
            )}
            {/* Label text on top */}
            <span className="relative z-10 text-[10px] font-mono font-bold tracking-widest text-m-cyan drop-shadow-[0_1px_3px_rgba(0,0,0,0.9)]">
              {label}
            </span>
          </div>
        </div>
      </button>

      {/* Hover delete X */}
      {onDelete && !confirmDelete && !deleting && (
        <button
          onClick={(e) => { e.stopPropagation(); setConfirmDelete(true) }}
          className="absolute top-1 right-1 z-20 w-5 h-5 flex items-center justify-center rounded-full bg-black/70 text-m-text-muted/60 hover:text-m-red hover:bg-black/90 transition-all opacity-0 group-hover/clip:opacity-100"
          title="Delete"
        >
          <svg width="8" height="8" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <path d="M2 2l8 8M10 2l-8 8"/>
          </svg>
        </button>
      )}

      {/* Deleting animation overlay */}
      {deleting && (
        <div className="absolute inset-0 z-30 rounded-2xl overflow-hidden pointer-events-none"
          onClick={(e) => e.stopPropagation()}>
          {/* Red wipe sweeping left to right */}
          <div className="absolute inset-0 bg-m-red/40 animate-wipe-delete" />
          {/* Scanline effect */}
          <div className="absolute inset-0 bg-[repeating-linear-gradient(0deg,transparent,transparent_2px,rgba(0,0,0,0.15)_2px,rgba(0,0,0,0.15)_4px)]" />
          {/* DELETING text */}
          <div className="absolute inset-0 flex items-center justify-center">
            <span className="text-[11px] font-mono font-bold tracking-[0.3em] text-m-red drop-shadow-[0_0_8px_rgba(255,0,68,0.8)] animate-pulse">
              DELETING
            </span>
          </div>
        </div>
      )}

      {/* Confirmation overlay */}
      {confirmDelete && !deleting && (
        <div className="absolute inset-0 z-20 rounded-2xl bg-black/85 flex flex-col items-center justify-center gap-3 p-4"
          onClick={(e) => e.stopPropagation()}>
          <span className="text-[10px] font-mono font-bold tracking-widest text-m-red text-center leading-relaxed">
            DELETE?<br />
            <span className="text-m-text-muted/60 text-[8px]">THIS CANNOT BE UNDONE</span>
          </span>
          <div className="flex gap-2">
            <button
              onClick={(e) => { e.stopPropagation(); setDeleting(true); setConfirmDelete(false); onDelete?.() }}
              className="label-tag px-3 py-1 border border-m-red/60 text-m-red hover:bg-m-red/20 transition-all text-[9px]"
            >
              CONFIRM
            </button>
            <button
              onClick={(e) => { e.stopPropagation(); setConfirmDelete(false) }}
              className="label-tag px-3 py-1 border border-m-border/60 text-m-text-muted hover:text-m-text transition-all text-[9px]"
            >
              CANCEL
            </button>
          </div>
        </div>
      )}

    </div>
  )
}

/* ── Clip matcher (exported for Dashboard reuse) ── */
export function matchRunClips(run: Run, clips: Clip[]): Clip[] {
  const d = new Date(run.date)
  const runTs = [
    d.getFullYear(),
    String(d.getMonth() + 1).padStart(2, '0'),
    String(d.getDate()).padStart(2, '0'),
    '_',
    String(d.getHours()).padStart(2, '0'),
    String(d.getMinutes()).padStart(2, '0'),
    String(d.getSeconds()).padStart(2, '0'),
  ].join('')
  // Primary: match by clip timestamp (from clip filename)
  const directMatch = clips.filter(c => c.run_timestamp === runTs)
  if (directMatch.length > 0) return directMatch
  // Secondary: match by run_folder name (recording start timestamp)
  const folderTs = `run_${runTs}`
  const folderMatch = clips.filter(c => c.run_folder === folderTs)
  if (folderMatch.length > 0) return folderMatch
  // No fallback — clips must match by timestamp or folder name.
  // The 2-hour window caused cross-contamination between back-to-back runs.
  return []
}

/* ── Main Component ── */
export default function RunHistory() {
  const { focusRunId, setFocusRunId } = useStore()
  const [pageRuns, setPageRuns] = useState<Run[]>([])
  const [totalCount, setTotalCount] = useState(0)
  const [maps, setMaps] = useState<string[]>([])
  const [clips, setClips] = useState<Clip[]>([])
  const [outcomeFilter, setOutcomeFilter] = useState<'all' | 'survived' | 'died'>('all')
  const [gradeFilter, setGradeFilter] = useState<string>('')
  const [mapFilter, setMapFilter] = useState('')
  const [rankedFilter, setRankedFilter] = useState(false)
  const [favFilter, setFavFilter] = useState(false)
  const [page, setPage] = useState(0)
  const [expanded, setExpanded] = useState<Set<number>>(new Set())
  const RUNS_PER_PAGE = 21

  const fetchPage = useCallback(() => {
    const params: Record<string, any> = {
      limit: RUNS_PER_PAGE,
      offset: page * RUNS_PER_PAGE,
    }
    if (outcomeFilter === 'survived') params.survived = true
    if (outcomeFilter === 'died') params.survived = false
    if (gradeFilter) params.grade = gradeFilter
    if (mapFilter) params.map_name = mapFilter
    if (rankedFilter) params.is_ranked = true
    if (favFilter) params.is_favorite = true

    getRuns(params).then(result => {
      setPageRuns(result.items)
      setTotalCount(result.total)
      setMaps(result.maps)
    }).catch((e) => console.error('[RunHistory] fetch runs failed:', e))
  }, [page, outcomeFilter, gradeFilter, mapFilter, rankedFilter, favFilter])

  const refreshRuns = useCallback(() => {
    fetchPage()
  }, [fetchPage])

  // Load clips on mount
  useEffect(() => { getClips().then(setClips).catch((e) => console.error('[RunHistory] fetch clips failed:', e)) }, [])

  // Fetch page whenever page/filters change
  useEffect(() => { fetchPage() }, [fetchPage])

  // Handle focusRunId — new runs are always page 0
  useEffect(() => {
    if (focusRunId) {
      setPage(0)
      setExpanded(new Set([focusRunId]))
      setFocusRunId(null)
    }
  }, [focusRunId])

  // Auto-refresh on Phase 1 (new run_id) AND Phase 2 (done count changes)
  const { captureStatus } = useStore()
  const lastRunId = captureStatus?.last_result?.run_id
  const doneCount = captureStatus?.processing_items?.filter(i => i.status === 'done').length ?? 0
  useEffect(() => {
    if (lastRunId || doneCount) {
      fetchPage()
      getClips().then(setClips).catch((e) => console.error('[RunHistory] refresh clips failed:', e))
    }
  }, [lastRunId, doneCount])

  const totalPages = Math.max(1, Math.ceil(totalCount / RUNS_PER_PAGE))

  useEffect(() => { setPage(0) }, [outcomeFilter, gradeFilter, mapFilter, rankedFilter, favFilter])

  function getRunClips(run: Run): Clip[] {
    return matchRunClips(run, clips)
  }

  const handleToggleFavorite = async (e: React.MouseEvent, runId: number) => {
    e.stopPropagation()
    try {
      const result = await toggleFavorite(runId)
      setPageRuns(prev => prev.map(r => r.id === runId ? { ...r, is_favorite: result.is_favorite } : r))
      // If favorite filter is active, removing a favorite should refresh the page
      if (favFilter) fetchPage()
    } catch (err) {
      console.error('Failed to toggle favorite:', err)
    }
  }

  const toggleExpand = (runId: number) => {
    setExpanded(prev => {
      const next = new Set(prev)
      if (next.has(runId)) next.delete(runId)
      else {
        next.add(runId)
        // Mark as viewed — update local state immediately + API
        const run = pageRuns.find(r => r.id === runId)
        if (run && !run.viewed) {
          setPageRuns(p => p.map(r => r.id === runId ? { ...r, viewed: true } : r))
          axios.post(`${apiBase}/api/runs/${runId}/viewed`).catch((e) => console.error('[RunHistory] mark run viewed failed:', e))
        }
      }
      return next
    })
  }

  return (
    <div className="max-w-7xl mx-auto space-y-4">
      <div>
        <p className="label-tag text-m-green">SYSTEM // RUN.LOG</p>
        <h2 className="text-xl font-display font-black tracking-wider text-m-text mt-1">
          RUN LOG
        </h2>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 flex-wrap">
        {/* Outcome filter */}
        <div className="flex gap-[1px] bg-m-border">
          {(['all', 'survived', 'died'] as const).map((f) => (
            <button
              key={f}
              onClick={() => setOutcomeFilter(f)}
              className={`px-3 py-2 text-xs tracking-widest uppercase transition-all ${
                outcomeFilter === f
                  ? 'bg-[#c8ff00]/10 text-[#c8ff00] border-b-2 border-[#c8ff00]'
                  : 'bg-m-card text-m-text-muted hover:text-m-text'
              }`}
            >
              {f === 'all' ? 'ALL' : f === 'survived' ? 'EXFIL' : 'KIA'}
            </button>
          ))}
        </div>

        {/* Grade filter */}
        <div className="flex gap-[1px] bg-m-border">
          <button
            onClick={() => setGradeFilter('')}
            className={`px-2.5 py-2 text-xs tracking-widest uppercase transition-all ${
              !gradeFilter
                ? 'bg-[#c8ff00]/10 text-[#c8ff00] border-b-2 border-[#c8ff00]'
                : 'bg-m-card text-m-text-muted hover:text-m-text'
            }`}
          >
            ALL
          </button>
          {(['S', 'A', 'B', 'C', 'D', 'F'] as const).map((g) => {
            const gc = GRADE_COLORS[g]
            return (
              <button
                key={g}
                onClick={() => setGradeFilter(gradeFilter === g ? '' : g)}
                className={`px-2.5 py-2 text-xs font-display font-black tracking-wider transition-all ${
                  gradeFilter === g
                    ? 'border-b-2'
                    : 'bg-m-card hover:brightness-125'
                }`}
                style={{
                  color: gc.text,
                  borderColor: gradeFilter === g ? gc.text : undefined,
                  backgroundColor: gradeFilter === g ? gc.bg : undefined,
                }}
              >
                {g}
              </button>
            )
          })}
        </div>

        {/* Map filter */}
        {maps.length > 0 && (
          <select
            value={mapFilter}
            onChange={(e) => setMapFilter(e.target.value)}
            className="px-3 py-2 text-xs bg-m-black text-m-text border border-1 border-m-border focus:outline-none appearance-none"
            style={{ colorScheme: 'dark' }}
          >
            <option value="">ALL ZONES</option>
            {maps.map((m) => (
              <option key={m} value={m!}>{m!.toUpperCase()}</option>
            ))}
          </select>
        )}

        {/* Ranked toggle */}
        <button
          onClick={() => setRankedFilter(!rankedFilter)}
          className={`flex items-center justify-center px-2.5 h-[34px] transition-all border ${
            rankedFilter
              ? 'border-[#c8ff00]/40 bg-[#c8ff00]/10'
              : 'border-m-border hover:border-[#c8ff00]/20'
          }`}
          title="Filter ranked"
        >
          <img src={rankedIcon} alt="Ranked" className={`h-3 w-auto ${rankedFilter ? 'opacity-90' : 'opacity-30 hover:opacity-50'}`} />
        </button>

        {/* Favorites toggle — icon only, Marathon green */}
        <button
          onClick={() => setFavFilter(!favFilter)}
          className={`flex items-center justify-center px-2.5 h-[34px] transition-all border ${
            favFilter
              ? 'border-[#c8ff00]/40 text-[#c8ff00] bg-[#c8ff00]/10'
              : 'border-m-border text-m-text-muted hover:text-[#c8ff00]/60'
          }`}
          title="Filter favorites"
        >
          <svg width="14" height="16" viewBox="0 0 14 16">
            {favFilter ? (
              <polygon points="7,0 13.5,4 13.5,12 7,16 0.5,12 0.5,4" fill="currentColor" />
            ) : (
              <polygon points="7,0 13.5,4 13.5,12 7,16 0.5,12 0.5,4" fill="none" stroke="currentColor" strokeWidth="1.2" />
            )}
          </svg>
        </button>

        <span className="label-tag text-m-text-muted ml-auto">
          {totalCount} TRANSMISSION{totalCount !== 1 ? 'S' : ''}
        </span>
      </div>

      {/* Column headers */}
      <div className="grid grid-cols-[36px_6px_auto_1fr_36px_36px_36px_36px_75px_50px_18px] items-center gap-x-3 px-4 py-2 border-b border-m-border">
        <span className="label-tag text-m-text-muted text-center">GRADE</span>
        <span />
        <span className="label-tag text-m-text-muted">SHELL</span>
        <span className="label-tag text-m-text-muted">LOCATION</span>
        <span className="label-tag text-m-text-muted text-right">PVE</span>
        <span className="label-tag text-m-text-muted text-right">RNR</span>
        <span className="label-tag text-m-text-muted text-right">DTH</span>
        <span className="label-tag text-m-text-muted text-right">RVV</span>
        <span className="label-tag text-m-text-muted text-right">LOOT</span>
        <span className="label-tag text-m-text-muted text-right">TIME</span>
        <span />
      </div>

      {/* Run List */}
      {totalCount === 0 ? (
        <div className="border border-1 border-m-border bg-m-card p-10 text-center">
          <p className="text-xs text-m-text-muted tracking-wider">
            {favFilter ? 'NO FAVORITED RUNS' : 'NO MATCHING RUNS'}
          </p>
        </div>
      ) : (
        <div className="border border-1 border-m-green/20 divide-y divide-m-border">
          {pageRuns.map((run) => (
            <RunRow
              key={run.id}
              run={run}
              isExpanded={expanded.has(run.id)}
              onToggle={() => toggleExpand(run.id)}
              onToggleFavorite={(e) => handleToggleFavorite(e, run.id)}
              onUpdate={refreshRuns}
              clips={getRunClips(run)}
              onClipsRefresh={() => { fetchPage(); getClips().then(setClips).catch((e) => console.error('[RunHistory] refresh clips failed:', e)) }}
            />
          ))}
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-3 pt-2">
          <button
            onClick={() => setPage(p => Math.max(0, p - 1))}
            disabled={page === 0}
            className="label-tag px-3 py-1.5 border border-m-border text-m-text-muted hover:text-m-text hover:border-m-green/40 disabled:opacity-30 disabled:cursor-not-allowed transition-all"
          >
            PREV
          </button>
          <span className="text-[9px] font-mono text-m-text-muted tracking-wider">
            {page + 1} // {totalPages}
          </span>
          <button
            onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))}
            disabled={page === totalPages - 1}
            className="label-tag px-3 py-1.5 border border-m-border text-m-text-muted hover:text-m-text hover:border-m-green/40 disabled:opacity-30 disabled:cursor-not-allowed transition-all"
          >
            NEXT
          </button>
        </div>
      )}
    </div>
  )
}

/* ── Run Row (exported for use in Dashboard/Terminal) ── */
export function RunRow({ run, isExpanded, onToggle, onToggleFavorite, onUpdate, clips, onClipsRefresh: _onClipsRefresh }: {
  run: Run
  isExpanded: boolean
  onToggle: () => void
  onToggleFavorite: (e: React.MouseEvent) => void
  onUpdate: () => void
  clips: Clip[]
  onClipsRefresh?: () => void
}) {
  const [highlightsOpen, setHighlightsOpen] = useState(false)
  const [debriefOpen, setDebriefOpen] = useState(false)
  const [playingClip, setPlayingClip] = useState<string | null>(null)
  const [folderSize, setFolderSize] = useState<number | null>(null)
  const [folderSizeTick, setFolderSizeTick] = useState(0)
  // Local clips override — when user creates/deletes clips, fetch fresh from API
  const [localClips, setLocalClips] = useState<Clip[] | null>(null)
  const activeClips = localClips ?? clips

  const refreshLocalClips = useCallback(() => {
    getClips().then(allClips => {
      const matched = matchRunClips(run, allClips)
      setLocalClips(matched)
    }).catch((e) => console.error('[RunHistory] refresh local clips failed:', e))
  }, [run])

  const refreshFolderSize = useCallback(() => {
    if (activeClips[0]?.run_folder) {
      axios.get(`${apiBase}/api/capture/folder-size/${activeClips[0].run_folder}`)
        .then(({ data }) => setFolderSize(data.size_mb))
        .catch(() => setFolderSize(null))
    }
  }, [activeClips])

  // Refetch folder size on expand and after deletions
  useEffect(() => {
    if (isExpanded) refreshFolderSize()
  }, [isExpanded, folderSizeTick, refreshFolderSize])

  const gc = run.grade ? (GRADE_COLORS[run.grade] || GRADE_COLORS.D) : null

  return (
    <div>
      {/* Collapsed row */}
      <div
        onClick={onToggle}
        className={`relative grid grid-cols-[36px_6px_auto_1fr_36px_36px_36px_36px_75px_50px_18px] items-center gap-x-3 px-4 py-3 transition-colors cursor-pointer ${
          !run.viewed
            ? 'bg-m-cyan/[0.04] border-l-2 border-l-m-cyan/40 hover:bg-m-cyan/[0.08]'
            : 'bg-m-card hover:bg-m-surface'
        }`}
      >
        {/* Unviewed grid overlay */}
        {!run.viewed && (
          <div className="absolute inset-0 pointer-events-none opacity-[0.03]" style={{
            backgroundImage: 'linear-gradient(to right, rgba(0,221,255,0.4) 1px, transparent 1px), linear-gradient(to bottom, rgba(0,221,255,0.4) 1px, transparent 1px)',
            backgroundSize: '20px 20px',
          }} />
        )}
        {/* Grade badge */}
        {gc ? (
          <span
            className="text-sm font-display font-black text-center px-1 py-0.5 border rounded"
            style={{ color: gc.text, borderColor: gc.border, backgroundColor: gc.bg }}
          >
            {run.grade}
          </span>
        ) : (
          <span className="text-sm font-display font-black text-center text-m-text-muted/30">--</span>
        )}

        {/* Status bar */}
        <div className={`w-1.5 h-8 ${run.survived ? 'bg-m-green' : 'bg-m-red'}`} />

        {/* Shell */}
        <span className="text-xs text-m-cyan tracking-wider uppercase truncate">
          {run.shell_name ?? '—'}
        </span>

        {/* Map + Spawn */}
        <span className="text-xs text-m-text tracking-wider uppercase truncate flex items-center gap-1.5">
          {run.is_ranked && (
            <img src={rankedIcon} alt="Ranked" className="h-3 w-auto opacity-80" />
          )}
          {run.map_name ?? 'UNKNOWN'}
          {run.spawn_location && (
            <span className="text-m-text-muted"> — {run.spawn_location}</span>
          )}
        </span>

        <span className={`text-xs font-mono text-right ${run.combatant_eliminations ? 'text-white' : 'text-m-text-muted'}`}>
          {run.combatant_eliminations || 0}<span className="text-m-text-muted text-2xs"> PVE</span>
        </span>
        <span className={`text-xs font-mono text-right ${run.runner_eliminations ? 'text-m-cyan' : 'text-m-text-muted'}`}>
          {run.runner_eliminations || 0}<span className="text-m-text-muted text-2xs"> RNR</span>
        </span>
        <span className={`text-xs font-mono text-right ${run.deaths ? 'text-m-red' : 'text-m-text-muted'}`}>
          {run.deaths}<span className="text-m-text-muted text-2xs"> DTH</span>
        </span>
        <span className={`text-xs font-mono text-right ${run.crew_revives ? 'text-m-green' : 'text-m-text-muted'}`}>
          {run.crew_revives || 0}<span className="text-m-text-muted text-2xs"> RVV</span>
        </span>
        <span className={`text-xs font-mono text-right ${
          run.loot_value_total >= 0 ? 'text-m-yellow' : 'text-m-red'
        }`}>
          ${run.loot_value_total.toLocaleString()}
        </span>
        <span className="text-xs font-mono text-m-text-muted text-right">
          {run.duration_seconds ? formatTime(run.duration_seconds) : '—'}
        </span>

        {/* Favorite hexagon */}
        <HexFavorite filled={!!run.is_favorite} onClick={onToggleFavorite} />
      </div>

      {/* Expanded content */}
      {isExpanded && (
        <div className="px-6 py-4 bg-m-surface border-t border-m-border space-y-3">
          {/* New compact detail — no repeated data */}
          <div className="space-y-2">
            {/* DATE + CHANGE SHELL */}
            <div className="flex items-center gap-2">
              <span className="text-[9px] font-mono text-m-text-muted tracking-wider w-20">DATE</span>
              <span className="text-[10px] font-mono text-m-text-muted">
                {format(new Date(run.date), 'yyyy.MM.dd HH:mm')}
              </span>
              <ShellPicker run={run} onUpdate={onUpdate} />
            </div>

            {/* SQUAD */}
            <div className="flex items-center gap-2">
              <span className="text-[9px] font-mono text-m-text-muted tracking-wider w-20">SQUAD</span>
              <span className="text-[10px] font-mono text-m-text">
                {run.squad_members && run.squad_members.length > 0
                  ? run.squad_members.join('  ·  ')
                  : 'Solo'}
              </span>
            </div>

            {/* WEAPONS */}
            <div className="flex items-center gap-2">
              <span className="text-[9px] font-mono text-m-text-muted tracking-wider w-20">PRIMARY</span>
              <span className="text-[10px] font-mono text-m-text">{run.primary_weapon ?? '—'}</span>
              <span className="text-[9px] font-mono text-m-text-muted tracking-wider ml-6">SECONDARY</span>
              <span className="text-[10px] font-mono text-m-text">{run.secondary_weapon ?? '—'}</span>
            </div>

            {/* INVENTORY — survived: start → end (+delta), eliminated: just lost value */}
            <div className="flex items-center gap-2">
              <span className="text-[9px] font-mono text-m-text-muted tracking-wider w-20">INVENTORY</span>
              {run.starting_loadout_value != null ? (() => {
                const delta = run.loot_value_total - run.starting_loadout_value
                return (
                  <span className="text-[10px] font-mono">
                    <span className="text-m-text-muted">${run.starting_loadout_value.toLocaleString()}</span>
                    <span className="text-m-text-muted"> → </span>
                    <span className={run.loot_value_total >= 0 ? 'text-m-yellow' : 'text-m-red'}>
                      ${run.loot_value_total.toLocaleString()}
                    </span>
                    {run.survived !== false && (
                      <span className={`ml-2 ${delta >= 0 ? 'text-m-green' : 'text-m-red'}`}>
                        ({delta >= 0 ? '+' : ''}{delta.toLocaleString()})
                      </span>
                    )}
                  </span>
                )
              })() : (
                <span className={`text-[10px] font-mono ${run.loot_value_total >= 0 ? 'text-m-yellow' : 'text-m-red'}`}>
                  ${run.loot_value_total.toLocaleString()}
                </span>
              )}
            </div>

            {/* KILLED BY or EXTRACTED//CLEAN */}
            <div className="flex items-center gap-2 flex-wrap">
              {run.survived ? (
                <>
                  <span className="text-[9px] font-mono text-m-green tracking-wider">EXTRACTED//CLEAN</span>
                </>
              ) : (
                <>
                  <span className="text-[9px] font-mono text-m-text-muted tracking-wider w-20">KILLED BY</span>
                  {run.damage_contributors && run.damage_contributors.length > 0 ? (
                    <span className="text-[10px] font-mono text-m-red">
                      {run.damage_contributors.map((c, i) => (
                        <span key={i}>
                          {i > 0 && <span className="text-m-text-muted/50"> + </span>}
                          {c.finished && run.killed_by ? run.killed_by : c.name} <span className="text-m-text-muted">{c.damage}</span>
                        </span>
                      ))}
                    </span>
                  ) : (
                    <span className="text-[10px] font-mono text-m-red">
                      {run.killed_by
                        ? <>{run.killed_by}{run.killed_by_damage ? <> <span className="text-m-text-muted"> {run.killed_by_damage}</span></> : ''}</>
                        : 'Unknown'}
                    </span>
                  )}
                </>
              )}
            </div>
          </div>

          {/* ▷ HIGHLIGHTS */}
          <div className="border-t border-m-border pt-3">
            <div className="flex items-center justify-between">
              <button
                onClick={(e) => { e.stopPropagation(); setHighlightsOpen(!highlightsOpen) }}
                className="label-tag text-m-text-muted hover:text-m-text transition-colors flex items-center gap-2"
              >
                <span className={`text-[10px] transition-transform ${highlightsOpen ? 'rotate-90' : ''}`}>▷</span>
                HIGHLIGHTS
                {(activeClips.length > 0 || run.recording_path) && (() => {
                  const total = activeClips.length + (run.recording_path ? 1 : 0)
                  return <span className="text-m-cyan text-[9px]">{total} CLIP{total !== 1 ? 'S' : ''}</span>
                })()}
              </button>
              {activeClips[0]?.run_folder && (
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    axios.post(`${apiBase}/api/capture/open-folder`, { folder: activeClips[0].run_folder })
                  }}
                  className="label-tag px-2 py-0.5 border border-m-border text-m-text-muted hover:text-m-green hover:border-m-green/40 transition-all flex items-center gap-1.5"
                  title="Open clips folder"
                >
                  <svg width="10" height="10" viewBox="0 0 16 16" fill="currentColor">
                    <path d="M1 3.5A1.5 1.5 0 012.5 2h3.879a1.5 1.5 0 011.06.44l1.122 1.12A1.5 1.5 0 009.62 4H13.5A1.5 1.5 0 0115 5.5v7a1.5 1.5 0 01-1.5 1.5h-11A1.5 1.5 0 011 12.5v-9z"/>
                  </svg>
                  OPEN
                  {folderSize != null && (
                    <span className="text-m-text-muted/40">{folderSize >= 1000 ? `${(folderSize / 1000).toFixed(1)}GB` : `${folderSize}MB`}</span>
                  )}
                </button>
              )}
            </div>
            {highlightsOpen && (
              <div className="mt-3">
                {activeClips.length === 0 && !run.recording_path ? (
                  <p className="text-xs text-m-text-muted/50">No clips available. Phase 2 may still be processing.</p>
                ) : (
                  <>
                    <div className="grid grid-cols-3 gap-3">
                      {/* Full recording pill */}
                      {run.recording_path && (() => {
                        const relPath = (run.recording_path!.split(/[/\\]clips[/\\]/).pop() || '').replace(/\\/g, '/')
                        const thumbPath = relPath.replace('.mp4', '_thumb.jpg')
                        const spritePath = relPath.replace('.mp4', '_sprite.jpg')
                        // Estimate sprite grid from duration: 3fps, min 30, cap 300
                        const estFrames = run.duration_seconds ? Math.min(300, Math.max(30, Math.floor(run.duration_seconds * 3))) : null
                        const estCols = estFrames ? Math.min(10, estFrames) : null
                        const estRows = estFrames && estCols ? Math.ceil(estFrames / estCols) : null
                        return (
                          <ClipPill
                            key="full-run"
                            label="FULL RUN"
                            thumbnail={getClipUrl(thumbPath)}
                            sprite={getClipUrl(spritePath)}
                            spriteCols={estCols}
                            spriteRows={estRows}
                            spriteFrames={estFrames}
                            isActive={playingClip === relPath}
                            onPlay={(e) => { e.stopPropagation(); setPlayingClip(relPath) }}
                            onDelete={async () => {
                              try {
                                await deleteKeptRecording(run.id)
                                if (playingClip === relPath) setPlayingClip(null)
                                onUpdate()
                                refreshLocalClips()
                                setFolderSizeTick(t => t + 1)
                              } catch (e) { console.error('Failed to delete recording:', e) }
                            }}
                          />
                        )
                      })()}
                      {activeClips.map((clip) => (
                        <ClipPill
                          key={clip.filename}
                          label={clip.type.toUpperCase().replace('_', ' ')}
                          thumbnail={clip.thumbnail ? getClipUrl(clip.thumbnail) : null}
                          sprite={clip.sprite ? getClipUrl(clip.sprite) : null}
                          spriteCols={clip.sprite_cols}
                          spriteRows={clip.sprite_rows}
                          spriteFrames={clip.sprite_frames}
                          isActive={playingClip === clip.filename}
                          onPlay={(e) => { e.stopPropagation(); setPlayingClip(clip.filename) }}
                          onDelete={async () => {
                            try {
                              await deleteClip(clip.filename)
                              if (playingClip === clip.filename) setPlayingClip(null)
                              refreshLocalClips()
                              setFolderSizeTick(t => t + 1)
                            } catch (e) { console.error('Failed to delete clip:', e) }
                          }}
                        />
                      ))}
                    </div>
                    {/* Inline video player with timeline + clip editor */}
                    {playingClip && (
                      <ClipTimeline
                        src={getClipUrl(playingClip)}
                        clipPath={playingClip}
                        label={playingClip.split('/').pop()?.replace('.mp4', '').replace(/^clip_\d+_\d+_/, '').replace(/_\d+$/, '').replace(/_/g, ' ').toUpperCase() || 'PLAYING'}
                        onClose={() => setPlayingClip(null)}
                        onPlayClip={(newClipPath) => setPlayingClip(newClipPath)}
                        onClipCreated={() => {
                          refreshLocalClips()
                          setTimeout(() => refreshLocalClips(), 1500)
                          setFolderSizeTick(t => t + 1)
                        }}
                      />
                    )}
                  </>
                )}
              </div>
            )}
          </div>

          {/* ▷ DEBRIEF */}
          <div className="border-t border-m-border pt-3">
            <button
              onClick={(e) => { e.stopPropagation(); setDebriefOpen(!debriefOpen) }}
              className="label-tag text-m-text-muted hover:text-m-text transition-colors flex items-center gap-2"
            >
              <span className={`text-[10px] transition-transform ${debriefOpen ? 'rotate-90' : ''}`}>▷</span>
              DEBRIEF
              {run.grade && (
                <span style={{ color: gc?.text }} className="text-[9px] font-display font-black">{run.grade}</span>
              )}
            </button>
            {debriefOpen && (
              <div className="mt-3">
                {run.summary ? (
                  <p className="text-sm text-m-text leading-relaxed whitespace-pre-line pl-4 border-l border-m-border">
                    {run.summary}
                  </p>
                ) : (
                  <p className="text-xs text-m-text-muted/50">No debrief available. Phase 2 may still be processing.</p>
                )}
              </div>
            )}
          </div>
        </div>
      )}

    </div>
  )
}
