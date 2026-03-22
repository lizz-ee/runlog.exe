/** Format seconds as M:SS */
export function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

/** Format seconds as Hh Mm or Mm Ss */
export function formatDuration(seconds: number): string {
  if (seconds >= 3600) {
    const h = Math.floor(seconds / 3600)
    const m = Math.floor((seconds % 3600) / 60)
    return `${h}h ${m}m`
  }
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}m ${s}s`
}
