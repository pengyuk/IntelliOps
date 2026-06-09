import { useState, useRef, useEffect } from 'react'
import { useStore } from '../store'

const ROLE_CONFIG = {
  operator:    { sig: 'OPS', cls: 'operator' },
  developer:   { sig: 'DEV', cls: 'developer' },
  copilot:     { sig: 'AI',  cls: 'copilot' },
  maintenance: { sig: 'OPS', cls: 'operator' },
  development: { sig: 'DEV', cls: 'developer' },
}

export default function DiscussionPanel() {
  const { messages, sendDiscussion, askCopilot, selectedId, discussionEvidence } = useStore()
  const [text, setText] = useState('')
  const [streaming, setStreaming] = useState('')
  const [isAsking, setIsAsking] = useState(false)
  const bodyRef = useRef(null)

  useEffect(() => {
    if (bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight
  }, [messages, streaming])

  const handleSend = async () => {
    if (!text.trim() || !selectedId) return
    await sendDiscussion(text)
    setText('')
  }

  const handleAskCopilot = async () => {
    if (!text.trim() || !selectedId) return
    setIsAsking(true)
    setStreaming('Processing...')
    try {
      const result = await askCopilot(text)
      setStreaming(result?.response || '')
    } catch { setStreaming('') }
    finally { setIsAsking(false); setText('') }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && e.ctrlKey) handleSend()
    if (e.key === 'Enter' && e.metaKey) handleAskCopilot()
  }

  return (
    <>
      <div className="panel-head">
        COMMS_CHANNEL
        <span className="badge ok" style={{ fontSize: 8 }}>LIVE</span>
      </div>
      <div className="panel-body" ref={bodyRef}>
        {!messages.length && !streaming && (
          <div className="empty-state">
            <span className="empty-icon">&gt;_</span>
            <span className="empty-title">CHANNEL OPEN</span>
            <span className="empty-desc">Type below to communicate with team or query Copilot</span>
          </div>
        )}

        {messages.map(msg => {
          const cfg = ROLE_CONFIG[msg.role || msg.message_type] || ROLE_CONFIG.operator
          return (
            <div key={msg.comment_id} className={`message ${cfg.cls}`}>
              <div className="row">
                <strong style={{ fontSize: 10, fontFamily: 'var(--font-display)', letterSpacing: '0.05em' }}>
                  [{cfg.sig}] {msg.author}
                </strong>
                <span className="muted" style={{ fontFamily: 'var(--font-mono)', fontSize: 9 }}>{msg.created_at?.slice(11, 19)}</span>
              </div>
              <div style={{ marginTop: 3, fontSize: 12, lineHeight: 1.5, whiteSpace: 'pre-wrap' }}>{msg.message}</div>
            </div>
          )
        })}

        {streaming && (
          <div className={`message copilot ${isAsking ? '' : 'streaming-message'}`}>
            <div className="row">
              <strong style={{ fontSize: 10, fontFamily: 'var(--font-display)', letterSpacing: '0.05em' }}>
                [AI] Copilot{isAsking && <span style={{ fontWeight: 400, color: 'var(--text-dim)', marginLeft: 6 }}>thinking...</span>}
              </strong>
            </div>
            <div style={{ marginTop: 3, fontSize: 12, lineHeight: 1.5, whiteSpace: 'pre-wrap' }}>
              {streaming}
              {isAsking && <span className="streaming-cursor" />}
            </div>
          </div>
        )}

        {/* P0-2: Discussion evidence extracted by sync agent */}
        {discussionEvidence.length > 0 && (
          <div className="section-title" style={{ fontSize: 9, marginTop: 8, marginBottom: 4, color: 'var(--sig-violet)' }}>
            🧠 AI从讨论中提取的证据
          </div>
        )}
        {discussionEvidence.map((ev, i) => {
          const evIcons = { change: '🔧', confirmation: '✅', action_taken: '⚡', recovery: '🟢', ongoing: '🔴', discovery: '🔍', handoff: '🔄' }
          return (
            <div key={i} className="card" style={{ fontSize: 10, padding: '4px 8px', marginBottom: 4, borderLeftColor: 'var(--sig-violet)', borderLeftWidth: 2 }}>
              {evIcons[ev.type] || '📌'} [{ev.author_role}] {ev.summary}
              <span className="muted" style={{ marginLeft: 6 }}>{(ev.confidence * 100).toFixed(0)}% 可信</span>
            </div>
          )
        })}
      </div>
      <div className="composer">
        <textarea
          value={text}
          onChange={e => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="> Enter message... [Ctrl+Enter: send | Cmd+Enter: query AI]"
          disabled={!selectedId}
        />
        <div className="row">
          <span className="muted-sm" style={{ flex: 1, fontFamily: 'var(--font-mono)', fontSize: 9 }}>
            {selectedId ? 'CTRL+ENTER=SEND  CMD+ENTER=QUERY_AI' : 'SELECT_INCIDENT_FIRST'}
          </span>
          <button onClick={handleSend} disabled={!selectedId || !text.trim()}>SEND</button>
          <button className="primary" onClick={handleAskCopilot} disabled={!selectedId || !text.trim() || isAsking}>
            QUERY_AI
          </button>
        </div>
      </div>
    </>
  )
}
