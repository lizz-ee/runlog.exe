// Electron preload bridge types

export interface ScreenshotEvent {
  type: 'run' | 'spawn'
  data: any
  timestamp: number
}

interface RunlogBridge {
  onScreenshotParsed: (callback: (event: ScreenshotEvent) => void) => void
  captureRun: () => Promise<void>
  captureSpawn: () => Promise<void>
}

declare global {
  interface Window {
    runlog?: RunlogBridge
  }
}

export const isElectron = !!window.runlog

export function onScreenshotParsed(callback: (event: ScreenshotEvent) => void) {
  if (window.runlog) {
    window.runlog.onScreenshotParsed(callback)
  }
}

export function captureRun() {
  return window.runlog?.captureRun()
}

export function captureSpawn() {
  return window.runlog?.captureSpawn()
}
