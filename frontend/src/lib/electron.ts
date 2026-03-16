// Electron preload bridge types

export interface ScreenshotEvent {
  type: 'run' | 'spawn'
  data: any
  timestamp: number
  auto?: boolean
}

export interface AutoCaptureEvent {
  type: string
  timestamp: number
  state?: string
  survived?: boolean
  [key: string]: any
}

interface RunlogBridge {
  onScreenshotParsed: (callback: (event: ScreenshotEvent) => void) => void
  onAutoCaptureEvent: (callback: (event: AutoCaptureEvent) => void) => void
  captureRun: () => Promise<void>
  captureSpawn: () => Promise<void>
  getApiBaseUrl: () => string
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
    window.runlog.onScreenshotParsed(callback)
  }
}

export function onAutoCaptureEvent(callback: (event: AutoCaptureEvent) => void) {
  if (window.runlog) {
    window.runlog.onAutoCaptureEvent(callback)
  }
}

export function captureRun() {
  return window.runlog?.captureRun()
}

export function captureSpawn() {
  return window.runlog?.captureSpawn()
}
