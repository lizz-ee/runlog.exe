import { useEffect, useState } from 'react'
import { getSettings, setApiKey, testApiKey, removeApiKey } from '../lib/api'

type KeyStatus = 'idle' | 'testing' | 'valid' | 'invalid' | 'saving' | 'saved' | 'error'

export default function Settings() {
  const [keyInput, setKeyInput] = useState('')
  const [status, setStatus] = useState<KeyStatus>('idle')
  const [statusMsg, setStatusMsg] = useState('')
  const [hasKey, setHasKey] = useState(false)
  const [maskedKey, setMaskedKey] = useState('')
  const [keySource, setKeySource] = useState('')

  useEffect(() => {
    getSettings().then((s) => {
      setHasKey(s.has_api_key)
      setMaskedKey(s.api_key_masked)
      setKeySource(s.api_key_source)
    }).catch(console.error)
  }, [])

  async function handleTest() {
    if (!keyInput.trim()) return
    setStatus('testing')
    setStatusMsg('VALIDATING KEY...')
    try {
      await testApiKey(keyInput.trim())
      setStatus('valid')
      setStatusMsg('KEY VALID — CONNECTION OK')
    } catch (err: any) {
      setStatus('invalid')
      setStatusMsg(err.response?.data?.detail || 'INVALID KEY')
    }
  }

  async function handleSave() {
    if (!keyInput.trim()) return
    setStatus('saving')
    setStatusMsg('SAVING...')
    try {
      await setApiKey(keyInput.trim())
      setStatus('saved')
      setStatusMsg('KEY SAVED')
      setKeyInput('')
      // Refresh display
      const s = await getSettings()
      setHasKey(s.has_api_key)
      setMaskedKey(s.api_key_masked)
      setKeySource(s.api_key_source)
    } catch (err: any) {
      setStatus('error')
      setStatusMsg(err.response?.data?.detail || 'SAVE FAILED')
    }
  }

  async function handleRemove() {
    try {
      await removeApiKey()
      setHasKey(false)
      setMaskedKey('')
      setKeySource('none')
      setStatus('idle')
      setStatusMsg('')
    } catch (err) {
      console.error('Failed to remove key:', err)
    }
  }

  async function handleTestAndSave() {
    if (!keyInput.trim()) return
    setStatus('testing')
    setStatusMsg('VALIDATING KEY...')
    try {
      await testApiKey(keyInput.trim())
      setStatus('saving')
      setStatusMsg('KEY VALID — SAVING...')
      await setApiKey(keyInput.trim())
      setStatus('saved')
      setStatusMsg('KEY SAVED — SYSTEM READY')
      setKeyInput('')
      const s = await getSettings()
      setHasKey(s.has_api_key)
      setMaskedKey(s.api_key_masked)
      setKeySource(s.api_key_source)
    } catch (err: any) {
      setStatus('invalid')
      setStatusMsg(err.response?.data?.detail || 'INVALID KEY')
    }
  }

  const statusColor =
    status === 'valid' || status === 'saved' ? 'text-m-green' :
    status === 'invalid' || status === 'error' ? 'text-m-red' :
    status === 'testing' || status === 'saving' ? 'text-m-yellow' :
    'text-m-text-muted'

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <div>
        <p className="label-tag text-m-green">SYSTEM // CONFIG</p>
        <h2 className="text-xl font-display font-black tracking-wider text-m-text mt-1">
          SYS.CONFIG
        </h2>
      </div>

      {/* API Key Section */}
      <div className="border border-1 border-m-border bg-m-card">
        <div className="px-5 py-4 border-b border-m-border">
          <p className="label-tag text-m-green mb-1">ANTHROPIC API KEY</p>
          <p className="text-xs text-m-text-muted">
            Required for AI-powered stat extraction and run analysis.
            Get your key from{' '}
            <span className="text-m-cyan">console.anthropic.com</span>
          </p>
        </div>

        <div className="px-5 py-4 space-y-4">
          {/* Current status */}
          <div className="flex items-center justify-between">
            <span className="label-tag text-m-text-muted">STATUS</span>
            {hasKey ? (
              <div className="flex items-center gap-2">
                <span className="w-1.5 h-1.5 bg-m-green rounded-full" />
                <span className="text-2xs font-mono text-m-green">CONFIGURED</span>
              </div>
            ) : (
              <div className="flex items-center gap-2">
                <span className="w-1.5 h-1.5 bg-m-red rounded-full" />
                <span className="text-2xs font-mono text-m-red">NOT SET</span>
              </div>
            )}
          </div>

          {hasKey && (
            <div className="flex items-center justify-between">
              <span className="label-tag text-m-text-muted">ACTIVE KEY</span>
              <span className="text-2xs font-mono text-m-text-muted">{maskedKey}</span>
            </div>
          )}

          {hasKey && keySource && (
            <div className="flex items-center justify-between">
              <span className="label-tag text-m-text-muted">SOURCE</span>
              <span className="text-2xs font-mono text-m-text-muted uppercase">{keySource}</span>
            </div>
          )}

          {/* Input */}
          <div className="space-y-2">
            <label className="label-tag text-m-text-muted">
              {hasKey ? 'REPLACE KEY' : 'ENTER KEY'}
            </label>
            <input
              type="password"
              value={keyInput}
              onChange={(e) => {
                setKeyInput(e.target.value)
                setStatus('idle')
                setStatusMsg('')
              }}
              placeholder="sk-ant-api03-..."
              className="w-full px-3 py-2 text-xs font-mono bg-m-black text-m-text border border-1 border-m-border focus:border-m-green focus:outline-none placeholder:text-m-text-muted/30"
            />
          </div>

          {/* Status message */}
          {statusMsg && (
            <div className={`text-2xs font-mono tracking-wider ${statusColor}`}>
              {statusMsg}
            </div>
          )}

          {/* Actions */}
          <div className="flex gap-2">
            <button
              onClick={handleTestAndSave}
              disabled={!keyInput.trim() || status === 'testing' || status === 'saving'}
              className="px-4 py-2 text-xs tracking-widest uppercase bg-m-green/10 text-m-green border border-1 border-m-green/30 hover:bg-m-green/20 transition-all disabled:opacity-30 disabled:cursor-not-allowed"
            >
              {status === 'testing' ? 'TESTING...' : status === 'saving' ? 'SAVING...' : 'TEST & SAVE'}
            </button>
            <button
              onClick={handleTest}
              disabled={!keyInput.trim() || status === 'testing'}
              className="px-4 py-2 text-xs tracking-widest uppercase bg-m-surface text-m-text-muted border border-1 border-m-border hover:text-m-text transition-all disabled:opacity-30 disabled:cursor-not-allowed"
            >
              TEST ONLY
            </button>
            {hasKey && (
              <button
                onClick={handleRemove}
                className="px-4 py-2 text-xs tracking-widest uppercase text-m-red/40 hover:text-m-red transition-colors ml-auto"
              >
                REMOVE KEY
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Info */}
      <div className="border border-1 border-m-border bg-m-card px-5 py-4">
        <p className="label-tag text-m-text-muted mb-2">SETUP GUIDE</p>
        <ol className="space-y-2 text-xs text-m-text-muted">
          <li className="flex gap-2">
            <span className="text-m-green font-mono">01</span>
            <span>Go to <span className="text-m-cyan">console.anthropic.com</span> and create an account</span>
          </li>
          <li className="flex gap-2">
            <span className="text-m-green font-mono">02</span>
            <span>Navigate to API Keys and generate a new key</span>
          </li>
          <li className="flex gap-2">
            <span className="text-m-green font-mono">03</span>
            <span>Paste the key above and click TEST & SAVE</span>
          </li>
          <li className="flex gap-2">
            <span className="text-m-green font-mono">04</span>
            <span>Your key is stored locally and never sent anywhere except Anthropic's API</span>
          </li>
        </ol>
      </div>

      {/* Version info */}
      <div className="flex justify-between text-2xs font-mono text-m-text-muted/40">
        <span>runlog.exe v1.0.0</span>
        <span>LOCAL-FIRST // NO CLOUD // NO TELEMETRY</span>
      </div>
    </div>
  )
}
