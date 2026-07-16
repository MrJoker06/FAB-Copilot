import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Alert, Button, Empty, Input, Space, Tag, Typography } from 'antd'

import { api } from '../api/client'
import type { ChatResult } from '../api/types'

interface Props { onClose: () => void }

export default function CopilotPanel({ onClose }: Props) {
  const [message, setMessage] = useState('')
  const [sessionId, setSessionId] = useState<string>()
  const [answer, setAnswer] = useState('')
  const chat = useMutation({
    mutationFn: (text: string) => api<ChatResult>('/api/v1/chat', { method: 'POST', body: JSON.stringify({ message: text, session_id: sessionId }) }),
    onSuccess: (result) => { setSessionId(result.session_id); setAnswer(result.answer); setMessage('') },
  })
  return (
    <aside className="copilot-panel">
      <div className="copilot-heading">
        <div><Typography.Text type="secondary">ANALYSIS AGENT</Typography.Text><h2>Fab Copilot</h2></div>
        <Button type="text" onClick={onClose} aria-label="关闭 Copilot">×</Button>
      </div>
      <Space wrap><Tag color="cyan">MCP</Tag><Tag color="blue">RAG</Tag><Tag>只读</Tag></Space>
      <div className="copilot-messages">
        {chat.isError && <Alert type="error" showIcon title="分析失败" description={chat.error.message} />}
        {answer ? <div className="assistant-answer"><Typography.Paragraph>{answer}</Typography.Paragraph></div> : <Empty description="输入制造问题，Agent 将优先调用类型化 MCP 工具。" image={Empty.PRESENTED_IMAGE_SIMPLE} />}
      </div>
      <div className="copilot-composer">
        <Input.TextArea
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          placeholder="例如：最近 30 天 CVD-02 的能力变化与可能原因"
          autoSize={{ minRows: 3, maxRows: 7 }}
        />
        <Button type="primary" block loading={chat.isPending} disabled={!message.trim()} onClick={() => chat.mutate(message.trim())}>发送分析请求</Button>
      </div>
    </aside>
  )
}
