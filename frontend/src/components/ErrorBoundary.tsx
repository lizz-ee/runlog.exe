import { Component, type ReactNode } from 'react'

interface Props {
  children: ReactNode
}

interface State {
  hasError: boolean
  error: Error | null
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('[ErrorBoundary]', error, info.componentStack)
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex items-center justify-center h-full p-8">
          <div className="text-center max-w-md">
            <p className="text-m-red font-mono text-sm tracking-wider mb-2">// RENDER.ERROR</p>
            <p className="text-m-text-muted text-xs font-mono mb-4">
              {this.state.error?.message || 'An unexpected error occurred'}
            </p>
            <button
              onClick={() => this.setState({ hasError: false, error: null })}
              className="text-xs font-mono tracking-wider text-m-green hover:text-m-green/80 border border-m-green/30 px-3 py-1"
            >
              RETRY
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}
