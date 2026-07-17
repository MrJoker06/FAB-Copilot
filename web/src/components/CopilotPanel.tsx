import { useEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Input, Spin } from 'antd'
import ReactMarkdown from 'react-markdown'

import { api } from '../api/client'
import type { ChatResult, KnowledgeSource, SessionDetail } from '../api/types'

interface Props {
  sessionId?: string
  onSessionChange: (sessionId?: string) => void
  onNewSession: () => Promise<void>
  onOpenHistory: () => void
  onOpenSource: (source: KnowledgeSource) => void
  onClose: () => void
}

const WIDTH_KEY = 'fabInsightCopilotWidth'
const DEFAULT_WIDTH = 380
const MIN_WIDTH = 320
const MAX_WIDTH = 640
const DRAFT_KEY = 'fabInsightChatDraft'

const toolLabels: Record<string, string> = {
  get_fab_overview: '查询工厂总览',
  get_yield_trend: '查询良率趋势',
  get_equipment_health: '查询设备健康',
  get_equipment_productivity: '查询设备生产状态',
  get_process_capability: '查询制程能力',
  get_defect_pareto: '查询缺陷 Pareto',
  get_recent_excursions: '查询近期异常',
  get_sensor_summary: '查询传感器摘要',
  search_knowledge: '检索知识与案例',
}

interface TraceItem { tool: string; status: string; rows: number | null; truncated?: boolean }

function metadataList<T>(metadata: Record<string, unknown>, key: string): T[] {
  return Array.isArray(metadata[key]) ? metadata[key] as T[] : []
}

function initialWidth() {
  const saved = Number(localStorage.getItem(WIDTH_KEY))
  return Number.isFinite(saved) && saved >= MIN_WIDTH ? saved : DEFAULT_WIDTH
}

