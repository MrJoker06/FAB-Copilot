import { useQuery } from '@tanstack/react-query'
import { Card, Table, Tag, Typography } from 'antd'

import { api } from '../api/client'
import type { HistoricalCase } from '../api/types'

export default function CasesPage() {
  const query = useQuery({ queryKey: ['cases'], queryFn: () => api<HistoricalCase[]>('/api/v1/cases') })
  return <section>
    <div className="page-heading"><div><Typography.Text type="secondary">VALIDATED EVIDENCE</Typography.Text><h2>历史案例库</h2><p>案例只形成排查假设，不替代当前批次的工程验证。</p></div><Tag color="blue">VALIDATED ONLY</Tag></div>
    <Card className="panel-card"><Table rowKey="case_id" loading={query.isLoading} dataSource={query.data ?? []} pagination={{ pageSize: 8 }} columns={[
      { title: '案例', dataIndex: 'case_id', width: 130 },
      { title: '标题', dataIndex: 'title' },
      { title: '站点', dataIndex: 'process_step', render: (value: string) => <Tag color="cyan">{value}</Tag> },
      { title: '设备', dataIndex: 'equipment_id' },
      { title: '日期', dataIndex: 'occurred_date' },
      { title: '严重度', dataIndex: 'severity' },
      { title: '复发状态', dataIndex: 'recurrence_status' },
    ]} /></Card>
  </section>
}
