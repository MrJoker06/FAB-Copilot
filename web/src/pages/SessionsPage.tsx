import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button, Card, Empty, Input, Modal, Popconfirm, Segmented, Space, Table, Tag, Typography } from 'antd'
import ReactMarkdown from 'react-markdown'

import { api } from '../api/client'
import type { SessionDetail, SessionSummary } from '../api/types'

type SessionFilter = 'active' | 'archived' | 'all'

interface Props {
  activeSessionId?: string
  onContinueSession: (sessionId: string) => void
  onSessionUnavailable: (sessionId: string) => void
}

export default function SessionsPage({ activeSessionId, onContinueSession, onSessionUnavailable }: Props) {
  const client = useQueryClient()
  const [filter, setFilter] = useState<SessionFilter>('active')
  const [search, setSearch] = useState('')
  const [selectedId, setSelectedId] = useState<string>()
  const query = useQuery({
    queryKey: ['sessions', search],
    queryFn: () => api<SessionSummary[]>(`/api/v1/sessions?include_archived=true&limit=200&query=${encodeURIComponent(search)}`),
  })
  const detail = useQuery({
    queryKey: ['session', selectedId],
    queryFn: () => api<SessionDetail>(`/api/v1/sessions/${selectedId}`),
    enabled: Boolean(selectedId),
  })
  const refresh = () => client.invalidateQueries({ queryKey: ['sessions'] })
  const archive = useMutation({
    mutationFn: (id: string) => api(`/api/v1/sessions/${id}`, { method: 'DELETE' }),
    onSuccess: (_, id) => { if (id === activeSessionId) onSessionUnavailable(id); refresh() },
  })
  const restore = useMutation({
    mutationFn: (id: string) => api(`/api/v1/sessions/${id}/restore`, { method: 'POST' }),
    onSuccess: (_, id) => {
      client.invalidateQueries({ queryKey: ['session', id] })
      refresh()
    },
  })
  const remove = useMutation({
    mutationFn: (id: string) => api(`/api/v1/sessions/${id}/permanent`, { method: 'DELETE' }),
    onSuccess: (_, id) => {
      if (id === activeSessionId) onSessionUnavailable(id)
      if (id === selectedId) setSelectedId(undefined)
      refresh()
    },
  })
  const rows = useMemo(() => (query.data ?? []).filter(item => {
    if (filter === 'active') return !item.archived_at
    if (filter === 'archived') return Boolean(item.archived_at)
    return true
  }), [filter, query.data])
  const archivedCount = (query.data ?? []).filter(item => item.archived_at).length
  const continueSession = async (row: SessionSummary | SessionDetail) => {
    if (row.archived_at) await restore.mutateAsync(row.session_id)
    onContinueSession(row.session_id)
    setSelectedId(undefined)
  }

  return <section>
    <div className="page-heading"><div><Typography.Text type="secondary">ANALYSIS MEMORY</Typography.Text><h2>历史会话</h2><p>恢复上下文继续分析；归档会话可在独立入口中恢复。</p></div><Space><Tag>{rows.length} RESULTS</Tag><Tag color="gold">{archivedCount} ARCHIVED</Tag></Space></div>
    <Card className="panel-card sessions-panel-v1">
      <div className="sessions-toolbar">
        <Segmented value={filter} onChange={value => setFilter(value as SessionFilter)} options={[
          { label: '活跃会话', value: 'active' },
          { label: `已归档 ${archivedCount}`, value: 'archived' },
          { label: '全部', value: 'all' },
        ]} />
        <Input.Search allowClear placeholder="搜索标题或最近消息" onSearch={setSearch} onChange={event => { if (!event.target.value) setSearch('') }} />
      </div>
      <Table<SessionSummary> rowKey="session_id" loading={query.isLoading} dataSource={rows} pagination={{ pageSize: 10 }} locale={{ emptyText: <Empty description={filter === 'archived' ? '暂无已归档会话' : '暂无历史会话'} /> }} columns={[
        { title: '标题', dataIndex: 'title', render: (value: string, row) => <Button type="link" className="session-title-button" onClick={() => setSelectedId(row.session_id)}>{value}</Button> },
        { title: '最近消息', dataIndex: 'last_message_preview', ellipsis: true },
        { title: '消息', dataIndex: 'message_count', width: 66 },
        { title: '模型/模式', dataIndex: 'model', width: 145, render: (value: string | null) => value || 'local-rules' },
        { title: '状态', dataIndex: 'archived_at', width: 76, render: (value: string | null) => value ? <Tag>已归档</Tag> : <Tag color="green">活跃</Tag> },
        { title: '更新时间', dataIndex: 'updated_at', width: 180, render: (value: string) => new Date(value).toLocaleString('zh-CN', { hour12: false }) },
        { title: '操作', key: 'actions', width: 220, render: (_, row) => <Space size={4}>
          <Button size="small" type="primary" ghost onClick={() => continueSession(row)}>{row.archived_at ? '恢复并继续' : '继续'}</Button>
          {row.archived_at
            ? <Button size="small" onClick={() => restore.mutate(row.session_id)}>恢复</Button>
            : <Popconfirm title="归档该会话？" onConfirm={() => archive.mutate(row.session_id)}><Button size="small">归档</Button></Popconfirm>}
          <Popconfirm title="永久删除该会话及全部消息？" onConfirm={() => remove.mutate(row.session_id)}><Button danger size="small">删除</Button></Popconfirm>
        </Space> },
      ]} />
    </Card>
    <Modal
      width={760}
      title={detail.data?.title || '会话详情'}
      open={Boolean(selectedId)}
      onCancel={() => setSelectedId(undefined)}
      footer={detail.data ? <Space>
        <Button onClick={() => setSelectedId(undefined)}>关闭</Button>
        <Button type="primary" onClick={() => continueSession(detail.data!)}>{detail.data.archived_at ? '恢复并继续' : '在助手中继续'}</Button>
      </Space> : null}
    >
      <div className="session-preview-meta">{detail.data && <><Tag>{detail.data.archived_at ? '已归档' : '活跃'}</Tag><Tag>{detail.data.model || 'local-rules'}</Tag><span>{detail.data.messages.length} 条消息</span></>}</div>
      <div className="session-preview-messages">
        {detail.isLoading && <Typography.Text type="secondary">正在加载会话…</Typography.Text>}
        {detail.data?.messages.map(item => <article key={item.message_id} className={`session-preview-message ${item.role}`}>
          <strong>{item.role === 'assistant' ? 'FAB COPILOT' : '你'}</strong>
          <div>{item.role === 'assistant' ? <ReactMarkdown>{item.content}</ReactMarkdown> : item.content}</div>
        </article>)}
      </div>
    </Modal>
  </section>
}
