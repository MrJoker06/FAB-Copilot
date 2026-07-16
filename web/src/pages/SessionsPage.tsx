import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button, Card, Popconfirm, Space, Table, Tag, Typography } from 'antd'

import { api } from '../api/client'
import type { SessionSummary } from '../api/types'

export default function SessionsPage() {
  const client = useQueryClient()
  const query = useQuery({ queryKey: ['sessions'], queryFn: () => api<SessionSummary[]>('/api/v1/sessions') })
  const archive = useMutation({
    mutationFn: (id: string) => api(`/api/v1/sessions/${id}`, { method: 'DELETE' }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['sessions'] }),
  })
  return <section>
    <div className="page-heading"><div><Typography.Text type="secondary">ANALYSIS MEMORY</Typography.Text><h2>历史会话</h2><p>会话数据归 API 应用域管理，与制造数据库保持独立。</p></div><Tag>{query.data?.length ?? 0} ACTIVE</Tag></div>
    <Card className="panel-card"><Table rowKey="session_id" loading={query.isLoading} dataSource={query.data ?? []} pagination={{ pageSize: 8 }} columns={[
      { title: '标题', dataIndex: 'title' },
      { title: '最近消息', dataIndex: 'last_message_preview', ellipsis: true },
      { title: '消息数', dataIndex: 'message_count', width: 90 },
      { title: '模型/模式', dataIndex: 'model', render: (value: string | null) => value || 'MCP router' },
      { title: '更新时间', dataIndex: 'updated_at' },
      { title: '操作', key: 'actions', render: (_, row: SessionSummary) => <Space><Popconfirm title="归档该会话？" onConfirm={() => archive.mutate(row.session_id)}><Button size="small">归档</Button></Popconfirm></Space> },
    ]} /></Card>
  </section>
}
