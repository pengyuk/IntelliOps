import { useStore } from '../store'

const SKILL_LABELS = {
  'incident-diagnosis': 'DIAGNOSE',
  'log-analysis': 'PARSE_LOGS',
  'script-operations': 'EXEC_SCRIPT',
  'postmortem-generator': 'POSTMORTEM',
  'knowledge-retrieval': 'FETCH_KB',
  'war-room-coordination': 'COORDINATE',
}

const CONFIDENCE_CONFIG = {
  high:   { cls: 'ok',   gradient: 'linear-gradient(90deg, #00f0a0, #00ffb4)' },
  medium: { cls: 'warn', gradient: 'linear-gradient(90deg, #ffb020, #ffc850)' },
  low:    { cls: 'bad',  gradient: 'linear-gradient(90deg, #ff4060, #ff6080)' },
}

export default function DiagnosisPanel() {
  const diagnosis = useStore(s => s.diagnosis)
  const activeSkills = useStore(s => s.activeSkills)
  const primarySkill = useStore(s => s.primarySkill)
  const agentTimeline = useStore(s => s.agentTimeline)

  if (!diagnosis) {
    return (
      <div className="panel">
        <div className="panel-head">ROOT_CAUSE_ENGINE <span className="badge neutral">IDLE</span></div>
        <div className="panel-body">
          <div className="empty-state">
            <span className="empty-icon">[ ? ]</span>
            <span className="empty-title">ENGINE STANDBY</span>
            <span className="empty-desc">Select an incident and press DIAGNOSE to activate root cause analysis</span>
          </div>
        </div>
      </div>
    )
  }

  const summaryPct = Math.round((diagnosis.confidence_summary || 0) * 100)
  const summaryLevel = summaryPct >= 70 ? 'high' : summaryPct >= 40 ? 'medium' : 'low'
  const summaryCfg = CONFIDENCE_CONFIG[summaryLevel]

  return (
    <div className="panel">
      <div className="panel-head">
        ROOT_CAUSE_ENGINE
        <span className={`badge ${summaryCfg.cls}`}>
          <span className={`status-dot ${summaryCfg.cls}`} />
          CONF {summaryPct}%
        </span>
      </div>
      <div className="panel-body">
        {/* Active Skills */}
        {(activeSkills.length > 0 || primarySkill) && (
          <div className="card" style={{ borderColor: 'rgba(0,216,255,0.2)', background: 'rgba(0,216,255,0.02)' }}>
            <div className="section-title" style={{ marginTop: 0, marginBottom: 4 }}>ACTIVE_AGENTS</div>
            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
              {(activeSkills || []).map(skillName => {
                const isPrimary = skillName === primarySkill
                return (
                  <span key={skillName} className="chip" style={{
                    fontWeight: isPrimary ? 700 : 400,
                    borderColor: isPrimary ? 'var(--sig-cyan)' : 'var(--border-dim)',
                    color: isPrimary ? 'var(--sig-cyan)' : 'var(--text-muted)',
                    background: isPrimary ? 'rgba(0,216,255,0.06)' : 'transparent'
                  }}>
                    {SKILL_LABELS[skillName] || skillName}
                    {isPrimary && ' *'}
                  </span>
                )
              })}
            </div>
            {agentTimeline.length > 0 && (
              <div className="agent-timeline">
                {agentTimeline.slice(-4).map((entry, i) => (
                  <div key={i}>[{entry.agent}] {entry.summary}</div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Root Cause Candidates */}
        {(diagnosis.candidate_root_causes || []).map((c, i) => {
          const cred = c.credibility || {}
          const pct = Math.round((c.confidence || 0) * 100)
          const level = cred.credibility_level || (pct >= 70 ? 'high' : pct >= 40 ? 'medium' : 'low')
          const cfg = CONFIDENCE_CONFIG[level] || CONFIDENCE_CONFIG.medium
          return (
            <div key={i} className="card cause" style={{ borderLeftColor: level === 'high' ? '#00f0a0' : level === 'medium' ? '#ffb020' : '#ff4060' }}>
              <div className="row">
                <strong style={{ fontSize: 12, fontFamily: 'var(--font-display)', letterSpacing: '0.02em' }}>
                  [{i + 1}] {c.cause}
                </strong>
                <span className={`badge ${cfg.cls}`}>
                  <span className={`status-dot ${cfg.cls}`} />
                  {pct}%
                </span>
              </div>
              <div className="progress">
                <span style={{ width: `${pct}%`, background: cfg.gradient }} />
              </div>
              {c.detail && <p className="muted" style={{ marginTop: 4, lineHeight: 1.5 }}>{c.detail}</p>}
              {(c.evidence_items || c.evidence_chain || []).length > 0 && (
                <div className="chips">
                  {(c.evidence_items || c.evidence_chain || []).map((e, j) => (
                    <span key={j} className="chip" title={e}>{e}</span>
                  ))}
                </div>
              )}
            </div>
          )
        })}

        {/* Log Analysis */}
        {diagnosis.log_analysis && (
          <div className="card" style={{ borderLeftColor: 'var(--sig-violet)' }}>
            <strong style={{ fontSize: 11, fontFamily: 'var(--font-display)', letterSpacing: '0.04em', color: 'var(--text-secondary)' }}>LOG_ANALYSIS</strong>
            <p className="muted" style={{ marginTop: 3, lineHeight: 1.5 }}>{diagnosis.log_analysis.summary}</p>
          </div>
        )}

        {/* Skill Suggestions */}
        {diagnosis.skill_suggestions && diagnosis.skill_suggestions.length > 0 && (
          <div className="card" style={{ borderLeftColor: 'var(--sig-violet)' }}>
            <strong style={{ fontSize: 11, fontFamily: 'var(--font-display)', letterSpacing: '0.04em', color: 'var(--text-secondary)' }}>SUGGESTED_PLAYBOOK</strong>
            {diagnosis.skill_suggestions.map((s, i) => (
              <div key={i} className="info-row" style={{ marginTop: 3 }}>
                <span style={{ color: 'var(--sig-cyan)', fontFamily: 'var(--font-mono)', fontSize: 9 }}>&gt;</span>
                <div style={{ fontSize: 11 }}>
                  <span style={{ fontFamily: 'var(--font-display)', fontWeight: 700, color: 'var(--text-primary)', fontSize: 10 }}>
                    {SKILL_LABELS[s.skill] || s.skill}
                  </span>
                  <span className="muted" style={{ marginLeft: 6 }}>{s.step}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
