// Electron preload bridge types

export interface ScreenshotEvent {
  type: 'run' | 'spawn'
  data: Record<string, unknown>
  timestamp: number
  auto?: boolean
}

export interface AutoCaptureEvent {
  type: string
  timestamp: number
  state?: string
  survived?: boolean
  [key: string]: unknown
}

export interface OverlaySettings {
  enabled: boolean
  corner: string
  customX?: number
  customY?: number
  opacity?: number
  size?: string
  closeWhenDone?: boolean
}

interface RunlogBridge {
  onScreenshotParsed: (callback: (event: ScreenshotEvent) => void) => () => void
  onAutoCaptureEvent: (callback: (event: AutoCaptureEvent) => void) => () => void
  onRecordingStatus: (callback: (data: { status: string; message: string }) => void) => () => void
  getApiBaseUrl: () => string
  windowMinimize: () => void
  windowMaximize: () => void
  windowClose: () => void
  updateOverlay: (state: string, detail: string) => void
  notifyOverlay: (message: string, duration: number) => void
  toggleOverlay: (enabled: boolean) => void
  setOverlayCorner: (corner: string) => void
  nudgeOverlay: (direction: string) => void
  getOverlaySettings: () => Promise<OverlaySettings>
  setOverlayOpacity: (opacity: number) => void
  setOverlaySize: (size: string) => void
  setOverlayPosition: (xPct: number, yPct: number) => void
  previewOverlay: () => void
  openUrl: (url: string) => void
}

declare global {
  interface Window {
    runlog?: RunlogBridge
  }
}

export const isElectron = !!window.runlog

export function getApiBaseUrl(): string {
  return window.runlog?.getApiBaseUrl?.() ?? ''
}

export function onScreenshotParsed(callback: (event: ScreenshotEvent) => void) {
  if (window.runlog) {
    return window.runlog.onScreenshotParsed(callback)
  }
  return () => {}
}

export function onAutoCaptureEvent(callback: (event: AutoCaptureEvent) => void) {
  if (window.runlog) {
    return window.runlog.onAutoCaptureEvent(callback)
  }
  return () => {}
}
