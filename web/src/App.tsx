import { lazy, Suspense, useState } from 'react'
import { Layout, Menu, Spin } from 'antd'
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'

import CopilotPanel from './components/CopilotPanel'
import ModelSettingsModal from './components/ModelSettingsModal'
import { api } from './api/client'
const DashboardPage = lazy(() => import('./pages/DashboardPage'))
const CapabilityPage = lazy(() => import('./pages/CapabilityPage'))
const KnowledgePage = lazy(() => import('./pages/KnowledgePage'))
const CasesPage = lazy(() => import('./pages/CasesPage'))
const SessionsPage = lazy(() => import('./pages/SessionsPage'))
const MonitorPage = lazy(() => import('./pages/MonitorPage'))

const { Header, Sider, Content } = Layout

const navigation = [
  { key: '/dashboard', icon: <span>▦</span>, label: '制造总览' },
  { key: '/capability', icon: <span>◎</span>, label: '制程能力' },
  { key: '/knowledge', icon: <span>▤</span>, label: '知识库' },
  { key: '/cases', icon: <span>▥</span>, label: '案例库' },
  { key: '/monitor', icon: <span>◉</span>, label: 'Agent 监控' },
]

export default function App() {
  const location = useLocation()
  const navigate = useNavigate()
  const [copilotOpen, setCopilotOpen] = useState(true)
  const [modelSettingsOpen, setModelSettingsOpen] = useState(false)
  const [activeSessionId, setActiveSessionId] = useState<string | undefined>(() => localStorage.getItem('fabInsightSessionId') || undefined)
  const selectSession = (sessionId?: string) => {
    setActiveSessionId(sessionId)
    if (sessionId) localStorage.setItem('fabInsightSessionId', sessionId)
    else localStorage.removeItem('fabInsightSessionId')
  }
  const continueSession = (sessionId: string) => {
    selectSession(sessionId)
    setCopilotOpen(true)
  }
  const startNewSession = async () => {
    const session = await api<{ session_id: string }>('/api/v1/sessions', {
      method: 'POST',
      body: JSON.stringify({ title: '新会话' }),
    })
    selectSession(session.session_id)
    setCopilotOpen(true)
  }

  return (
    <Layout className="root-layout">
      <Header className="topbar">
        <div className="brand">
          <span className="brand-mark">FI</span>
          <div><strong>Fab Insight</strong><small>制造分析控制台</small></div>
        </div>
        <div className="topbar-actions">
          <span className="system-status"><i />API 与 Data MCP 已连接</span>
          <button className="mobile-agent-toggle" onClick={() => setCopilotOpen(!copilotOpen)} aria-label={copilotOpen ? '隐藏分析助手' : '显示分析助手'}>◇</button>
          <button className="model-settings-button" onClick={() => setModelSettingsOpen(true)}><span>⚙</span><span>模型设置</span></button>
        </div>
      </Header>
      <Layout className="app-shell">
        <Sider width={158} className="domain-sidebar">
          <Menu
            mode="inline"
            selectedKeys={[location.pathname]}
            items={navigation}
            onClick={({ key }) => navigate(key)}
          />
          <button className={`sidebar-agent${copilotOpen ? ' active' : ''}`} onClick={() => setCopilotOpen(!copilotOpen)}><span>◇</span><span>分析助手</span></button>
          <div className="fab-tag"><strong>DEMO FAB</strong><small>历史数据 24 个月</small></div>
        </Sider>
        <Layout className="workspace-layout">
          <Content className="workspace-content">
            <Suspense fallback={<div className="route-loading"><Spin size="large" /></div>}><Routes>
              <Route path="/dashboard" element={<DashboardPage />} />
              <Route path="/capability" element={<CapabilityPage />} />
              <Route path="/knowledge" element={<KnowledgePage />} />
              <Route path="/cases" element={<CasesPage />} />
              <Route path="/sessions" element={<SessionsPage activeSessionId={activeSessionId} onContinueSession={continueSession} onNewSession={startNewSession} onSessionUnavailable={id => { if (id === activeSessionId) selectSession(undefined) }} />} />
              <Route path="/monitor" element={<MonitorPage />} />
              <Route path="*" element={<Navigate to="/dashboard" replace />} />
            </Routes></Suspense>
          </Content>
          {copilotOpen && <CopilotPanel sessionId={activeSessionId} onSessionChange={selectSession} onNewSession={startNewSession} onOpenHistory={() => navigate('/sessions')} onOpenSource={source => navigate(source.source_type === 'case' ? `/cases?case=${encodeURIComponent(source.case_id || source.reference_id)}` : `/knowledge?chunk=${source.chunk_id}`)} onClose={() => setCopilotOpen(false)} />}
        </Layout>
      </Layout>
      <ModelSettingsModal open={modelSettingsOpen} onClose={() => setModelSettingsOpen(false)} />
    </Layout>
  )
}
