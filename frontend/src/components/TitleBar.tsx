export default function TitleBar() {
  const minimize = () => (window as any).runlog?.windowMinimize?.()
  const maximize = () => (window as any).runlog?.windowMaximize?.()
  const close = () => (window as any).runlog?.windowClose?.()

  return (
    <div className="h-8 bg-m-black flex items-center select-none shrink-0" style={{ WebkitAppRegion: 'drag' } as any}>
      {/* App title */}
      <span className="text-[10px] tracking-[0.15em] text-m-text-muted/50 font-mono ml-3">
        MARATHON RUNLOG
      </span>

      {/* Spacer — draggable area */}
      <div className="flex-1" />

      {/* Window controls */}
      <div className="flex h-full" style={{ WebkitAppRegion: 'no-drag' } as any}>
        <button
          onClick={minimize}
          className="w-11 h-full flex items-center justify-center text-m-text-muted hover:bg-m-surface hover:text-m-text transition-colors"
        >
          <svg width="10" height="1" viewBox="0 0 10 1" fill="currentColor">
            <rect width="10" height="1" />
          </svg>
        </button>
        <button
          onClick={maximize}
          className="w-11 h-full flex items-center justify-center text-m-text-muted hover:bg-m-surface hover:text-m-text transition-colors"
        >
          <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1">
            <rect x="0.5" y="0.5" width="9" height="9" />
          </svg>
        </button>
        <button
          onClick={close}
          className="w-11 h-full flex items-center justify-center text-m-text-muted hover:bg-red-600 hover:text-white transition-colors"
        >
          <svg width="10" height="10" viewBox="0 0 10 10" stroke="currentColor" strokeWidth="1.2">
            <line x1="0" y1="0" x2="10" y2="10" />
            <line x1="10" y1="0" x2="0" y2="10" />
          </svg>
        </button>
      </div>
    </div>
  )
}
