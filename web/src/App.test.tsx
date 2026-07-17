import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

import App from './App'

vi.mock('echarts-for-react', () => ({ default: () => <div data-testid="chart" /> }))

const sessions = [
  {
    session_id: 'session-active', title: '已恢复会话', created_at: '2026-07-16T10:00:00Z', updated_at: '2026-07-17T10:00:00Z',
    model: 'deepseek-v4-flash', archived_at: null, last_message_preview: '继续分析 CVD', message_count: 2,
  },
  {
    session_id: 'session-archived', title: '已归档会话', created_at: '2026-07-15T10:00:00Z', updated_at: '2026-07-16T10:00:00Z',
    model: 'local-rules', archived_at: '2026-07-16T11:00:00Z', last_message_preview: '历史异常', message_count: 2,
  },
]

const jsonResponse = (data: unknown) => Promise.resolve({ ok: true, json: async () => ({ data, request_id: 'req-test0001' }) })

beforeEach(() => {
  localStorage.clear()
  Object.defineProperty(window, 'innerWidth', { value: 1440, configurable: true })
  vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    if (path.includes('/api/v1/knowledge/chunks/1')) return jsonResponse({
      selected_chunk_id: 1,
      document: { title: 'CVD 控制计划', source: 'CP-CVD-01', doc_type: 'Control Plan', version: '2.1', status: 'Active', effective_date: '2026-01-01', owner: 'Process Engineering', authority: 'Controlled', process_steps: 'CVD', tags: 'thickness' },
      chunks: [{ chunk_id: 1, title: 'CVD 控制计划', source: 'CP-CVD-01', section: '膜厚控制', content: '膜厚漂移时应先核对腔体状态。' }],
    })
    if (path.includes('/api/v1/knowledge/documents')) return jsonResponse([{ title: 'CVD 控制计划', source: 'CP-CVD-01', doc_type: 'Control Plan', version: '2.1', owner: 'Process Engineering', authority: 'Controlled', effective_date: '2026-01-01', section_count: 1, sections: '膜厚控制', first_chunk_id: 1 }])
    if (path.includes('/api/v1/chat') && init?.method === 'POST') return jsonResponse({ answer: '已完成分析。', mode: 'deterministic-mcp', session_id: 'session-active', message_id: 3, tool_trace: [], sources: [] })
    if (path.endsWith('/api/v1/sessions') && init?.method === 'POST') return jsonResponse({ session_id: 'session-new', title: '新会话' })
    if (path.includes('/api/v1/sessions/session-new')) return jsonResponse({ ...sessions[0], session_id: 'session-new', title: '新会话', messages: [] })
    if (path.includes('/api/v1/sessions/session-active')) return jsonResponse({ ...sessions[0], messages: [
      { message_id: 1, role: 'user', content: '介绍一下你自己', metadata: {}, created_at: '2026-07-17T09:00:00Z' },
      { message_id: 2, role: 'assistant', content: '我是 Fab Copilot。', metadata: {}, created_at: '2026-07-17T09:00:01Z' },
    ] })
    if (path.includes('/api/v1/sessions')) return jsonResponse(sessions)
    if (path.includes('/api/v1/settings/model')) return jsonResponse({ model: 'deepseek-v4-flash', allowed_models: ['deepseek-v4-flash', 'deepseek-v4-pro'], api_key_configured: true, api_key_masked: '••••1234', api_key_source: 'environment', persistence: 'process_memory' })
    return jsonResponse({ overview:{lots:2,wafers:50,yield_pct:91,avg_cycle_hours:88,avg_hold_hours:1,held_lots:1,excursions:1,start:'2026-07-01',end:'2026-07-17'}, yield_trend:[], equipment:[], defects:[], excursions:[] })
  }))
})

afterEach(() => cleanup())

function renderApp(path = '/dashboard') {
  return render(<QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={[path]}><App /></MemoryRouter></QueryClientProvider>)
}

test('renders the V1-style FAB shell and resizable Copilot', async () => {
  renderApp()
  expect(screen.getByText('Fab Insight')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /隐藏分析助手/ })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /模型设置/ })).toBeInTheDocument()
  expect(await screen.findByText('deepseek-v4-flash')).toBeInTheDocument()
  expect(screen.queryByText('API 与 Data MCP 已连接')).not.toBeInTheDocument()
  expect(screen.queryByText('当前为可复现虚拟 FAB 数据，不代表真实量产规范。')).not.toBeInTheDocument()
  expect(await screen.findByText('制造绩效总览')).toBeInTheDocument()
  expect(await screen.findByText('完成批次')).toBeInTheDocument()
  const resizeHandle = screen.getByRole('separator', { name: '调整分析助手宽度' })
  expect(resizeHandle).toHaveAttribute('aria-valuenow', '380')
  fireEvent.keyDown(resizeHandle, { key: 'ArrowLeft' })
  expect(resizeHandle).toHaveAttribute('aria-valuenow', '400')
  expect(localStorage.getItem('fabInsightCopilotWidth')).toBe('400')
})

test('shows the archived-session entrance and active-session continue action', async () => {
  renderApp('/sessions')
  expect(await screen.findByRole('heading', { name: '历史会话' })).toBeInTheDocument()
  expect(await screen.findByText('已归档 1')).toBeInTheDocument()
  expect(await screen.findByRole('button', { name: /已恢复会话/ })).toBeInTheDocument()
  expect(await screen.findByRole('button', { name: '在助手中继续' })).toBeInTheDocument()
  expect(await screen.findByText('我是 Fab Copilot。')).toBeInTheDocument()
})

test('opens model configuration from the V1 topbar entrance', async () => {
  renderApp()
  fireEvent.click(screen.getByRole('button', { name: /模型设置/ }))
  expect(await screen.findByRole('dialog')).toHaveTextContent('模型配置')
  expect(await screen.findByText('API Key 已配置')).toBeInTheDocument()
})

test('keeps the V1 assistant send and draft behavior', async () => {
  renderApp()
  expect(screen.getByText(/我可以帮你查看制造总览和趋势/)).toBeInTheDocument()
  expect(screen.queryByText(/受控数据工具/)).not.toBeInTheDocument()
  const input = screen.getByPlaceholderText('例如：最近 30 天 CVD-02 的能力变化与可能原因')
  fireEvent.change(input, { target: { value: '待继续分析的草稿' } })
  expect(localStorage.getItem('fabInsightChatDraft')).toBe('待继续分析的草稿')
  fireEvent.click(screen.getByRole('button', { name: 'CVD-02 的膜厚是否发生漂移？' }))
  await waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/v1/chat', expect.objectContaining({
    method: 'POST',
    body: expect.stringContaining('CVD-02 的膜厚是否发生漂移？'),
  })))
})

test('previews governed knowledge document content', async () => {
  renderApp('/knowledge')
  fireEvent.click(await screen.findByRole('button', { name: /CVD 控制计划/ }))
  expect(await screen.findByRole('heading', { name: '膜厚控制' })).toBeInTheDocument()
  expect(await screen.findByText('膜厚漂移时应先核对腔体状态。')).toBeInTheDocument()
})
