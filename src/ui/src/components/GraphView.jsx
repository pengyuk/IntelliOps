import { useEffect, useRef } from 'react'
import { useStore } from '../store'
import * as echarts from 'echarts'

export default function GraphView() {
  const kgGraph = useStore(s => s.kgGraph)
  const chartRef = useRef(null)
  const instanceRef = useRef(null)

  useEffect(() => {
    if (!chartRef.current) return
    if (!instanceRef.current) {
      instanceRef.current = echarts.init(chartRef.current, null, {
        devicePixelRatio: window.devicePixelRatio || 1,
        backgroundColor: 'transparent'
      })
    }
    const chart = instanceRef.current

    if (!kgGraph?.nodes?.length) {
      chart.clear()
      chart.setOption({
        graphic: {
          type: 'group', left: 'center', top: 'center',
          children: [
            { type: 'text', style: { text: '[ TOPOLOGY ]', fontSize: 13, fill: '#484868', fontFamily: 'Space Mono, monospace', fontWeight: 'bold' } },
            { type: 'text', top: 26, style: { text: 'Select incident to load', fontSize: 10, fill: '#686888', fontFamily: 'Space Mono, monospace' } }
          ]
        }
      })
      return
    }

    const typeColors = {
      Service: '#00d8ff', Alert: '#ff4060', Change: '#ffb020',
      Host: '#00f0a0', Database: '#a080ff', default: '#686888'
    }
    const nodes = kgGraph.nodes.map(n => ({
      id: n.id, name: n.name || n.id,
      symbolSize: n.type === 'Service' ? 26 : n.type === 'Alert' ? 20 : 16,
      itemStyle: {
        color: typeColors[n.type] || typeColors.default,
        borderColor: '#12121f',
        borderWidth: 2,
        shadowBlur: 6,
        shadowColor: typeColors[n.type] ? typeColors[n.type] + '44' : 'transparent'
      },
      label: { show: true, fontSize: 9, color: '#9898b8', fontFamily: 'Space Mono, monospace' }
    }))
    const edges = (kgGraph.edges || []).map(e => ({
      source: e.from, target: e.to,
      label: { show: !!e.rel, formatter: e.rel || '', fontSize: 8, color: '#686888', fontFamily: 'Space Mono, monospace' },
      lineStyle: { color: '#2a2a42', width: 1, curveness: 0.2 }
    }))

    chart.setOption({
      tooltip: {
        trigger: 'item',
        backgroundColor: '#12121f',
        borderColor: '#2a2a42',
        textStyle: { color: '#d4d4e8', fontSize: 11, fontFamily: 'Space Mono, monospace' },
        formatter: p => p.dataType === 'node'
          ? `<strong>${p.name}</strong><br/>Type: ${kgGraph.nodes.find(n => n.id === p.name)?.type || '--'}`
          : `${p.data.source} → ${p.data.target}`
      },
      animationDuration: 600,
      animationEasing: 'cubicOut',
      series: [{
        type: 'graph', layout: 'force', roam: true, draggable: true,
        force: { repulsion: 280, edgeLength: [100, 260], gravity: 0.08 },
        data: nodes, edges: edges,
        emphasis: {
          focus: 'adjacency',
          lineStyle: { width: 2, color: '#00d8ff' },
          itemStyle: { shadowBlur: 16, shadowColor: 'rgba(0,216,255,0.4)' }
        }
      }]
    })

    const handleResize = () => chart.resize()
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [kgGraph])

  return <div ref={chartRef} className="graph-container" />
}
