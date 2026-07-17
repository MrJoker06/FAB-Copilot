import { useEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Input, Spin } from 'antd'
import ReactMarkdown from 'react-markdown'

import { api } from '../api/client'
import type { ChatResult, SessionDetail } from '../api/types'

interface Props {
  sessionId?: string
  onSessionChange: (sessionId?: string) => void
  onOpenHistory: () => void
  onClose: () => void
}

const WIDTH_KEY = 'fabInsightCopilotWidth'
const DEFAULT_WIDTH = 380
const MIN_WIDTH = 320
const MAX_WIDTH = 640

function initialWidth() {
  const saved = Number(localStorage.getItem(WIDTH_KEY))
  return Number.isFinite(saved) && saved >= MIN_WIDTH ? saved : DEFAULT_WIDTH
}

export default function CopilotPanel({ sessionId, onSessionChange, onOpenHistory, onClose }: Props) {
  const client = useQueryClient()
  const [message, setMessage] = useState('')
  const [pendingQuestion, setPendingQuestion] = useState('')
  const [width, setWidth] = useState(initialWidth)
  const drag = useRef<{ pointerId: number; startX: number; startWidth: number } | undefined>(undefined)
  const session = useQuery({
    queryKey: ['session', sessionId],
    queryFn: () => api<SessionDetail>(`/api/v1/sessions/${sessionId}`),
    enabled: Boolean(sessionId),
    retry: false,
  })
  const chat = useMutation({
    mutationFn: (text: string) => api<ChatResult>('/api/v1/chat', {
      method: 'POST',
      body: JSON.stringify({ message: text, session_id: sessionId }),
    }),
    onMutate: text => setPendingQuestion(text),
    onSuccess: async result => {
      onSessionChange(result.session_id)
      setMessage('')
      await Promise.all([
        client.invalidateQueries({ queryKey: ['session', result.session_id] }),
        client.invalidateQueries({ queryKey: ['sessions'] }),
      ])
    },
    onSettled: () => setPendingQuestion(''),
  })

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

  const messages = session.data?.messages ?? []
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
        <div className="copilot-title"><strong>Fab Copilot</strong><small>{session.data ? `${session.data.title} · ${messages.length} 条消息` : '制造数据分析助手'}</small></div>
        <button className="session-history-button" onClick={onOpenHistory}><span>◷</span><span>历史会话</span></button>
        <button className="icon-btn" onClick={() => onSessionChange(undefined)} aria-label="新建会话" title="新建会话">＋</button>
        <button className="icon-btn" onClick={onClose} aria-label="收起分析助手" title="收起分析助手">›</button>
      </div>
      <div className="copilot-messages">
        {session.isLoading && <div className="copilot-loading"><Spin /></div>}
        {session.isError && <Alert type="error" showIcon title="无法恢复历史会话" description={session.error.message} />}
        {!session.isLoading && !messages.length && !pendingQuestion && <>
          <article className="message assistant welcome-message">
            <div className="message-meta"><strong className="message-label">FAB COPILOT</strong></div>
            <div className="message-content">可以从制造总览、制程能力、设备异常或历史案例开始分析。我会通过受控数据工具读取信息，并保留每轮分析上下文。</div>
          </article>
          <div className="suggestions">
            {['最近有哪些高风险异常？', '查看综合良率和周期趋势', '分析设备健康与停机风险'].map(prompt => <button key={prompt} onClick={() => setMessage(prompt)}>{prompt}</button>)}
          </div>
        </>}
        {messages.map(item => <article key={item.message_id} className={`message ${item.role}`}>
          <div className="message-meta"><strong className="message-label">{item.role === 'assistant' ? 'FAB COPILOT' : '你'}</strong></div>
          <div className={`message-content${item.role === 'assistant' ? ' markdown-content' : ''}`}>{item.role === 'assistant' ? <ReactMarkdown>{item.content}</ReactMarkdown> : item.content}</div>
        </article>)}
        {pendingQuestion && <article className="message user pending"><div className="message-meta"><strong className="message-label">你</strong></div><div className="message-content">{pendingQuestion}</div></article>}
        {chat.isPending && <div className="assistant-thinking"><Spin size="small" /> 正在分析并调用受控工具…</div>}
        {chat.isError && <Alert type="error" showIcon title="分析失败" description={chat.error.message} />}
      </div>
      <div className="chat-form">
        <Input.TextArea
          value={message}
          onChange={event => setMessage(event.target.value)}
          onPressEnter={event => {
            if (!event.shiftKey && message.trim() && !chat.isPending) {
              event.preventDefault()
              chat.mutate(message.trim())
            }
          }}
          placeholder="例如：最近 30 天 CVD-02 的能力变化与可能原因"
          autoSize={{ minRows: 3, maxRows: 7 }}
        />
        <div className="chat-actions">
          <span>基于历史数据库与厂内知识</span>
          <Button className="send-btn" type="primary" loading={chat.isPending} disabled={!message.trim()} onClick={() => chat.mutate(message.trim())}>发送</Button>
        </div>
      </div>
    </aside>
  )
}
