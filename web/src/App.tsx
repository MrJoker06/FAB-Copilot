import { lazy, Suspense, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Layout, Menu, Spin } from 'antd'
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'

import { api } from './api/client'
import type { CurrentModelView } from './api/types'
import CopilotPanel from './components/CopilotPanel'
const AdminPage = lazy(() => import('./pages/AdminPage'))
const DashboardPage = lazy(() => import('./pages/DashboardPage'))
const CapabilityPage = lazy(() => import('./pages/CapabilityPage'))
const KnowledgePage = lazy(() => import('./pages/KnowledgePage'))
const CasesPage = lazy(() => import('./pages/CasesPage'))
const SessionsPage = lazy(() => import('./pages/SessionsPage'))

const { Header, Sider, Content } = Layout

const navigation = [
  { key: '/dashboard', icon: <span>▦</span>, label: '制造总览' },
  { key: '/capability', icon: <span>◎</span>, label: '制程能力' },
  { key: '/knowledge', icon: <span>▤</span>, label: '知识库' },
  { key: '/cases', icon: <span>▥</span>, label: '案例库' },
]

export default function App() {
  const location = useLocation()
  if (location.pathname.startsWith('/admin')) {
    return <Suspense fallback={<div className="route-loading"><Spin size="large" /></div>}><AdminPage /></Suspense>
  }
  return <UserWorkspace />
}

function UserWorkspace() {
  const location = useLocation()
  const navigate = useNavigate()
  const [copilotOpen, setCopilotOpen] = useState(true)
  const [activeSessionId, setActiveSessionId] = useState<string | undefined>(() => localStorage.getItem('fabInsightSessionId') || undefined)
  const modelConfig = useQuery({
    queryKey: ['current-model'],
    queryFn: () => api<CurrentModelView>('/api/v1/settings/model/current'),
    staleTime: 60_000,
  })
  const currentModel = modelConfig.data?.model ?? (modelConfig.isError ? '暂不可用' : '加载中…')
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
          <span className="system-status">当前模型：<strong>{currentModel}</strong></span>
          <button className="mobile-agent-toggle" onClick={() => setCopilotOpen(!copilotOpen)} aria-label={copilotOpen ? '隐藏分析助手' : '显示分析助手'}>◇</button>
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
              <Route path="*" element={<Navigate to="/dashboard" replace />} />
            </Routes></Suspense>
          </Content>
          {copilotOpen && <CopilotPanel sessionId={activeSessionId} onSessionChange={selectSession} onNewSession={startNewSession} onOpenHistory={() => navigate('/sessions')} onOpenSource={source => navigate(source.source_type === 'case' ? `/cases?case=${encodeURIComponent(source.case_id || source.reference_id)}` : `/knowledge?chunk=${source.chunk_id}`)} onClose={() => setCopilotOpen(false)} />}
        </Layout>
      </Layout>
    </Layout>
  )
}
