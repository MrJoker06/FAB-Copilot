import { lazy, Suspense, useState } from 'react'
import { Alert, Button, Layout, Menu, Space, Spin } from 'antd'
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'

import CopilotPanel from './components/CopilotPanel'
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
  { key: '/sessions', icon: <span>◫</span>, label: '历史会话' },
  { key: '/monitor', icon: <span>◉</span>, label: 'Agent 监控' },
]

export default function App() {
  const location = useLocation()
  const navigate = useNavigate()
  const [copilotOpen, setCopilotOpen] = useState(true)
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

  return (
    <Layout className="root-layout">
      <Header className="topbar">
        <div className="topbar-brand">
          <span className="topbar-brand-mark">FI</span>
          <div><strong>Fab Insight</strong><small>制造分析控制台</small></div>
        </div>
        <Space className="topbar-actions">
          <span className="system-status"><i />API 与 Data MCP 已连接</span>
          <Button className="agent-toggle" onClick={() => setCopilotOpen(!copilotOpen)}>
            <span>◇</span>{copilotOpen ? '隐藏分析助手' : '显示分析助手'}
          </Button>
        </Space>
      </Header>
      <Layout className="app-shell">
        <Sider width={158} breakpoint="xl" collapsedWidth={64} className="domain-sidebar">
          <Menu
            mode="inline"
            selectedKeys={[location.pathname]}
            items={navigation}
            onClick={({ key }) => navigate(key)}
          />
          <button className="sidebar-agent" onClick={() => setCopilotOpen(!copilotOpen)}><span>◇</span><span>分析助手</span></button>
          <div className="fab-tag"><strong>DEMO FAB</strong><small>历史数据 24 个月</small></div>
        </Sider>
        <Layout className="workspace-layout">
          <Content className="workspace-content">
            <Alert
              className="demo-notice"
              type="info"
              showIcon
              title="当前为可复现虚拟 FAB 数据，不代表真实量产规范。"
              closable
            />
            <Suspense fallback={<div className="route-loading"><Spin size="large" /></div>}><Routes>
              <Route path="/dashboard" element={<DashboardPage />} />
              <Route path="/capability" element={<CapabilityPage />} />
              <Route path="/knowledge" element={<KnowledgePage />} />
              <Route path="/cases" element={<CasesPage />} />
              <Route path="/sessions" element={<SessionsPage activeSessionId={activeSessionId} onContinueSession={continueSession} onSessionUnavailable={id => { if (id === activeSessionId) selectSession(undefined) }} />} />
              <Route path="/monitor" element={<MonitorPage />} />
              <Route path="*" element={<Navigate to="/dashboard" replace />} />
            </Routes></Suspense>
          </Content>
          {copilotOpen && <CopilotPanel sessionId={activeSessionId} onSessionChange={selectSession} onOpenHistory={() => navigate('/sessions')} onClose={() => setCopilotOpen(false)} />}
        </Layout>
      </Layout>
    </Layout>
  )
}
