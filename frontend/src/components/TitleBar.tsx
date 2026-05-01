import type { CSSProperties } from 'react'

type DraggableRegionStyle = CSSProperties & {
  WebkitAppRegion?: 'drag' | 'no-drag'
}

const dragStyle: DraggableRegionStyle = { WebkitAppRegion: 'drag' }
const noDragStyle: DraggableRegionStyle = { WebkitAppRegion: 'no-drag' }

export default function TitleBar() {
  const minimize = () => window.runlog?.windowMinimize?.()
  const maximize = () => window.runlog?.windowMaximize?.()
  const close = () => window.runlog?.windowClose?.()

  return (
    <div className="h-8 bg-transparent flex items-center shrink-0 relative" style={dragStyle}>
      {/* Window controls — floating top-right */}
      <div className="absolute right-0 top-0 flex" style={noDragStyle}>
        <button
          onClick={minimize}
          aria-label="Minimize window"
          className="w-8 h-8 flex items-center justify-center text-m-text-muted/30 hover:bg-m-surface hover:text-m-text transition-colors"
        >
          <svg width="8" height="1" viewBox="0 0 8 1" fill="currentColor">
            <rect width="8" height="1" />
          </svg>
        </button>
        <button
          onClick={maximize}
          aria-label="Maximize window"
          className="w-8 h-8 flex items-center justify-center text-m-text-muted/30 hover:bg-m-surface hover:text-m-text transition-colors"
        >
          <svg width="8" height="8" viewBox="0 0 8 8" fill="none" stroke="currentColor" strokeWidth="1">
            <rect x="0.5" y="0.5" width="7" height="7" />
          </svg>
        </button>
        <button
          onClick={close}
          aria-label="Close window"
          className="w-8 h-8 flex items-center justify-center text-m-text-muted/30 hover:bg-red-600/80 hover:text-white transition-colors"
        >
          <svg width="8" height="8" viewBox="0 0 8 8" stroke="currentColor" strokeWidth="1.2">
            <line x1="0" y1="0" x2="8" y2="8" />
            <line x1="8" y1="0" x2="0" y2="8" />
          </svg>
        </button>
      </div>
    </div>
  )
}
