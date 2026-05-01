import { useEffect } from 'react'
import { useStore } from '../lib/store'

export default function Toasts() {
  const { toasts, removeToast } = useStore()

  useEffect(() => {
    if (!toasts.length) return
    const timer = setTimeout(() => removeToast(toasts[0].id), 5000)
    return () => clearTimeout(timer)
  }, [toasts, removeToast])

  return (
    <div className="fixed bottom-4 right-4 z-50 space-y-2 max-w-sm">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          onClick={() => removeToast(toast.id)}
          className={`px-4 py-3 border border-1 cursor-pointer bg-m-card transition-transform duration-150 ease-out hover:translate-x-[-2px] ${
            toast.type === 'success'
              ? 'border-m-green/30 text-m-green'
              : toast.type === 'error'
              ? 'border-m-red/30 text-m-red'
              : 'border-m-cyan/30 text-m-cyan'
          }`}
        >
          <p className="text-xs font-bold tracking-wider">{toast.title}</p>
          <p className="label-tag mt-0.5 opacity-70">{toast.body}</p>
        </div>
      ))}
    </div>
  )
}
