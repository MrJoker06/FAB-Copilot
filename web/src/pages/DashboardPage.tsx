import { useQuery } from '@tanstack/react-query'
import { Card, Empty, Skeleton, Statistic, Table, Tag, Typography } from 'antd'

import { api } from '../api/client'
import type { DashboardData, EquipmentHealth, YieldPoint } from '../api/types'

function TrendChart({ data }: { data: YieldPoint[] }) {
  const width = 720
  const height = 245
  const left = 48
  const right = 36
  const top = 20
  const bottom = 44
  const chartWidth = width - left - right
  const chartHeight = height - top - bottom
  const points = (values: number[]) => {
    const minimum = Math.min(...values)
    const maximum = Math.max(...values)
    const span = maximum - minimum || 1
    return values.map((value, index) => {
      const x = left + (data.length === 1 ? chartWidth / 2 : index / (data.length - 1) * chartWidth)
      const y = top + (1 - (value - minimum) / span) * chartHeight
      return `${x},${y}`
    }).join(' ')
  }
  if (!data.length) return <div className="trend-empty">暂无趋势数据</div>
  const yieldPoints = points(data.map(item => item.yield_pct))
  const cyclePoints = points(data.map(item => item.cycle_time_hours))
  return <div className="trend-chart" role="img" aria-label="综合良率与周期趋势图">
    <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
      {[0, 1, 2, 3, 4].map(index => {
        const y = top + index / 4 * chartHeight
        return <line key={index} x1={left} x2={width - right} y1={y} y2={y} className="trend-grid-line" />
      })}
      <polyline points={yieldPoints} className="trend-line yield" />
      <polyline points={cyclePoints} className="trend-line cycle" />
      {data.map((item, index) => {
        if (index % Math.max(1, Math.ceil(data.length / 6)) !== 0 && index !== data.length - 1) return null
        const x = left + (data.length === 1 ? chartWidth / 2 : index / (data.length - 1) * chartWidth)
        return <text key={item.week} x={x} y={height - 14} textAnchor="middle">{item.week}</text>
      })}
    </svg>
    <div className="trend-legend"><span><i className="yield" />良率</span><span><i className="cycle" />周期</span></div>
  </div>
}

export default function DashboardPage() {
  const dashboard = useQuery({ queryKey: ['dashboard'], queryFn: () => api<DashboardData>('/api/v1/reports/dashboard') })
  if (dashboard.isLoading) return <Skeleton active paragraph={{ rows: 12 }} />
  if (!dashboard.data) return <Empty description="制造总览暂不可用，请稍后重试。" />
  const data = dashboard.data
  const kpis = [
    ['完成批次', data.overview.lots, 'lots'],
    ['综合良率', data.overview.yield_pct, '%'],
    ['平均周期', data.overview.avg_cycle_hours, 'h'],
    ['Hold 批次', data.overview.held_lots, 'lots'],
    ['异常工序', data.overview.excursions, 'runs'],
  ] as const
  return (
    <section>
      <div className="page-heading"><div><Typography.Text type="secondary">FAB OPERATIONS</Typography.Text><h2>制造绩效总览</h2><p>{data.overview.start} — {data.overview.end}</p></div></div>
      <div className="kpi-grid-v1">{kpis.map(([title, value, suffix]) => <Card className="metric-card" key={title}><Statistic title={title} value={value} suffix={suffix} /></Card>)}</div>
      <div className="report-grid-v1">
        <Card title={<div><strong>周良率趋势</strong><small>综合良率与周期变化</small></div>} className="panel-card trend-panel-v1">
          <TrendChart data={data.yield_trend} />
        </Card>
        <Card title={<div><strong>缺陷 Pareto</strong><small>按缺陷数量排序</small></div>} className="panel-card defect-panel-v1">
          <div className="defect-list">{data.defects.slice(0,8).map((item) => {
            const maximum = Math.max(...data.defects.map(row => row.defect_count), 1)
            return <div className="defect-row" key={item.defect_type}><span>{item.defect_type}</span><i><b style={{width:`${item.defect_count / maximum * 100}%`}} /></i><em>{item.defect_count}</em></div>
          })}</div>
        </Card>
        <Card title={<div><strong>设备健康</strong><small>按异常与停机风险排序</small></div>} className="panel-card wide-panel-v1">
          <Table<EquipmentHealth> rowKey="equipment_id" size="small" pagination={{pageSize:6}} dataSource={data.equipment} columns={[{title:'设备',dataIndex:'equipment_id'},{title:'运行',dataIndex:'runs'},{title:'异常',dataIndex:'excursions'},{title:'停机小时',dataIndex:'downtime_hours'},{title:'状态',dataIndex:'health',render:(value)=><Tag color={value==='Risk'?'red':value==='Watch'?'gold':'green'}>{value}</Tag>}]} />
        </Card>
        <Card title={<div><strong>近期制程异常</strong><small>最新异常批次与设备</small></div>} className="panel-card wide-panel-v1">
          <Table<Record<string, unknown>> rowKey={(row) => String(row.run_id ?? `${row.lot_id}-${row.equipment_id}-${row.excursion_code}`)} size="small" pagination={false} dataSource={data.excursions.slice(0,8)} columns={[{title:'时间',render:(_,row)=>String(row.run_time ?? row.detected_time ?? '-')},{title:'批次',dataIndex:'lot_id'},{title:'站点',dataIndex:'process_step'},{title:'设备',dataIndex:'equipment_id'},{title:'异常码',dataIndex:'excursion_code',render:(value)=>value?<Tag color="red">{String(value)}</Tag>:'-'}]} />
        </Card>
      </div>
    </section>
  )
}
