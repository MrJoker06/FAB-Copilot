import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button, Input, Popconfirm, Segmented, Spin } from 'antd'
import ReactMarkdown from 'react-markdown'

import { api } from '../api/client'
import type { SessionDetail, SessionSummary } from '../api/types'

type SessionFilter = 'active' | 'archived' | 'all'

interface Props {
  activeSessionId?: string
  onContinueSession: (sessionId: string) => void
  onNewSession: () => void
  onSessionUnavailable: (sessionId: string) => void
}

const formatDate = (value: string) => new Date(value).toLocaleString('zh-CN', { hour12: false })

export default function SessionsPage({ activeSessionId, onContinueSession, onNewSession, onSessionUnavailable }: Props) {
  const client = useQueryClient()
  const [filter, setFilter] = useState<SessionFilter>('active')
  const [search, setSearch] = useState('')
  const [selectedId, setSelectedId] = useState<string>()
  const query = useQuery({
    queryKey: ['sessions', search],
    queryFn: () => api<SessionSummary[]>(`/api/v1/sessions?include_archived=true&limit=200&query=${encodeURIComponent(search)}`),
  })
  const rows = useMemo(() => (query.data ?? []).filter(item => {
    if (filter === 'active') return !item.archived_at
    if (filter === 'archived') return Boolean(item.archived_at)
    return true
  }), [filter, query.data])
  const effectiveSelectedId = rows.some(item => item.session_id === selectedId) ? selectedId : rows[0]?.session_id
  const detail = useQuery({
    queryKey: ['session', effectiveSelectedId],
    queryFn: () => api<SessionDetail>(`/api/v1/sessions/${effectiveSelectedId}`),
    enabled: Boolean(effectiveSelectedId),
  })
  const refresh = async (id?: string) => {
    await client.invalidateQueries({ queryKey: ['sessions'] })
    if (id) await client.invalidateQueries({ queryKey: ['session', id] })
  }
  const archive = useMutation({
    mutationFn: (id: string) => api(`/api/v1/sessions/${id}`, { method: 'DELETE' }),
    onSuccess: async (_, id) => {
      if (id === activeSessionId) onSessionUnavailable(id)
      await refresh(id)
    },
  })
  const restore = useMutation({
    mutationFn: (id: string) => api(`/api/v1/sessions/${id}/restore`, { method: 'POST' }),
    onSuccess: (_, id) => refresh(id),
  })
  const remove = useMutation({
    mutationFn: (id: string) => api(`/api/v1/sessions/${id}/permanent`, { method: 'DELETE' }),
    onSuccess: async (_, id) => {
      if (id === activeSessionId) onSessionUnavailable(id)
      if (id === selectedId) setSelectedId(undefined)
      await refresh()
    },
  })
  const archivedCount = (query.data ?? []).filter(item => item.archived_at).length
  const activeCount = (query.data ?? []).length - archivedCount
  const continueSession = async (row: SessionSummary | SessionDetail) => {
    if (row.archived_at) await restore.mutateAsync(row.session_id)
    onContinueSession(row.session_id)
  }
  const selected = detail.data

  return <section className="sessions-view">
    <div className="page-heading session-page-heading">
      <div className="session-page-title">
        <div><span className="eyebrow">CONVERSATION ARCHIVE</span><h2>历史会话</h2><p>集中检索、回看和继续 Fab Copilot 分析</p></div>
      </div>
      <div className="session-library-controls">
        <Input.Search allowClear placeholder="搜索标题或最近消息" onSearch={setSearch} onChange={event => { if (!event.target.value) setSearch('') }} />
        <Segmented className="session-filter" value={filter} onChange={value => setFilter(value as SessionFilter)} options={[
          { label: `活跃 ${activeCount}`, value: 'active' },
          { label: `已归档 ${archivedCount}`, value: 'archived' },
          { label: '全部', value: 'all' },
        ]} />
        <Button type="primary" onClick={onNewSession}>＋ 新建会话</Button>
      </div>
    </div>
    <div className="session-library-notice">
      {filter === 'archived' ? '已归档会话保留完整上下文，可恢复后继续分析。' : filter === 'active' ? '选择会话可查看完整分析记录，并在右侧助手中继续。' : '这里统一显示活跃与已归档的全部会话。'}
    </div>
    <div className="session-library-layout">
      <aside className="panel-card session-library-index">
        <div className="session-library-list">
          {query.isLoading && <div className="session-library-loading"><Spin size="small" /> 正在加载会话…</div>}
          {!query.isLoading && !rows.length && <div className="session-empty">{filter === 'archived' ? '暂无已归档会话' : '暂无历史会话'}</div>}
          {!!rows.length && <div className="session-library-group">
            <h3>{filter === 'archived' ? '已归档会话' : filter === 'active' ? '最近会话' : '全部会话'}</h3>
            {rows.map(row => <div key={row.session_id} className={`session-library-item${row.session_id === effectiveSelectedId ? ' active' : ''}`}>
              <button className="session-library-open" onClick={() => setSelectedId(row.session_id)}>
                <strong>{row.title}</strong>
                <span>{formatDate(row.updated_at)} · {row.message_count} 条消息</span>
                <small>{row.last_message_preview || '尚无消息'}</small>
              </button>
              <span className={`session-state${row.archived_at ? ' archived' : ''}`}>{row.archived_at ? '已归档' : '活跃'}</span>
            </div>)}
          </div>}
        </div>
      </aside>
      <article className="panel-card session-library-reader">
        {detail.isLoading && <div className="session-reader-empty"><Spin /> 正在加载会话…</div>}
        {!detail.isLoading && !selected && <div className="session-reader-empty"><strong>选择一个会话</strong><span>完整对话将在这里显示。</span></div>}
        {selected && <>
          <header className="session-library-reader-heading">
            <div className="session-reader-title">
              <h2>{selected.title}</h2>
              <div className="session-library-meta"><span>{selected.archived_at ? '已归档' : '活跃'}</span><span>{selected.model || 'local-rules'}</span><span>{selected.messages.length} 条消息</span><span>{formatDate(selected.updated_at)}</span></div>
            </div>
            <div className="session-library-actions">
              <Button type="primary" onClick={() => continueSession(selected)}>{selected.archived_at ? '恢复并继续' : '在助手中继续'}</Button>
              {selected.archived_at
                ? <Button onClick={() => restore.mutate(selected.session_id)}>恢复</Button>
                : <Popconfirm title="归档该会话？" onConfirm={() => archive.mutate(selected.session_id)}><Button>归档</Button></Popconfirm>}
              <Popconfirm title="永久删除该会话及全部消息？" onConfirm={() => remove.mutate(selected.session_id)}><Button danger>删除</Button></Popconfirm>
            </div>
          </header>
          <div className="session-library-messages">
            {selected.messages.map(item => <section key={item.message_id} className={`session-transcript-item ${item.role}`}>
              <div className="session-transcript-heading"><strong>{item.role === 'assistant' ? 'FAB COPILOT' : '你'}</strong><time>{formatDate(item.created_at)}</time></div>
              <div className="session-transcript-content markdown-content">{item.role === 'assistant' ? <ReactMarkdown>{item.content}</ReactMarkdown> : item.content}</div>
            </section>)}
          </div>
        </>}
      </article>
    </div>
  </section>
}
