import { lazy, Suspense, useState } from 'react'
import { Alert, Badge, Button, Layout, Menu, Space, Spin, Typography } from 'antd'
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
  { key: '/dashboard', label: '制造总览' },
  { key: '/capability', label: '制程能力' },
  { key: '/knowledge', label: '知识中心' },
  { key: '/cases', label: '案例库' },
  { key: '/sessions', label: '历史会话' },
  { key: '/monitor', label: 'Agent 监控' },
]

export default function App() {
  const location = useLocation()
  const navigate = useNavigate()
  const [copilotOpen, setCopilotOpen] = useState(true)

  return (
    <Layout className="app-shell">
      <Sider width={220} breakpoint="lg" collapsedWidth={72} className="domain-sidebar">
        <div className="brand-mark">
          <span>FI</span>
          <div><strong>FAB INSIGHT</strong><small>V2 COMMAND</small></div>
        </div>
        <Menu
          mode="inline"
          selectedKeys={[location.pathname]}
          items={navigation}
          onClick={({ key }) => navigate(key)}
        />
        <div className="fab-tag"><Badge status="processing" /> DEMO FAB · 24M</div>
      </Sider>
      <Layout>
        <Header className="command-header">
          <div><Typography.Text type="secondary">FAB OPERATIONS</Typography.Text><h1>制造分析指挥台</h1></div>
          <Space>
            <Badge status="success" text="API" />
            <Badge status="processing" text="DATA MCP" />
            <Button type={copilotOpen ? 'primary' : 'default'} onClick={() => setCopilotOpen(!copilotOpen)}>
              Fab Copilot
            </Button>
          </Space>
        </Header>
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
              <Route path="/sessions" element={<SessionsPage />} />
              <Route path="/monitor" element={<MonitorPage />} />
              <Route path="*" element={<Navigate to="/dashboard" replace />} />
            </Routes></Suspense>
          </Content>
          {copilotOpen && <CopilotPanel onClose={() => setCopilotOpen(false)} />}
        </Layout>
      </Layout>
    </Layout>
  )
}
