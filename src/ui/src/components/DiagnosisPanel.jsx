import { useStore } from '../store'

const SKILL_ICONS = {
  'incident-diagnosis': '🔍',
  'log-analysis': '📋',
  'script-operations': '⚡',
  'postmortem-generator': '📝',
  'knowledge-retrieval': '📚',
  'war-room-coordination': '📢',
}

const SKILL_NAMES = {
  'incident-diagnosis': '故障诊断',
  'log-analysis': '日志分析',
  'script-operations': '脚本执行',
  'postmortem-generator': '复盘生成',
  'knowledge-retrieval': '知识检索',
  'war-room-coordination': '应急协同',
}

const CONFIDENCE_CONFIG = {
  high: { cls: 'ok', label: '高置信度', gradient: 'linear-gradient(90deg, #059669, #34d399)' },
  medium: { cls: 'warn', label: '中等置信度', gradient: 'linear-gradient(90deg, #d97706, #fbbf24)' },
  low: { cls: 'bad', label: '低置信度', gradient: 'linear-gradient(90deg, #dc2626, #f87171)' },
}

export default function DiagnosisPanel() {
  const diagnosis = useStore(s => s.diagnosis)
  const activeSkills = useStore(s => s.activeSkills)
  const primarySkill = useStore(s => s.primarySkill)
  const agentTimeline = useStore(s => s.agentTimeline)
  const investigationState = useStore(s => s.investigationState)
  const upstreamSystems = useStore(s => s.upstreamSystems)
  const upstreamChanges = useStore(s => s.upstreamChanges)

  if (!diagnosis) {
    return (
      <div className="panel">
        <div className="panel-head">
          🔬 根因推理
          <span className="badge neutral">待诊断</span>
        </div>
        <div className="panel-body">
          <div className="empty-state">
            <span className="empty-icon">🧠</span>
            <span className="empty-title">尚未启动诊断</span>
            <span className="empty-desc">选择事故后点击「Copilot 诊断」启动 AI 根因推理引擎</span>
          </div>
        </div>
      </div>
    )
  }

  // Show progress for async diagnosis (queued / running)
  const isProcessing = diagnosis.status === 'queued' || diagnosis.status === 'running'
  if (isProcessing) {
    const progress = diagnosis._progress || 0
    const step = diagnosis._step || '初始化...'
    return (
      <div className="panel">
        <div className="panel-head">
          🔬 根因推理
          <span className="badge warn">
            <span className="status-dot warn" />
            {diagnosis.status === 'queued' ? '排队中' : '分析中'}
          </span>
        </div>
        <div className="panel-body">
          <div className="card" style={{ borderColor: 'var(--sig-amber)', borderLeftWidth: 3 }}>
            <div style={{ fontSize: 12, fontFamily: 'var(--font-display)', marginBottom: 8 }}>
              ⏳ {step}
            </div>
            <div style={{ 
              width: '100%', height: 6, background: 'var(--border-dim)', 
              borderRadius: 3, overflow: 'hidden' 
            }}>
              <div style={{
                width: `${Math.max(progress, 5)}%`,
                height: '100%',
                background: 'linear-gradient(90deg, var(--sig-amber), var(--sig-green))',
                borderRadius: 3,
                transition: 'width 0.5s ease',
              }} />
            </div>
            <div style={{ fontSize: 9, color: 'var(--text-muted)', marginTop: 4, textAlign: 'right' }}>
              {progress}%
            </div>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 8, lineHeight: 1.5 }}>
              💡 诊断在后台异步执行，无需等待。可切换查看其他事故。
            </div>
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
        🔬 根因推理
        <span className={`badge ${summaryCfg.cls}`}>
          <span className={`status-dot ${summaryCfg.cls}`} style={{ width: 6, height: 6 }} />
          综合置信度 {summaryPct}%
        </span>
      </div>
      <div className="panel-body">
        {/* ── Active Skills Bar ── */}
        {(activeSkills.length > 0 || primarySkill) && (
          <div className="card" style={{ background: 'linear-gradient(135deg, #eff6ff, #f5f3ff)', border: '1px solid #e0e7ff' }}>
            <div className="section-title" style={{ marginTop: 0, marginBottom: 6 }}>🧠 活跃智能体</div>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {(activeSkills || []).map(skillName => {
                const isPrimary = skillName === primarySkill
                return (
                  <span key={skillName} className="chip" style={{
                    fontWeight: isPrimary ? 700 : 500,
                    background: isPrimary ? '#dbeafe' : '#f8fafc',
                    border: isPrimary ? '1.5px solid #2563eb' : '1px solid #e2e8f0',
                    color: isPrimary ? '#1d4ed8' : '#475569',
                  }}>
                    {SKILL_ICONS[skillName] || '🤖'} {SKILL_NAMES[skillName] || skillName}
                    {isPrimary && ' ⭐'}
                  </span>
                )
              })}
            </div>
            {agentTimeline.length > 0 && (
              <div className="agent-timeline">
                {agentTimeline.slice(-4).map((entry, i) => (
                  <div key={i}>{entry.agent}: {entry.summary}</div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ── Root Cause Candidates ── */}
        {(diagnosis.candidate_root_causes || []).map((c, i) => {
          const cred = c.credibility || {}
          const pct = Math.round((c.confidence || 0) * 100)
          const level = cred.credibility_level || (pct >= 70 ? 'high' : pct >= 40 ? 'medium' : 'low')
          const cfg = CONFIDENCE_CONFIG[level] || CONFIDENCE_CONFIG.medium
          return (
            <div key={i} className="card cause" style={{ borderLeftColor: level === 'high' ? '#059669' : level === 'medium' ? '#d97706' : '#dc2626' }}>
              <div className="row">
                <strong style={{ fontSize: 13 }}>#{i + 1} {c.cause}</strong>
                <span className={`badge ${cfg.cls}`}>
                  <span className={`status-dot ${cfg.cls}`} style={{ width: 6, height: 6 }} />
                  {pct}% · {cfg.label}
                </span>
              </div>
              <div className="progress">
                <span style={{ width: `${pct}%`, background: cfg.gradient }} />
              </div>
              {c.detail && <p className="muted" style={{ marginTop: 6, lineHeight: 1.5 }}>{c.detail}</p>}
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

        {/* ── Log Analysis Summary ── */}
        {diagnosis.log_analysis && (
          <div className="card" style={{ borderLeftColor: '#7c3aed' }}>
            <strong style={{ fontSize: 12 }}>📊 日志分析</strong>
            <p className="muted" style={{ marginTop: 4, lineHeight: 1.5 }}>{diagnosis.log_analysis.summary}</p>
          </div>
        )}

        {/* ── P1-1: Investigation State (Excluded/Verified) ── */}
        {(investigationState.excluded?.length > 0 || investigationState.verified?.length > 0) && (
          <div className="card" style={{ background: '#fef2f2', borderLeftColor: '#dc2626' }}>
            <strong style={{ fontSize: 12 }}>🚫 排查状态</strong>
            {investigationState.excluded?.length > 0 && (
              <div style={{ marginTop: 4 }}>
                <span className="badge bad" style={{ fontSize: 8 }}>已排除 {investigationState.excluded.length} 项</span>
                {investigationState.excluded.slice(0, 3).map((item, i) => (
                  <div key={i} className="muted" style={{ fontSize: 10, marginTop: 2 }}>❌ {item.name || item}</div>
                ))}
              </div>
            )}
            {investigationState.verified?.length > 0 && (
              <div style={{ marginTop: 4 }}>
                <span className="badge ok" style={{ fontSize: 8 }}>已验证 {investigationState.verified.length} 项</span>
                {investigationState.verified.slice(0, 3).map((item, i) => (
                  <div key={i} className="muted" style={{ fontSize: 10, marginTop: 2 }}>✅ {item.name || item}</div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ── P0-1: Topology Alerts ── */}
        {upstreamChanges.length > 0 && (
          <div className="card" style={{ background: '#fef3c7', border: '1px solid #f59e0b', borderLeftColor: '#f59e0b' }}>
            <strong style={{ fontSize: 12 }}>⚠️ 上游系统有变更</strong>
            {upstreamChanges.slice(0, 3).map((c, i) => (
              <div key={i} style={{ fontSize: 10, marginTop: 2, color: '#92400e' }}>
                🔺 {c.name || c.id || '未知变更'}
              </div>
            ))}
            <p className="muted" style={{ fontSize: 9, marginTop: 3 }}>上游变更是根因的高概率来源，请优先排查</p>
          </div>
        )}

        {/* ── Skill Suggestions ── */}
        {diagnosis.skill_suggestions && diagnosis.skill_suggestions.length > 0 && (
          <div className="card" style={{ background: '#fafafa', borderLeftColor: '#8b5cf6' }}>
            <strong style={{ fontSize: 12 }}>💡 建议下一步</strong>
            {diagnosis.skill_suggestions.map((s, i) => (
              <div key={i} className="info-row" style={{ marginTop: 4 }}>
                <span>{SKILL_ICONS[s.skill] || '•'}</span>
                <div>
                  <strong style={{ fontSize: 12 }}>{SKILL_NAMES[s.skill] || s.skill}</strong>
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
