import { useState } from 'react'
import { useStore } from '../store'

const RISK_CONFIG = {
  low:    { sig: 'LOW',  cls: 'ok',   btnCls: 'primary' },
  medium: { sig: 'MED',  cls: 'warn', btnCls: 'primary' },
  high:   { sig: 'HIGH', cls: 'bad',  btnCls: 'danger' },
}

export default function ScriptPanel() {
  const { scripts, selectedId, loadScripts, executeScript, verifyScript, canExecute } = useStore()
  const [executing, setExecuting] = useState({})
  const exec = canExecute()

  const handleExecute = async (scriptId) => {
    setExecuting(prev => ({ ...prev, [scriptId]: true }))
    try { await executeScript(scriptId) }
    finally { setExecuting(prev => ({ ...prev, [scriptId]: false })) }
  }

  return (
    <>
      <div className="panel-head">
        ACTION_DECK
        <button onClick={() => loadScripts(selectedId)} disabled={!selectedId}>
          LOAD_SCRIPTS
        </button>
      </div>
      <div className="panel-body">
        {!selectedId ? (
          <div className="empty-state">
            <span className="empty-icon">&gt;_</span>
            <span className="empty-desc">Select incident to load action deck</span>
          </div>
        ) : scripts.length === 0 ? (
          <div className="empty-state">
            <span className="empty-icon">[ ]</span>
            <span className="empty-title">DECK EMPTY</span>
            <span className="empty-desc">Run diagnosis or press LOAD_SCRIPTS</span>
          </div>
        ) : (
          scripts.map(script => {
            const risk = RISK_CONFIG[script.risk_level] || RISK_CONFIG.low
            const isExecuting = executing[script.script_id]
            const isKgAware = script.category === 'kg_aware'
            return (
              <div key={script.script_id} className={`card script-card ${script.risk_level}`}>
                <div className="row">
                  <strong style={{ fontSize: 11, fontFamily: 'var(--font-display)', letterSpacing: '0.03em' }}>{script.name}</strong>
                  <span className={`badge ${risk.cls}`} style={{ fontSize: 8 }}>
                    <span className={`status-dot ${risk.cls}`} />
                    {risk.sig}
                  </span>
                  {isKgAware && (
                    <span className="badge" style={{ fontSize: 7, background: 'var(--sig-violet)', color: '#fff', marginLeft: 2 }}>
                      TOPO
                    </span>
                  )}
                </div>
                {script.topology_hint && (
                  <p className="muted" style={{ marginTop: 2, fontSize: 9, color: 'var(--sig-violet)', fontStyle: 'italic' }}>
                    🔗 {script.topology_hint}
                  </p>
                )}
                {script.explanation && (
                  <p className="muted" style={{ marginTop: 3, lineHeight: 1.4, fontSize: 10 }}>{script.explanation}</p>
                )}
                {script.code && (
                  <pre className="code-block">{script.code}</pre>
                )}
                <div className="row" style={{ marginTop: 6 }}>
                  <button className="ghost" onClick={() => verifyScript(script.script_id).then(r => alert(r.dry_run_result || 'DRY_RUN COMPLETE'))} disabled={isExecuting}>
                    DRY_RUN
                  </button>
                  <button className={risk.btnCls} disabled={!exec || isExecuting} onClick={() => handleExecute(script.script_id)}>
                    {isExecuting ? 'EXECUTING...' : exec ? 'EXECUTE' : 'LOCKED'}
                  </button>
                </div>
              </div>
            )
          })
        )}
      </div>
    </>
  )
}
