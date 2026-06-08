import { useStore } from '../store'

export default function KnowledgePanel() {
  const { cases, assets, selectedId } = useStore()
  const hasData = cases.length > 0 || assets.length > 0

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
            return (
              <div key={i} className="card asset">
                <div className="row">
                  <strong style={{ fontSize: 11, fontFamily: 'var(--font-display)', flex: 1 }}>{a.title}</strong>
                  {relPct > 0 && <span className="badge info" style={{ fontSize: 8 }}>REL {relPct}%</span>}
                </div>
                {a.description && <p className="muted" style={{ marginTop: 2 }}>{a.description}</p>}
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
      </div>
    </div>
  )
}
