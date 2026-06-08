import { useEffect, useRef } from 'react'
import { useStore } from '../store'

export function useWebSocket(incidentId) {
  const wsRef = useRef(null)
  const refreshAll = useStore(s => s.refreshAll)

  useEffect(() => {
    if (!incidentId) return
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${location.host}/api/ws/incident/${incidentId}`
    
    const ws = new WebSocket(wsUrl)
    wsRef.current = ws

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        if (data.type === 'timeline' || data.type === 'diagnosis') {
          refreshAll()
        }
      } catch {}
    }

    ws.onclose = () => { wsRef.current = null }

    return () => {
      if (wsRef.current) wsRef.current.close()
    }
  }, [incidentId])
}
