import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Card, Col, Input, Row, Select, Space, Statistic, Table, Tag } from 'antd'
import { Link } from 'react-router-dom'

import { api } from '../api/client'
import type { ModelConfigView, MonitorSummary } from '../api/types'

const ADMIN_TOKEN_KEY = 'fabInsightAdminToken'

export default function AdminPage() {
  const client = useQueryClient()
  const [token, setToken] = useState(() => sessionStorage.getItem(ADMIN_TOKEN_KEY) || '')
  const [tokenInput, setTokenInput] = useState('')
  const [model, setModel] = useState('')
  const [apiKey, setApiKey] = useState('')
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token])
  const modelConfig = useQuery({
    queryKey: ['admin-model-config', token],
    queryFn: () => api<ModelConfigView>('/api/v1/admin/settings/model', { headers }),
    enabled: Boolean(token),
    retry: false,
  })
  const monitor = useQuery({
    queryKey: ['admin-monitor', token],
    queryFn: () => api<MonitorSummary>('/api/v1/monitor/summary', { headers }),
    enabled: Boolean(token),
    retry: false,
  })
  const selectedModel = model || modelConfig.data?.model || ''
  const save = useMutation({
    mutationFn: () => api<ModelConfigView>('/api/v1/admin/settings/model', {
      method: 'POST',
      headers,
      body: JSON.stringify({ model: selectedModel, ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}) }),
    }),
    onSuccess: (result) => {
      client.setQueryData(['admin-model-config', token], result)
      client.setQueryData(['current-model'], { model: result.api_key_configured ? result.model : 'local-rules' })
      setApiKey('')
    },
  })
  const authenticate = () => {
    const value = tokenInput.trim()
    if (!value) return
    sessionStorage.setItem(ADMIN_TOKEN_KEY, value)
    setToken(value)
    setTokenInput('')
  }
  const logout = () => {
    sessionStorage.removeItem(ADMIN_TOKEN_KEY)
    setToken('')
    setModel('')
  }

  if (!token) return <main className="admin-login">
    <Card className="admin-login-card" title="Fab Insight 管理后台">
      <p>输入管理员令牌后管理运行模型和查看分析运行状态。</p>
      <Input.Password value={tokenInput} onChange={event => setTokenInput(event.target.value)} onPressEnter={authenticate} placeholder="管理员令牌" autoComplete="current-password" />
      <Button type="primary" block disabled={!tokenInput.trim()} onClick={authenticate}>进入管理后台</Button>
      <Link to="/dashboard">返回用户工作台</Link>
    </Card>
  </main>

  const unauthorized = modelConfig.isError || monitor.isError
  return <main className="admin-shell">
    <header className="admin-header">
      <div><span className="brand-mark">FI</span><div><strong>Fab Insight 管理后台</strong><small>模型配置与运行监控</small></div></div>
      <Space><Link to="/dashboard">用户工作台</Link><Button onClick={logout}>退出管理</Button></Space>
    </header>
    <section className="admin-content">
      {unauthorized && <Alert type="error" showIcon title="管理员认证失败" description="请检查 FAB_API_ADMIN_API_TOKEN 配置与输入的管理员令牌。" action={<Button onClick={logout}>重新认证</Button>} />}
      {!unauthorized && <>
        <div className="page-heading"><div><span className="eyebrow">ADMINISTRATION</span><h2>模型与运行管理</h2><p>普通用户只能使用这里提供的当前模型，无法修改配置。</p></div></div>
        <Row gutter={[16, 16]}>
          <Col xs={24} xl={10}>
            <Card title="模型配置" loading={modelConfig.isLoading} className="panel-card admin-model-card">
              <label>当前模型</label>
              <Select value={selectedModel || undefined} onChange={setModel} options={(modelConfig.data?.allowed_models ?? []).map(value => ({ value, label: value }))} />
              <label>更新 API Key（留空则保持当前配置）</label>
              <Input.Password value={apiKey} onChange={event => setApiKey(event.target.value)} placeholder={modelConfig.data?.api_key_configured ? `保持现有配置 ${modelConfig.data.api_key_masked}` : '输入模型 API Key'} autoComplete="new-password" />
              <Space wrap><Tag color={modelConfig.data?.api_key_configured ? 'green' : 'default'}>{modelConfig.data?.api_key_configured ? 'API Key 已配置' : '本地规则'}</Tag><Tag>{modelConfig.data?.api_key_source === 'runtime' ? '运行时配置' : '环境配置'}</Tag></Space>
              <Button type="primary" loading={save.isPending} disabled={!selectedModel} onClick={() => save.mutate()}>保存模型配置</Button>
              {save.isError && <Alert type="error" showIcon title="保存失败" description={save.error.message} />}
            </Card>
          </Col>
          <Col xs={24} xl={14}>
            <Card title="最近 24 小时" loading={monitor.isLoading} className="panel-card">
              <div className="admin-metrics">
                <Statistic title="分析运行" value={monitor.data?.runs ?? 0} />
                <Statistic title="成功率" value={monitor.data?.success_rate_pct ?? 0} suffix="%" />
                <Statistic title="分析调用" value={monitor.data?.tool_calls ?? 0} />
                <Statistic title="P95 延迟" value={monitor.data?.p95_duration_ms ?? 0} suffix="ms" />
              </div>
              <Table rowKey="tool" size="small" pagination={false} dataSource={monitor.data?.tool_usage ?? []} columns={[{ title: '分析能力', dataIndex: 'tool' }, { title: '调用次数', dataIndex: 'count' }]} />
            </Card>
          </Col>
        </Row>
      </>}
    </section>
  </main>
}
