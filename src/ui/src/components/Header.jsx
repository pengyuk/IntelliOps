import { useStore } from '../store'

const STATUS_MAP = {
  New: { label: 'NEW', cls: 'info' },
  Analyzing: { label: 'ANALYZING', cls: 'warn' },
  Executing: { label: 'EXECUTING', cls: 'warn' },
  Resolved: { label: 'RESOLVED', cls: 'ok' },
  Postmortem: { label: 'POSTMORTEM', cls: 'info' },
}

export default function Header({ onRefresh, onDiagnose, onPostmortem, isDiagnosing, diagnoseError }) {
  const { incident, users, userId, setUserId, canExecute, diagnosis, activeSkills } = useStore()
  const exec = canExecute()
  const statusInfo = STATUS_MAP[incident?.status] || { label: incident?.status || '--', cls: 'neutral' }
  const hasAutoDiagnosis = !!diagnosis
  const pipelineReady = hasAutoDiagnosis && activeSkills?.length > 0
  const canDiagnose = !!incident && !isDiagnosing

  return (
    <header>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, minWidth: 0 }}>
        <div style={{
          flexShrink: 0, width: 28, height: 28,
          border: '1.5px solid var(--sig-green)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          color: 'var(--sig-green)', fontFamily: 'var(--font-display)',
          fontWeight: 700, fontSize: 13, letterSpacing: '0.04em',
          background: 'rgba(0,240,160,0.04)'
        }}>IO</div>
        <div style={{ minWidth: 0 }}>
          <h1>{incident?.summary || 'INTELLIOPS // TACTICAL OPERATIONS CONSOLE'}</h1>
          {incident && (
            <div className="meta" style={{ marginTop: 2 }}>
              <span className="badge info" style={{ fontFamily: 'var(--font-mono)', fontSize: 8 }}>{incident.incident_id}</span>
              <span className={`badge ${statusInfo.cls}`}>
                <span className={`status-dot ${statusInfo.cls}`} />
                {statusInfo.label}
              </span>
              {pipelineReady && (
                <span className="badge ok" title="智能分析已就绪">
                  <span className="status-dot ok" />
                  AI READY
                </span>
              )}
              <span className={`badge ${exec ? 'ok' : 'neutral'}`}>
                {exec ? 'RW' : 'RO'}
              </span>
            </div>
          )}
        </div>
      </div>
      <div className="top-actions">
        <select value={userId} onChange={e => setUserId(e.target.value)} style={{ width: 140 }}>
          {users.map(u => <option key={u.user_id} value={u.user_id}>{u.name} : {u.role}</option>)}
        </select>
        <button className="ghost" onClick={onRefresh} title="REFRESH">REFRESH</button>
        <button className="primary" onClick={onDiagnose} disabled={!canDiagnose}>
          {isDiagnosing ? '⏳ DIAGNOSING...' : pipelineReady ? 'RE-DIAGNOSE' : 'DIAGNOSE'}
        </button>
        <button onClick={onPostmortem} disabled={!incident || incident?.status !== 'Resolved'}>
          POSTMORTEM
        </button>
        {diagnoseError && (
          <span className="badge bad" style={{ fontSize: 9, maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            ❌ {diagnoseError}
          </span>
        )}
      </div>
    </header>
  )
}
