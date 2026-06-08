import { create } from 'zustand'

const API_BASE = '/api'

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
    const res = await fetch(API_BASE + path, {
      ...options,
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) }
    })
    if (!res.ok) throw new Error(await res.text())
    return res.json()
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
    const data = await get().api('/copilot/diagnose', {
      method: 'POST',
      body: JSON.stringify({ incident_id: selectedId, user_id: userId })
    })
    set({ 
      diagnosis: data,
      activeSkills: data.active_skills || [],
      primarySkill: data.primary_skill || null,
    })
    await Promise.all([get().loadTimeline(selectedId), get().loadScripts(selectedId), get().loadAssets(selectedId)])
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
