import { create } from 'zustand'

// Auto-detect API base: Vite dev server proxies /api → backend, direct FastAPI has no /api prefix
const API_BASE = window.location.port === '5173' ? '/api' : ''

export const useStore = create((set, get) => ({
  // State
  incidents: [],
  selectedId: '',
  incident: null,
  users: [],
  userId: 'ui-user',
  diagnosis: null,
  scripts: [],
  messages: [],
  timeline: [],
  logs: [],
  cases: [],
  assets: [],
  postmortem: null,
  kgGraph: null,
  wsStatus: {},

  // Skill & Agent state
  skills: [],
  agents: [],
  activeSkills: [],
  primarySkill: null,
  agentTimeline: [],

  // P0-1: Topology-aware context
  upstreamSystems: [],
  downstreamSystems: [],
  upstreamChanges: [],

  // P0-2: Discussion evidence
  discussionEvidence: [],

  // P1-1: Investigation state
  investigationState: { verified: [], to_verify: [], high_risk: [], excluded: [] },

  // Computed
  currentUser: () => {
    const { users, userId } = get()
    return users.find(u => u.user_id === userId) || null
  },
  canExecute: () => {
    const user = get().currentUser()
    return user?.role === 'operator'
  },

  // Actions
  setSelectedId: (id) => set({ selectedId: id, diagnosis: null, scripts: [] }),

  // API helpers
  api: async (path, options = {}) => {
    const url = API_BASE + path
    console.log(`[API] ${options.method || 'GET'} ${url}`)
    // Use AbortController for configurable timeout (default 5 min for diagnose)
    const timeout = options.timeout || (options.method === 'POST' ? 300000 : 30000)
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), timeout)
    try {
      const res = await fetch(url, {
        ...options,
        signal: controller.signal,
        headers: { 'Content-Type': 'application/json', ...(options.headers || {}) }
      })
      clearTimeout(timeoutId)
      if (!res.ok) {
        const errText = await res.text()
        console.error(`[API] Error ${res.status} from ${url}:`, errText)
        throw new Error(`API ${res.status}: ${errText.slice(0, 200)}`)
      }
      return res.json()
    } catch (err) {
      clearTimeout(timeoutId)
      if (err.name === 'AbortError') {
        console.error(`[API] Timeout after ${timeout}ms: ${url}`)
        throw new Error(`请求超时 (${Math.round(timeout/1000)}s)，后端可能正在加载模型，请稍后重试`)
      }
      throw err
    }
  },

  // Data loading
  loadUsers: async () => {
    const data = await get().api('/auth/users')
    set({ users: data.users || [] })
  },

  loadIncidents: async () => {
    const data = await get().api('/incidents')
    const { selectedId } = get()
    set({ incidents: data.incidents || [] })
    if (!selectedId && data.incidents?.length) {
      const first = data.incidents[0].incident_id
      set({ selectedId: first })
    }
  },

  loadIncident: async (id) => {
    const inc = await get().api(`/incident/${id}`)
    set({ 
      incident: inc,
      // Auto-populate from pre-computed pipeline results
      diagnosis: inc.auto_diagnosis || null,
      activeSkills: inc.active_skills || [],
      primarySkill: inc.primary_skill || null,
      cases: inc.related_cases || [],
      scripts: inc.suggested_scripts || [],
      kgGraph: inc.kg_context || null,
      // P0-1: Topology-aware context
      upstreamSystems: (inc.kg_context || {}).upstream || [],
      downstreamSystems: (inc.kg_context || {}).downstream || [],
      upstreamChanges: (inc.kg_context || {}).upstream_changes || [],
    })
  },

  loadTimeline: async (id) => {
    const data = await get().api(`/incident/${id}/timeline`)
    set({ timeline: data.timeline || [] })
  },

  loadDiscussion: async (id) => {
    const data = await get().api(`/incident/${id}/discussion`)
    set({ messages: data.messages || [] })
  },

  loadAssets: async (id) => {
    const [cases, assets] = await Promise.all([
      get().api(`/incident/${id}/related-cases`),
      get().api(`/incident/${id}/knowledge-assets`)
    ])
    set({ cases: cases.cases || [], assets: assets.assets || [] })
  },

  loadLogs: async () => {
    const data = await get().api('/action/logs')
    set({ logs: data.logs || [] })
  },

  loadScripts: async (incidentId) => {
    const { diagnosis } = get()
    const data = await get().api(`/script/suggest?incident_id=${incidentId}&diagnosis_id=${diagnosis?.diagnosis_id || ''}`)
    set({ scripts: data.suggestions || [] })
  },

  loadKG: async (incidentId) => {
    try {
      const data = await get().api(`/kg/incident/${incidentId}`)
      set({ kgGraph: data })
    } catch { set({ kgGraph: null }) }
  },

  // Skill & Agent loading
  loadSkills: async () => {
    try {
      const data = await get().api('/skills')
      set({ skills: data.skills || [] })
    } catch { /* skills not critical */ }
  },

  loadAgents: async () => {
    try {
      const data = await get().api('/agents')
      set({ agents: data.agents || [] })
    } catch { /* agents not critical */ }
  },

  loadInvestigationState: async (incidentId) => {
    try {
      const data = await get().api(`/incident/${incidentId}/investigation-state`)
      set({ investigationState: data })
    } catch { set({ investigationState: { verified: [], to_verify: [], high_risk: [], excluded: [] } }) }
  },

  addInvestigationItem: async (incidentId, quadrant, item) => {
    try {
      const data = await get().api(`/incident/${incidentId}/investigation-state/item`, {
        method: 'POST',
        body: JSON.stringify({ quadrant, item })
      })
      await get().loadInvestigationState(incidentId)
      return data
    } catch (e) { console.warn('addInvestigationItem failed:', e) }
  },

  loadActiveSkills: async (incidentId) => {
    try {
      const data = await get().api(`/incident/${incidentId}/active-skills`)
      set({ activeSkills: data.active_skills || [] })
    } catch { set({ activeSkills: [] }) }
  },

  refreshAll: async () => {
    const { selectedId } = get()
    if (!selectedId) return
    await Promise.all([
      get().loadIncident(selectedId),
      get().loadTimeline(selectedId),
      get().loadDiscussion(selectedId),
      get().loadAssets(selectedId),
      get().loadLogs(),
      get().loadKG(selectedId)
    ])
  },

  // Actions
  runDiagnosis: async () => {
    const { selectedId, userId } = get()
    if (!selectedId) throw new Error('未选择事故')
    console.log('[Diagnose] Starting async diagnosis for incident:', selectedId)
    
    // Step 1: Submit async diagnosis
    const task = await get().api('/copilot/diagnose', {
      method: 'POST',
      body: JSON.stringify({ incident_id: selectedId, user_id: userId })
    })
    console.log('[Diagnose] Task queued:', task.diagnosis_id)
    
    // Update UI immediately to show progress
    set({ 
      diagnosis: { diagnosis_id: task.diagnosis_id, status: 'queued', _progress: 0, _step: '提交诊断任务...' },
    })
    
    // Step 2: Poll until complete
    const diagnosisId = task.diagnosis_id
    const maxAttempts = 90  // 90 * 2s = 3 min max
    for (let i = 0; i < maxAttempts; i++) {
      await new Promise(r => setTimeout(r, 2000))  // 2s interval
      try {
        const poll = await get().api(`/copilot/diagnose/${diagnosisId}`)
        console.log(`[Diagnose] Poll ${i+1}: status=${poll.status} progress=${poll.progress}%`)
        
        // Update progress in UI
        set({
          diagnosis: { 
            diagnosis_id: diagnosisId, 
            status: poll.status, 
            _progress: poll.progress || 0, 
            _step: poll.step || '' 
          },
        })
        
        if (poll.status === 'completed' && poll.result) {
          const data = poll.result
          set({ 
            diagnosis: data,
            activeSkills: data.active_skills || [],
            primarySkill: data.primary_skill || null,
          })
          await Promise.all([get().loadTimeline(selectedId), get().loadScripts(selectedId), get().loadAssets(selectedId)])
          console.log('[Diagnose] Complete!')
          return
        }
        if (poll.status === 'failed') {
          throw new Error(poll.error || '诊断任务失败')
        }
      } catch (e) {
        if (e.message?.includes('diagnosis task not found')) continue // task not created yet
        throw e
      }
    }
    throw new Error('诊断超时（超过3分钟），请稍后重试')
  },

  sendDiscussion: async (text) => {
    const { selectedId, userId, currentUser } = get()
    const user = currentUser()
    await get().api(`/incident/${selectedId}/discussion`, {
      method: 'POST',
      body: JSON.stringify({ author: userId, message: text, message_type: user?.role === 'developer' ? 'development' : 'maintenance' })
    })
    await get().loadDiscussion(selectedId)
  },

  askCopilot: async (text) => {
    const { selectedId, userId, diagnosis } = get()
    const data = await get().api('/copilot/chat', {
      method: 'POST',
      body: JSON.stringify({ incident_id: selectedId, diagnosis_id: diagnosis?.diagnosis_id, user_id: userId, message: text })
    })
    if (!get().diagnosis) set({ diagnosis: { diagnosis_id: data.diagnosis_id } })
    // Capture skill context from response
    if (data.active_skills) set({ activeSkills: data.active_skills })
    if (data.primary_skill) set({ primarySkill: data.primary_skill })
    if (data.agent_timeline) set({ agentTimeline: data.agent_timeline })
    // P0-2: Capture discussion evidence from Copilot response
    if (data.discussion_evidence) set({ discussionEvidence: data.discussion_evidence })
    // P1-1: Capture investigation state if returned
    if (data._investigation_state) set({ investigationState: data._investigation_state })
    await Promise.all([get().loadDiscussion(selectedId), get().loadTimeline(selectedId), get().loadScripts(selectedId)])
    return data
  },

  executeScript: async (scriptId) => {
    const { selectedId, userId, diagnosis } = get()
    const result = await get().api('/script/execute', {
      method: 'POST',
      body: JSON.stringify({ script_id: scriptId, requested_by: userId, lifecycle_type: 'once', incident_id: selectedId, diagnosis_id: diagnosis?.diagnosis_id, feed_to_copilot: true })
    })
    await Promise.all([get().loadLogs(), get().loadDiscussion(selectedId), get().loadTimeline(selectedId)])
    return result
  },

  verifyScript: async (scriptId) => {
    return get().api('/script/verify', { method: 'POST', body: JSON.stringify({ script_id: scriptId, user_id: get().userId }) })
  },

  createPostmortem: async () => {
    const { selectedId, userId } = get()
    const report = await get().api(`/incident/${selectedId}/postmortem`, {
      method: 'POST',
      body: JSON.stringify({ requested_by: userId, mark_resolved: true })
    })
    set({ postmortem: report })
    await get().refreshAll()
    return report
  }
}))
