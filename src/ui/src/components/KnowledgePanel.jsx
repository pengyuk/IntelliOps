import { useStore } from '../store'
import { useEffect, useState } from 'react'

const API_BASE = window.location.port === '5173' ? '/api' : ''

export default function KnowledgePanel() {
  const { cases, assets, selectedId } = useStore()
  const [highFreqPatterns, setHighFreqPatterns] = useState([])
  const [skillStatus, setSkillStatus] = useState(null)
  const hasData = cases.length > 0 || assets.length > 0

  useEffect(() => {
    // Fetch high-frequency patterns on mount and when selectedId changes
    fetch(API_BASE + '/knowledge/high-frequency-patterns')
      .then(r => r.json())
      .then(d => setHighFreqPatterns(d.patterns || []))
      .catch(() => {})
    fetch(API_BASE + '/knowledge/skill-update-log')
      .then(r => r.json())
      .then(d => setSkillStatus(d))
      .catch(() => {})
  }, [selectedId])

  const triggerAggregation = async () => {
    try {
      const r = await fetch(API_BASE + '/knowledge/run-aggregation', { method: 'POST' })
      const d = await r.json()
      alert(`聚合完成: ${d.patterns_refined} 个模式已提炼, ${d.skill_updates} 个SKILL已更新`)
      // Refresh patterns
      const p = await fetch(API_BASE + '/knowledge/high-frequency-patterns').then(r => r.json())
      setHighFreqPatterns(p.patterns || [])
    } catch (e) {
      alert('聚合失败: ' + e.message)
    }
  }

  if (!selectedId) {
    return (
      <div className="panel">
        <div className="panel-head">KNOWLEDGE_BASE</div>
        <div className="panel-body">
          <div className="empty-state">
            <span className="empty-icon">[DB]</span>
            <span className="empty-desc">Select incident to query knowledge base</span>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="panel">
      <div className="panel-head">
        KNOWLEDGE_BASE
        {hasData && <span className="badge info" style={{ fontSize: 8 }}>{cases.length + assets.length} ENTRIES</span>}
      </div>
      <div className="panel-body">
        <div className="section-title">SIMILAR_CASES</div>
        {cases.length === 0 ? (
          <div className="empty-state" style={{ minHeight: 30, padding: 6 }}>
            <span className="empty-desc">No high-similarity cases found</span>
          </div>
        ) : (
          cases.map((c, i) => {
            const simScore = typeof c.similarity_score === 'number' ? Math.round(c.similarity_score * 100) : c.similarity_score
            const simLevel = simScore >= 70 ? 'ok' : simScore >= 40 ? 'warn' : 'neutral'
            return (
              <div key={i} className="card asset">
                <div className="row">
                  <strong style={{ fontSize: 11, fontFamily: 'var(--font-display)', flex: 1 }}>{c.summary}</strong>
                  <span className={`badge ${simLevel}`} style={{ fontSize: 8 }}>MATCH {simScore}%</span>
                </div>
                {c.root_cause && <p className="muted" style={{ marginTop: 2 }}>Root: {c.root_cause}</p>}
              </div>
            )
          })
        )}

        <div className="section-title">KNOWLEDGE_ASSETS</div>
        {assets.length === 0 ? (
          <div className="empty-state" style={{ minHeight: 30, padding: 6 }}>
            <span className="empty-desc">No linked knowledge assets</span>
          </div>
        ) : (
          assets.map((a, i) => {
            const relPct = Math.round((a.relevance || 0) * 100)
            const relDetail = a.reliability_detail || {}
            const relLabel = a.reliability || 'UNVERIFIED'
            const relCls = relLabel === 'RELIABLE' ? 'ok' : relLabel === 'DEGRADED' ? 'bad' : relLabel === 'VERIFIED' ? 'info' : 'neutral'
            return (
              <div key={i} className="card asset">
                <div className="row">
                  <strong style={{ fontSize: 11, fontFamily: 'var(--font-display)', flex: 1 }}>{a.title}</strong>
                  <span className={`badge ${relCls}`} style={{ fontSize: 7, marginRight: 4 }}>{relLabel}</span>
                  {relPct > 0 && <span className="badge info" style={{ fontSize: 8 }}>REL {relPct}%</span>}
                </div>
                {a.description && <p className="muted" style={{ marginTop: 2 }}>{a.description}</p>}
                {(relDetail.verification_count > 0 || relDetail.false_positive_count > 0) && (
                  <div className="muted" style={{ fontSize: 8, marginTop: 2 }}>
                    verified:{relDetail.verification_count || 0} fp:{relDetail.false_positive_count || 0} weight:{((relDetail.weight || 0.5)*100).toFixed(0)}%
                  </div>
                )}
              </div>
            )
          })
        )}

        {!hasData && (
          <div className="empty-state">
            <span className="empty-icon">[EMPTY]</span>
            <span className="empty-title">NO DATA</span>
            <span className="empty-desc">Run diagnosis to auto-correlate knowledge</span>
          </div>
        )}

        {/* High-Frequency Patterns */}
        <div className="section-title" style={{ marginTop: 12 }}>
          ⚡ HIGH_FREQ_PATTERNS
          {highFreqPatterns.length > 0 && (
            <span className="badge" style={{background:'var(--sig-violet)',color:'#fff',fontSize:8,marginLeft:6}}>
              {highFreqPatterns.length}
            </span>
          )}
        </div>
        {highFreqPatterns.length === 0 ? (
          <div className="empty-state" style={{ minHeight: 24, padding: 4 }}>
            <span className="empty-desc" style={{fontSize:10}}>No high-frequency patterns yet (need ≥5 similar incidents)</span>
          </div>
        ) : (
          highFreqPatterns.slice(0, 5).map((p, i) => (
            <div key={i} className="card asset" style={{ borderLeftColor: 'var(--sig-violet)', borderLeftWidth: 2 }}>
              <div className="row">
                <span style={{ fontSize: 10, fontFamily: 'var(--font-display)', flex: 1 }}>
                  {p.pattern_key?.slice(0, 40) || 'Unknown'}
                </span>
                <span className="badge" style={{background:'var(--sig-violet)',color:'#fff',fontSize:7}}>
                  {p.count}x
                </span>
              </div>
              <div className="muted" style={{ fontSize: 9, marginTop: 2 }}>
                {p.asset_type} · {p.source_incidents?.length || p.count} incidents
              </div>
            </div>
          ))
        )}
        {highFreqPatterns.length > 0 && (
          <button 
            onClick={triggerAggregation}
            style={{
              width:'100%',marginTop:6,padding:'4px 8px',fontSize:10,
              background:'var(--sig-violet)',color:'#fff',border:'none',
              borderRadius:4,cursor:'pointer',fontFamily:'var(--font-display)'
            }}
          >
            🧠 触发聚合提炼 → SKILL更新
          </button>
        )}

        {/* Skill Update Status */}
        {skillStatus && skillStatus.auto_remediation_skills?.length > 0 && (
          <>
            <div className="section-title" style={{ marginTop: 12 }}>
              🤖 AUTO_SKILLS
              <span className="badge ok" style={{fontSize:8,marginLeft:6}}>
                {skillStatus.auto_remediation_skills.length}
              </span>
            </div>
            {skillStatus.auto_remediation_skills.map((s, i) => (
              <div key={i} className="card asset" style={{ borderLeftColor: 'var(--sig-green)', borderLeftWidth: 2 }}>
                <span style={{ fontSize: 10 }}>{s.name}</span>
                <span className="badge neutral" style={{fontSize:7,float:'right'}}>{s.type}</span>
              </div>
            ))}
          </>
        )}
      </div>
    </div>
  )
}
