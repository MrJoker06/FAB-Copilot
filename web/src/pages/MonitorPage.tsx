import { useQuery } from '@tanstack/react-query'
import { Card, Col, Row, Statistic, Table, Tag, Typography } from 'antd'

import { api } from '../api/client'
import type { MonitorSummary } from '../api/types'

export default function MonitorPage() {
  const query = useQuery({ queryKey: ['monitor'], queryFn: () => api<MonitorSummary>('/api/v1/monitor/summary') })
  const data = query.data
  return <section>
    <div className="page-heading"><div><Typography.Text type="secondary">OBSERVABILITY</Typography.Text><h2>Agent 监控</h2><p>模型、分析调用、成功率和错误类型的统一观察面。</p></div><Tag color="green">24H WINDOW</Tag></div>
    <Row gutter={[16,16]}>
      <Col span={6}><Card className="metric-card"><Statistic title="分析运行" value={data?.runs ?? 0} /></Card></Col>
      <Col span={6}><Card className="metric-card"><Statistic title="成功率" value={data?.success_rate_pct ?? 0} suffix="%" /></Card></Col>
      <Col span={6}><Card className="metric-card"><Statistic title="分析调用" value={data?.tool_calls ?? 0} /></Card></Col>
      <Col span={6}><Card className="metric-card"><Statistic title="P95 延迟" value={data?.p95_duration_ms ?? 0} suffix="ms" /></Card></Col>
      <Col span={24}><Card className="panel-card"><Table rowKey="tool" pagination={false} dataSource={data?.tool_usage ?? []} columns={[{title:'工具',dataIndex:'tool'},{title:'调用次数',dataIndex:'count'}]} /></Card></Col>
    </Row>
  </section>
}