export default function CopilotPanel({ sessionId, onSessionChange, onNewSession, onOpenHistory, onOpenSource, onClose }: Props) {
  const client = useQueryClient()
  const [message, setMessage] = useState(() => localStorage.getItem(DRAFT_KEY) || '')
  const [pendingQuestion, setPendingQuestion] = useState('')
  const [lastQuestion, setLastQuestion] = useState('')
  const [copiedMessageId, setCopiedMessageId] = useState<number>()
  const [width, setWidth] = useState(initialWidth)
  const drag = useRef<{ pointerId: number; startX: number; startWidth: number } | undefined>(undefined)
  const messagesEnd = useRef<HTMLDivElement>(null)
  const session = useQuery({
    queryKey: ['session', sessionId],
    queryFn: () => api<SessionDetail>(`/api/v1/sessions/${sessionId}`),
    enabled: Boolean(sessionId),
    retry: false,
  })
  const messages = session.data?.messages ?? []
  const chat = useMutation({
    mutationFn: (text: string) => api<ChatResult>('/api/v1/chat', {
      method: 'POST',
      body: JSON.stringify({ message: text, session_id: sessionId }),
    }),
    onMutate: text => { setPendingQuestion(text); setLastQuestion(text) },
    onSuccess: async result => {
      onSessionChange(result.session_id)
      setMessage('')
      localStorage.removeItem(DRAFT_KEY)
      await Promise.all([
        client.invalidateQueries({ queryKey: ['session', result.session_id] }),
        client.invalidateQueries({ queryKey: ['sessions'] }),
      ])
    },
    onSettled: () => setPendingQuestion(''),
  })
  const newSession = useMutation({
    mutationFn: onNewSession,
    onSuccess: () => {
      setMessage('')
      setLastQuestion('')
      localStorage.removeItem(DRAFT_KEY)
    },
  })
  const submit = (value: string) => {
    const text = value.trim()
    if (text && !chat.isPending) chat.mutate(text)
  }

  const widthBounds = () => {
    if (window.innerWidth <= 1100) return { min: MIN_WIDTH, max: MAX_WIDTH }
    return {
      min: MIN_WIDTH,
      max: Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, window.innerWidth - 158 - 600)),
    }
  }
  const updateWidth = (next: number, persist = false) => {
    const bounds = widthBounds()
    const clamped = Math.round(Math.min(bounds.max, Math.max(bounds.min, next)))
    setWidth(clamped)
    if (persist) localStorage.setItem(WIDTH_KEY, String(clamped))
  }
  const finishResize = (event: PointerEvent<HTMLDivElement>) => {
    if (!drag.current || event.pointerId !== drag.current.pointerId) return
    const finalWidth = drag.current.startWidth + drag.current.startX - event.clientX
    event.currentTarget.releasePointerCapture?.(event.pointerId)
    drag.current = undefined
    document.body.classList.remove('copilot-resizing')
    updateWidth(finalWidth, true)
  }
  const resizeByKeyboard = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
    const bounds = widthBounds()
    const next = event.key === 'Home' ? bounds.min
      : event.key === 'End' ? bounds.max
        : width + (event.key === 'ArrowLeft' ? 20 : -20)
    updateWidth(next, true)
    event.preventDefault()
  }
  useEffect(() => {
    const clamp = () => setWidth(current => {
      if (window.innerWidth <= 1100) return current
      const max = Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, window.innerWidth - 158 - 600))
      return Math.round(Math.min(max, Math.max(MIN_WIDTH, current)))
    })
    window.addEventListener('resize', clamp)
    return () => window.removeEventListener('resize', clamp)
  }, [])
  useEffect(() => {
    messagesEnd.current?.scrollIntoView?.({ block: 'end' })
  }, [messages.length, pendingQuestion, chat.isPending])

  const style = { '--copilot-width': `${width}px` } as CSSProperties
  return (
    <aside className="copilot-panel" style={style}>
      <div
        className="copilot-resize-handle"
        role="separator"
        aria-label="调整分析助手宽度"
        aria-orientation="vertical"
        aria-valuemin={widthBounds().min}
        aria-valuemax={widthBounds().max}
        aria-valuenow={width}
        tabIndex={0}
        onPointerDown={event => {
          if (event.button !== 0 || window.innerWidth <= 1100) return
          drag.current = { pointerId: event.pointerId, startX: event.clientX, startWidth: width }
          event.currentTarget.setPointerCapture?.(event.pointerId)
          document.body.classList.add('copilot-resizing')
          event.preventDefault()
        }}
        onPointerMove={event => {
          if (!drag.current || event.pointerId !== drag.current.pointerId) return
          updateWidth(drag.current.startWidth + drag.current.startX - event.clientX)
        }}
        onPointerUp={finishResize}
        onPointerCancel={finishResize}
        onDoubleClick={() => { localStorage.removeItem(WIDTH_KEY); updateWidth(DEFAULT_WIDTH) }}
        onKeyDown={resizeByKeyboard}
      />
      <div className="copilot-heading">
        <span className="copilot-icon">◇</span>
        <div className="copilot-title"><strong>Fab Copilot</strong><small>{session.data ? `已恢复 · ${messages.length} 条消息` : '数据分析助手'}</small></div>
        <button className="session-history-button" onClick={onOpenHistory}><span>◷</span><span>历史会话</span></button>
        <button className="icon-btn" disabled={newSession.isPending} onClick={() => newSession.mutate()} aria-label="新建会话" title="新建会话">＋</button>
        <button className="icon-btn" onClick={onClose} aria-label="收起分析助手" title="收起分析助手">›</button>
      </div>
      <div className="copilot-messages">
        {session.isLoading && <div className="copilot-loading"><Spin /></div>}
        {session.isError && <Alert type="error" showIcon title="无法恢复历史会话" description={session.error.message} />}
        {!session.isLoading && !messages.length && !pendingQuestion && <>
          <article className="message assistant welcome-message">
            <div className="message-meta"><strong className="message-label">FAB COPILOT</strong></div>
            <div className="message-content">我可以帮你查看制造总览和趋势、分析设备与工序异常、评估制程能力、查找知识文档和历史案例，并整理可能原因与待验证项。</div>
          </article>
          <div className="suggestions">
            {['最近三个月哪些设备风险最高？', 'CVD-02 的膜厚是否发生漂移？', '分析刻蚀设备 CD 偏移的潜在原因'].map(prompt => <button key={prompt} onClick={() => submit(prompt)}>{prompt}</button>)}
          </div>
        </>}
        {messages.map(item => <article key={item.message_id} className={`message ${item.role}`}>
          <div className="message-meta"><strong className="message-label">{item.role === 'assistant' ? 'FAB COPILOT' : '你'}</strong></div>
          {item.role === 'assistant' && metadataList<TraceItem>(item.metadata, 'tool_trace').length > 0 && <details className="analysis-trace">
            <summary><span>执行路径已完成 · {metadataList<TraceItem>(item.metadata, 'tool_trace').length} 个工具</span><small>可展开</small></summary>
            <ol>{metadataList<TraceItem>(item.metadata, 'tool_trace').map((trace, index) => <li key={`${trace.tool}-${index}`}><span>{index + 1}. {toolLabels[trace.tool] || trace.tool}</span><small>{trace.status === 'success' ? '完成' : trace.status}{trace.rows == null ? '' : ` · ${trace.rows} 条结果`}</small></li>)}</ol>
          </details>}
          <div className={`message-content${item.role === 'assistant' ? ' markdown-content' : ''}`}>{item.role === 'assistant' ? <ReactMarkdown>{item.content}</ReactMarkdown> : item.content}</div>
          {item.role === 'assistant' && metadataList<KnowledgeSource>(item.metadata, 'sources').length > 0 && <div className="source-list"><strong>知识来源</strong>{metadataList<KnowledgeSource>(item.metadata, 'sources').map(source => <button key={source.reference_id} onClick={() => onOpenSource(source)}>[来源 {source.reference_id}] {source.source} · {source.section}</button>)}</div>}
          {item.role === 'assistant' && <div className="message-actions"><button className="copy-answer" onClick={async () => { await navigator.clipboard.writeText(item.content); setCopiedMessageId(item.message_id); window.setTimeout(() => setCopiedMessageId(undefined), 1600) }}><span>{copiedMessageId === item.message_id ? '✓' : '⧉'}</span><span>{copiedMessageId === item.message_id ? '已复制' : '复制'}</span></button></div>}
        </article>)}
        {pendingQuestion && <article className="message user pending"><div className="message-meta"><strong className="message-label">你</strong></div><div className="message-content">{pendingQuestion}</div></article>}
        {chat.isPending && <div className="assistant-thinking"><Spin size="small" /> 正在分析问题并整理证据…</div>}
        {chat.isError && <Alert type="error" showIcon title="分析请求未完成" description={<><span>{chat.error.message}</span><Button size="small" onClick={() => submit(lastQuestion)}>重试</Button></>} />}
        <div ref={messagesEnd} />
      </div>
      <div className="chat-form">
        <Input.TextArea
          value={message}
          onChange={event => {
            setMessage(event.target.value)
            if (event.target.value) localStorage.setItem(DRAFT_KEY, event.target.value)
            else localStorage.removeItem(DRAFT_KEY)
          }}
          onPressEnter={event => {
            if (!event.shiftKey && message.trim() && !chat.isPending) {
              event.preventDefault()
              submit(message)
            }
          }}
          placeholder="例如：最近 30 天 CVD-02 的能力变化与可能原因"
          autoSize={{ minRows: 3, maxRows: 7 }}
        />
        <div className="chat-actions">
          <span>基于历史数据库与厂内知识</span>
          <Button className="send-btn" type="primary" loading={chat.isPending} disabled={!message.trim()} onClick={() => submit(message)}>发送</Button>
        </div>
      </div>
    </aside>
  )
}
