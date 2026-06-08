import { useStore } from '../store'

export default function PostmortemDialog({ onClose }) {
  const postmortem = useStore(s => s.postmortem)
  if (!postmortem) return null

  const rc = postmortem.root_cause_conclusion || {}
  const confPct = Math.round((rc.confidence || 0) * 100)

  return (
    <div className="dialog-overlay" onClick={onClose}>
      <div className="dialog" onClick={e => e.stopPropagation()}>
        <div className="row" style={{ marginBottom: 14, paddingBottom: 10, borderBottom: '1px solid var(--border-dim)' }}>
          <h2 style={{ fontFamily: 'var(--font-display)', letterSpacing: '0.05em', fontSize: 15 }}>POSTMORTEM_REPORT</h2>
          <button onClick={onClose} className="ghost">CLOSE</button>
        </div>

        <div className="card" style={{ borderColor: 'var(--border-dim)' }}>
          <div className="row">
            <strong style={{ fontSize: 12, fontFamily: 'var(--font-display)' }}>{postmortem.postmortem_id}</strong>
            <span className={`badge ${postmortem.status === 'published' ? 'ok' : 'warn'}`}>
              {postmortem.status === 'published' ? 'PUBLISHED' : postmortem.status}
            </span>
          </div>
          <div style={{ marginTop: 8 }}>
            <div className="section-title">ROOT_CAUSE</div>
            <p style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)', fontFamily: 'var(--font-display)' }}>
              {rc.cause || '--'}
            </p>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 4 }}>
              <span className={`badge ${confPct >= 70 ? 'ok' : confPct >= 40 ? 'warn' : 'bad'}`}>
                CONF {confPct}%
              </span>
              {rc.detail && <span className="muted">{rc.detail}</span>}
            </div>
          </div>
        </div>

        {postmortem.improvement_suggestions?.length > 0 && (
          <>
            <div className="section-title" style={{ marginTop: 14 }}>IMPROVEMENTS</div>
            {(postmortem.improvement_suggestions || []).map((item, i) => (
              <div key={i} className="card" style={{ borderLeftColor: 'var(--sig-violet)' }}>
                <span style={{ fontSize: 12 }}>{item}</span>
              </div>
            ))}
          </>
        )}

        {postmortem.timeline?.length > 0 && (
          <>
            <div className="section-title" style={{ marginTop: 14 }}>TIMELINE_SNAPSHOT</div>
            {(postmortem.timeline || []).slice(0, 10).map((item, i) => (
              <div key={i} className="timeline-item">
                <span className="muted" style={{ fontFamily: 'var(--font-mono)', fontSize: 9 }}>{item.timestamp?.slice(11, 19)}</span>
                <span style={{ marginLeft: 8, fontSize: 11 }}>{item.summary}</span>
              </div>
            ))}
          </>
        )}

        {postmortem.knowledge && (
          <>
            <div className="section-title" style={{ marginTop: 14 }}>KNOWLEDGE_ARTIFACTS</div>
            <div className="card" style={{ borderColor: 'var(--border-dim)' }}>
              <div className="info-row">
                <span className="info-label">RULES</span>
                <span>{(postmortem.knowledge.root_cause_rules || []).length}</span>
              </div>
              <div className="info-row">
                <span className="info-label">SOPS</span>
                <span>{(postmortem.knowledge.sop_templates || []).length}</span>
              </div>
              {(postmortem.knowledge.key_learnings || []).length > 0 && (
                <div className="info-row">
                  <span className="info-label">LEARNINGS</span>
                  <span>{(postmortem.knowledge.key_learnings || []).join(' | ')}</span>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
