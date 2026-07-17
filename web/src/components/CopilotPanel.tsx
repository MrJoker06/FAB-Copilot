import { useEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Empty, Input, Space, Spin, Tag } from 'antd'
import ReactMarkdown from 'react-markdown'

import { api } from '../api/client'
import type { ChatResult, SessionDetail } from '../api/types'
import ModelSettingsModal from './ModelSettingsModal'

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
  const [settingsOpen, setSettingsOpen] = useState(false)
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
        <Space size={2} className="copilot-actions">
          <Button type="text" onClick={() => onSessionChange(undefined)} aria-label="新建会话">＋</Button>
          <Button type="text" onClick={onOpenHistory} aria-label="历史会话">◫</Button>
          <Button type="text" onClick={() => setSettingsOpen(true)} aria-label="模型配置">⚙</Button>
          <Button type="text" onClick={onClose} aria-label="关闭 Copilot">×</Button>
        </Space>
      </div>
      <Space className="copilot-badges" wrap><Tag color="cyan">MCP</Tag><Tag color="blue">RAG</Tag><Tag>只读</Tag></Space>
      <div className="copilot-messages">
        {session.isLoading && <div className="copilot-loading"><Spin /></div>}
        {session.isError && <Alert type="error" showIcon title="无法恢复历史会话" description={session.error.message} />}
        {!session.isLoading && !messages.length && !pendingQuestion && <div className="copilot-empty"><Empty description="输入制造问题，或从历史会话继续分析。" image={Empty.PRESENTED_IMAGE_SIMPLE} /></div>}
        {messages.map(item => <article key={item.message_id} className={`chat-message ${item.role}`}>
          <strong>{item.role === 'assistant' ? 'FAB COPILOT' : '你'}</strong>
          <div>{item.role === 'assistant' ? <ReactMarkdown>{item.content}</ReactMarkdown> : item.content}</div>
        </article>)}
        {pendingQuestion && <article className="chat-message user pending"><strong>你</strong><div>{pendingQuestion}</div></article>}
        {chat.isPending && <div className="assistant-thinking"><Spin size="small" /> 正在分析并调用受控工具…</div>}
        {chat.isError && <Alert type="error" showIcon title="分析失败" description={chat.error.message} />}
      </div>
      <div className="copilot-composer">
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
        <Button type="primary" block loading={chat.isPending} disabled={!message.trim()} onClick={() => chat.mutate(message.trim())}>发送分析请求</Button>
      </div>
      <ModelSettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </aside>
  )
}
