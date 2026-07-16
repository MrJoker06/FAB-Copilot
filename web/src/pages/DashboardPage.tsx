import { useQuery } from '@tanstack/react-query'
import { Card, Col, Empty, Row, Skeleton, Statistic, Table, Tag, Typography } from 'antd'
import ReactECharts from 'echarts-for-react'

import { api } from '../api/client'
import type { DashboardData, EquipmentHealth } from '../api/types'

export default function DashboardPage() {
  const dashboard = useQuery({ queryKey: ['dashboard'], queryFn: () => api<DashboardData>('/api/v1/reports/dashboard') })
  if (dashboard.isLoading) return <Skeleton active paragraph={{ rows: 12 }} />
  if (!dashboard.data) return <Empty description="制造总览暂不可用，请检查 Data MCP。" />
  const data = dashboard.data
  const kpis = [
    ['完成批次', data.overview.lots, 'lots'],
    ['综合良率', data.overview.yield_pct, '%'],
    ['平均周期', data.overview.avg_cycle_hours, 'h'],
    ['异常工序', data.overview.excursions, 'runs'],
  ] as const
  return (
    <section>
      <div className="page-heading"><div><Typography.Text type="secondary">MANUFACTURING OVERVIEW</Typography.Text><h2>制造总览</h2></div><span>{data.overview.start} — {data.overview.end}</span></div>
      <Row gutter={[16, 16]}>{kpis.map(([title, value, suffix]) => <Col xs={12} xl={6} key={title}><Card className="metric-card"><Statistic title={title} value={value} suffix={suffix} /></Card></Col>)}</Row>
      <Row gutter={[16, 16]} className="dashboard-grid">
        <Col xs={24} xl={15}><Card title="良率与周期趋势" className="panel-card"><ReactECharts option={{ tooltip:{trigger:'axis'}, legend:{data:['良率','周期']}, xAxis:{type:'category',data:data.yield_trend.map(item=>item.week)}, yAxis:[{type:'value',name:'良率 %'},{type:'value',name:'周期 h'}], series:[{name:'良率',type:'line',smooth:true,data:data.yield_trend.map(item=>item.yield_pct)},{name:'周期',type:'line',yAxisIndex:1,smooth:true,data:data.yield_trend.map(item=>item.cycle_time_hours)}] }} /></Card></Col>
        <Col xs={24} xl={9}><Card title="设备风险" className="panel-card"><Table<EquipmentHealth> rowKey="equipment_id" size="small" pagination={{pageSize:6}} dataSource={data.equipment} columns={[{title:'设备',dataIndex:'equipment_id'},{title:'异常',dataIndex:'excursions'},{title:'状态',dataIndex:'health',render:(value)=><Tag color={value==='Risk'?'red':value==='Watch'?'gold':'green'}>{value}</Tag>}]} /></Card></Col>
      </Row>
    </section>
  )
}
