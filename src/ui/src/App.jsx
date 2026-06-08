import { useEffect, useState } from 'react'
import { useStore } from './store'
import { useWebSocket } from './hooks/useWebSocket'
import Header from './components/Header'
import DiagnosisPanel from './components/DiagnosisPanel'
import KnowledgePanel from './components/KnowledgePanel'
import ScriptPanel from './components/ScriptPanel'
import DiscussionPanel from './components/DiscussionPanel'
import LogPanel from './components/LogPanel'
import PostmortemDialog from './components/PostmortemDialog'
import GraphView from './components/GraphView'

export default function App() {
  const { selectedId, loadUsers, loadIncidents, loadIncident, loadTimeline, loadDiscussion, loadAssets, loadLogs, loadKG, loadSkills, loadAgents, refreshAll, setSelectedId } = useStore()
  const [showPostmortem, setShowPostmortem] = useState(false)
  const [isLoading, setIsLoading] = useState(true)

  useWebSocket(selectedId)

  useEffect(() => {
    Promise.all([
      loadUsers(),
      loadIncidents(),
      loadLogs(),
      loadSkills(),
      loadAgents()
    ]).finally(() => setIsLoading(false))
  }, [])

  useEffect(() => {
    if (selectedId) {
      loadIncident(selectedId)
      loadTimeline(selectedId)
      loadDiscussion(selectedId)
      loadAssets(selectedId)
      loadKG(selectedId)
    }
  }, [selectedId])

  const handleRefresh = () => refreshAll()
  const handleDiagnose = async () => {
    const store = useStore.getState()
    await store.runDiagnosis()
  }
  const handlePostmortem = async () => {
    const store = useStore.getState()
    await store.createPostmortem()
    setShowPostmortem(true)
  }

  return (
    <div className="app">
      <Header
        onRefresh={handleRefresh}
        onDiagnose={handleDiagnose}
        onPostmortem={handlePostmortem}
      />
      <main>
        {/* Left: Context */}
        <section className="panel context">
          <div className="panel-head">CONTEXT_FEED</div>
          <div className="panel-body">
            {isLoading ? (
              <>
                <div className="skeleton skeleton-card" />
                <div className="skeleton skeleton-card" />
                <div className="skeleton skeleton-card" />
              </>
            ) : (
              <>
                <IncidentSelector />
                <GraphView />
                <TimelineList />
              </>
            )}
          </div>
        </section>

        {/* Center: Diagnosis + Knowledge */}
        <div className="workspace">
          <DiagnosisPanel />
          <KnowledgePanel />
        </div>

        {/* Center Bottom: Scripts */}
        <section className="panel workspace-bottom">
          <ScriptPanel />
        </section>

        {/* Right: Discussion */}
        <section className="panel right-top">
          <DiscussionPanel />
        </section>

        {/* Right Bottom: Logs */}
        <section className="panel right-bottom">
          <LogPanel />
        </section>
      </main>

      {showPostmortem && <PostmortemDialog onClose={() => setShowPostmortem(false)} />}
    </div>
  )
}

function IncidentSelector() {
  const { incidents, selectedId, setSelectedId } = useStore()
  if (!incidents.length) {
    return (
      <div className="empty-state">
        <span className="empty-icon">[ ]</span>
        <span className="empty-title">NO ACTIVE INCIDENTS</span>
        <span className="empty-desc">Awaiting signal input</span>
      </div>
    )
  }
  return (
    <div style={{ marginBottom: 10 }}>
      <div className="section-title">ACTIVE INCIDENTS</div>
      {incidents.map(inc => (
        <button
          key={inc.incident_id}
          className={`incident-btn ${inc.incident_id === selectedId ? 'active' : ''}`}
          onClick={() => setSelectedId(inc.incident_id)}
        >
          <strong>{inc.summary}</strong>
          <span className="muted">{inc.incident_id} :: {inc.status}</span>
        </button>
      ))}
    </div>
  )
}

function TimelineList() {
  const timeline = useStore(s => s.timeline)
  const LABELS = { alert: 'ALERT', diagnosis: 'DIAGNOSIS', action_result: 'RESULT', action_execution: 'EXEC', status: 'STATUS', conclusion: 'CONCLUSION', decision: 'DECISION' }
  const SIGNALS = { alert: '■', diagnosis: '◆', action_result: '▲', action_execution: '▶', status: '●', conclusion: '◉', decision: '◈' }

  return (
    <div>
      <div className="section-title">EVENT_STREAM</div>
      {timeline.length === 0 ? (
        <div className="empty-state" style={{ minHeight: 50, padding: 10 }}>
          <span className="empty-desc">No events recorded</span>
        </div>
      ) : (
        timeline.map(e => (
          <div key={e.event_id} className={`timeline-item ${e.event_type}`}>
            <div className="row">
              <strong style={{ fontSize: 10, fontFamily: 'var(--font-display)', letterSpacing: '0.04em' }}>
                {SIGNALS[e.event_type] || '·'} {LABELS[e.event_type] || e.event_type}
              </strong>
              <span className="muted" style={{ fontFamily: 'var(--font-mono)', fontSize: 9 }}>{e.timestamp?.slice(11, 19)}</span>
            </div>
            <div style={{ fontSize: 11, marginTop: 2 }}>{e.summary}</div>
            {e.actor && <div className="muted" style={{ marginTop: 1, fontSize: 9 }}>{e.actor}{e.role ? ` :: ${e.role}` : ''}</div>}
          </div>
        ))
      )}
    </div>
  )
}
