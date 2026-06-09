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
  const { selectedId, loadUsers, loadIncidents, loadIncident, loadTimeline, loadDiscussion, loadAssets, loadLogs, loadKG, loadSkills, loadAgents, loadInvestigationState, refreshAll, setSelectedId } = useStore()
  const [showPostmortem, setShowPostmortem] = useState(false)
  const [isLoading, setIsLoading] = useState(true)
  const [isDiagnosing, setIsDiagnosing] = useState(false)
  const [diagnoseError, setDiagnoseError] = useState(null)

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
      loadInvestigationState(selectedId)
    }
  }, [selectedId])

  const handleRefresh = () => refreshAll()
  const handleDiagnose = async () => {
    const store = useStore.getState()
    if (!store.selectedId) {
      setDiagnoseError('请先选择一个事故')
      return
    }
    setIsDiagnosing(true)
    setDiagnoseError(null)
    try {
      await store.runDiagnosis()
    } catch (err) {
      console.error('[Diagnose] Failed:', err)
      setDiagnoseError(err.message || '诊断请求失败，请检查后端服务是否运行')
    } finally {
      setIsDiagnosing(false)
    }
  }
  const handlePostmortem = async () => {
    const store = useStore.getState()
    try {
      await store.createPostmortem()
      setShowPostmortem(true)
    } catch (err) {
      console.error('[Postmortem] Failed:', err)
      alert('复盘生成失败: ' + (err.message || '未知错误'))
    }
  }

  return (
    <div className="app">
      <Header
        onRefresh={handleRefresh}
        onDiagnose={handleDiagnose}
        onPostmortem={handlePostmortem}
        isDiagnosing={isDiagnosing}
        diagnoseError={diagnoseError}
      />
      <main>
        {/* Left: Context */}
        <section className="panel context">
          <div className="panel-head">📋 事故与知识上下文</div>
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
        <span className="empty-icon">📭</span>
        <span className="empty-title">暂无事故</span>
        <span className="empty-desc">事故接入后将自动出现在此处</span>
      </div>
    )
  }
  return (
    <div style={{ marginBottom: 10 }}>
      <div className="section-title">事故列表</div>
      {incidents.map(inc => (
        <button
          key={inc.incident_id}
          className={`incident-btn ${inc.incident_id === selectedId ? 'active' : ''}`}
          onClick={() => setSelectedId(inc.incident_id)}
        >
          <strong>{inc.summary}</strong>
          <span className="muted">{inc.incident_id} · {inc.status}</span>
        </button>
      ))}
    </div>
  )
}

function TimelineList() {
  const timeline = useStore(s => s.timeline)
  const upstreamSystems = useStore(s => s.upstreamSystems)
  const downstreamSystems = useStore(s => s.downstreamSystems)
  const upstreamChanges = useStore(s => s.upstreamChanges)
  const ICONS = { alert: '🚨', diagnosis: '🧠', action_result: '✅', action_execution: '⚡', status: '📌', conclusion: '🎯', decision: '✋',
    kg_context: '🔗', log_analysis: '📊', knowledge: '📚', script_execution: '⚡', diagnosis_update: '🔄', postmortem: '📝',
    evidence_change: '🔧', root_cause_confirmed: '✅', action_taken: '⚡', recovery_indication: '🟢', evidence_found: '🔍', handoff: '🔄',
    discussion_insight: '💬' }
  const LABELS = { alert: '告警', diagnosis: 'AI推理', action_result: '执行结果', action_execution: '动作执行', status: '状态变更',
    conclusion: '结论', decision: '决策', kg_context: 'KG分析', log_analysis: '日志分析', knowledge: '知识匹配',
    script_execution: '脚本执行', diagnosis_update: '诊断更新', postmortem: '复盘',
    evidence_change: '协同·变更', root_cause_confirmed: '协同·根因确认', action_taken: '协同·操作',
    recovery_indication: '协同·恢复', evidence_found: '协同·发现', handoff: '协同·交接', discussion_insight: '协同·洞察' }

  return (
    <div>
      <div className="section-title">⏱ 时间线</div>
      {/* P0-1: Topology summary */}
      {(upstreamSystems.length > 0 || upstreamChanges.length > 0) && (
        <div className="card" style={{ fontSize: 10, padding: 6, marginBottom: 6, background: '#fef3c7', border: '1px solid #fcd34d' }}>
          {upstreamSystems.length > 0 && (
            <div>🔺 上游: {upstreamSystems.map(n => n.name || n.id).join(', ')}</div>
          )}
          {downstreamSystems.length > 0 && (
            <div>🔻 下游: {downstreamSystems.map(n => n.name || n.id).slice(0, 5).join(', ')}</div>
          )}
          {upstreamChanges.length > 0 && (
            <div style={{ color: '#dc2626' }}>⚠️ 上游变更: {upstreamChanges.map(n => n.name || n.id).join(', ')}</div>
          )}
        </div>
      )}
      {timeline.length === 0 ? (
        <div className="empty-state" style={{ minHeight: 60, padding: 12 }}>
          <span className="empty-desc">选择事故后展示事件时间线</span>
        </div>
      ) : (
        timeline.map(e => (
          <div key={e.event_id} className={`timeline-item ${e.event_type}`}>
            <div className="row">
              <strong style={{ fontSize: 12 }}>{ICONS[e.event_type] || '•'} {LABELS[e.event_type] || e.event_type}</strong>
              <span className="muted">{e.timestamp?.slice(11, 19)}</span>
            </div>
            <div style={{ fontSize: 12, marginTop: 2 }}>{e.summary}</div>
            {e.actor && <div className="muted" style={{ marginTop: 2 }}>{e.actor}{e.role ? ` · ${e.role}` : ''}</div>}
            {/* P0-3: Show root cause link */}
            {e.related_root_cause_id && (
              <span className="badge" style={{ fontSize: 7, marginTop: 2, background: '#e0e7ff', color: '#3730a3' }}>
                🔗 {e.related_root_cause_id}
              </span>
            )}
          </div>
        ))
      )}
    </div>
  )
}
