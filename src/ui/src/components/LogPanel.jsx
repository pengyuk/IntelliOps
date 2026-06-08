import { useStore } from '../store'

export default function LogPanel() {
  const { logs, selectedId, loadLogs } = useStore()
  const visibleLogs = logs
    .filter(log => !selectedId || !log.incident_id || log.incident_id === selectedId)
    .reverse()
    .slice(0, 50)

  return (
    <>
      <div className="panel-head">
        AUDIT_TRAIL
        <div style={{ display: 'flex', gap: 5, alignItems: 'center' }}>
          {visibleLogs.length > 0 && (
            <span className="badge neutral" style={{ fontSize: 8 }}>{visibleLogs.length} RECORDS</span>
          )}
          <button onClick={loadLogs}>REFRESH</button>
        </div>
      </div>
      <div className="panel-body">
        {visibleLogs.length === 0 ? (
          <div className="empty-state">
            <span className="empty-icon">[LOG]</span>
            <span className="empty-desc">No execution records</span>
          </div>
        ) : (
          visibleLogs.map(log => {
            const isSuccess = log.status === 'success'
            return (
              <div key={log.exec_id} className="card log" style={{
                borderLeftColor: isSuccess ? 'var(--sig-green)' : 'var(--sig-amber)',
                fontSize: 10
              }}>
                <div className="row">
                  <strong style={{ fontSize: 10, fontFamily: 'var(--font-display)', letterSpacing: '0.03em' }}>
                    {log.script_name || log.action_id || 'UNNAMED'}
                  </strong>
                  <span className={`badge ${isSuccess ? 'ok' : 'warn'}`} style={{ fontSize: 8 }}>
                    <span className={`status-dot ${isSuccess ? 'ok' : 'warn'}`} />
                    {isSuccess ? 'OK' : log.status || 'RUN'}
                  </span>
                </div>
                <div className="muted" style={{ marginTop: 1, fontSize: 9 }}>
                  {log.requested_by || 'SYSTEM'} :: {log.created_at?.slice(11, 19)}
                </div>
                {log.output && (
                  <div style={{ marginTop: 3, fontSize: 10, lineHeight: 1.4, color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', maxHeight: 60, overflow: 'hidden' }}>
                    {log.output.length > 200 ? log.output.slice(0, 200) + '…' : log.output}
                  </div>
                )}
                {log.conclusion && (
                  <div className="muted" style={{ marginTop: 3, fontStyle: 'italic', fontSize: 9 }}>
                    {log.conclusion}
                  </div>
                )}
              </div>
            )
          })
        )}
      </div>
    </>
  )
}
