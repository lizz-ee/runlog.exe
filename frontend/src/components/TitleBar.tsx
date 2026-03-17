export default function TitleBar() {
  const minimize = () => (window as any).runlog?.windowMinimize?.()
  const maximize = () => (window as any).runlog?.windowMaximize?.()
  const close = () => (window as any).runlog?.windowClose?.()

  return (
    <div className="h-6 bg-transparent flex items-center shrink-0 relative" style={{ WebkitAppRegion: 'drag' } as any}>
      {/* Window controls — floating top-right */}
      <div className="absolute right-0 top-0 flex" style={{ WebkitAppRegion: 'no-drag' } as any}>
        <button
          onClick={minimize}
          className="w-8 h-6 flex items-center justify-center text-m-text-muted/30 hover:bg-m-surface hover:text-m-text transition-colors"
        >
          <svg width="8" height="1" viewBox="0 0 8 1" fill="currentColor">
            <rect width="8" height="1" />
          </svg>
        </button>
        <button
          onClick={maximize}
          className="w-8 h-6 flex items-center justify-center text-m-text-muted/30 hover:bg-m-surface hover:text-m-text transition-colors"
        >
          <svg width="8" height="8" viewBox="0 0 8 8" fill="none" stroke="currentColor" strokeWidth="1">
            <rect x="0.5" y="0.5" width="7" height="7" />
          </svg>
        </button>
        <button
          onClick={close}
          className="w-8 h-6 flex items-center justify-center text-m-text-muted/30 hover:bg-red-600/80 hover:text-white transition-colors"
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
