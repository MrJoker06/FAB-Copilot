import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Card, Descriptions, Drawer, Spin, Table, Tag, Typography } from 'antd'
import { useSearchParams } from 'react-router-dom'

import { api } from '../api/client'
import type { HistoricalCase, HistoricalCaseDetail } from '../api/types'

const text = (value: string | null | undefined) => value?.trim() || '未记录'

export default function CasesPage() {
  const [params, setParams] = useSearchParams()
  const selectedCaseId = params.get('case') || undefined
  const query = useQuery({ queryKey: ['cases'], queryFn: () => api<HistoricalCase[]>('/api/v1/cases') })
  const detail = useQuery({
    queryKey: ['case-detail', selectedCaseId],
    queryFn: () => api<HistoricalCaseDetail>(`/api/v1/cases/${encodeURIComponent(selectedCaseId!)}`),
    enabled: Boolean(selectedCaseId),
  })
  const openCase = (caseId: string) => setParams({ case: caseId })
  const closeCase = () => {
    const next = new URLSearchParams(params)
    next.delete('case')
    setParams(next, { replace: true })
  }

  return <section>
    <div className="page-heading"><div><Typography.Text type="secondary">VALIDATED EVIDENCE</Typography.Text><h2>历史案例库</h2><p>案例只形成排查假设，不替代当前批次的工程验证。</p></div><Tag color="blue">VALIDATED ONLY</Tag></div>
    <Card className="panel-card"><Table rowKey="case_id" loading={query.isLoading} dataSource={query.data ?? []} pagination={{ pageSize: 8 }} columns={[
      { title: '案例', dataIndex: 'case_id', width: 130 },
      { title: '标题', dataIndex: 'title', render: (value: string, record: HistoricalCase) => <Button type="link" className="case-title-link" onClick={event => { event.stopPropagation(); openCase(record.case_id) }}>{value}</Button> },
      { title: '站点', dataIndex: 'process_step', render: (value: string) => <Tag color="cyan">{value}</Tag> },
      { title: '设备', dataIndex: 'equipment_id' },
      { title: '日期', dataIndex: 'occurred_date' },
      { title: '严重度', dataIndex: 'severity' },
      { title: '复发状态', dataIndex: 'recurrence_status' },
    ]} onRow={record => ({
      className: 'case-table-row',
      role: 'button',
      tabIndex: 0,
      'aria-label': `查看案例 ${record.case_id} ${record.title}`,
      onClick: () => openCase(record.case_id),
      onKeyDown: event => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          openCase(record.case_id)
        }
      },
    })} /></Card>

    <Drawer
      className="case-detail-drawer"
      width={640}
      open={Boolean(selectedCaseId)}
      onClose={closeCase}
      title={selectedCaseId ? `历史案例 · ${selectedCaseId}` : '历史案例'}
    >
      {detail.isLoading && <div className="case-detail-loading"><Spin /> 正在加载案例详情…</div>}
      {detail.isError && <Alert type="error" showIcon message="案例详情加载失败" description="请确认案例仍处于已验证状态后重试。" />}
      {detail.data && <article className="case-detail">
        <header>
          <div className="case-detail-tags"><Tag color="blue">{detail.data.case_status}</Tag><Tag color="cyan">{detail.data.process_step}</Tag><Tag color="orange">{detail.data.severity}</Tag></div>
          <h2>{detail.data.title}</h2>
          <p>{text(detail.data.summary)}</p>
        </header>
        <Descriptions bordered size="small" column={2}>
          <Descriptions.Item label="发生日期">{detail.data.occurred_date}</Descriptions.Item>
          <Descriptions.Item label="设备">{detail.data.equipment_id}</Descriptions.Item>
          <Descriptions.Item label="设备族">{text(detail.data.equipment_family)}</Descriptions.Item>
          <Descriptions.Item label="缺陷类型">{text(detail.data.defect_type)}</Descriptions.Item>
          <Descriptions.Item label="根因置信度">{detail.data.root_cause_confidence}</Descriptions.Item>
          <Descriptions.Item label="复发状态">{detail.data.recurrence_status}</Descriptions.Item>
          <Descriptions.Item label="批准人">{text(detail.data.approved_by)}</Descriptions.Item>
          <Descriptions.Item label="标签">{text(detail.data.tags)}</Descriptions.Item>
        </Descriptions>
        <section><h3>问题描述</h3><p>{text(detail.data.problem)}</p></section>
        <section><h3>异常症状</h3><p>{text(detail.data.symptoms)}</p></section>
        <section><h3>已验证根因</h3><p>{text(detail.data.root_cause)}</p></section>
        <section><h3>处置方案</h3><p>{text(detail.data.solution)}</p></section>
        <section><h3>处理结果</h3><p>{text(detail.data.result)}</p></section>
        <section><h3>验证方法</h3><p>{text(detail.data.validation_method)}</p></section>
      </article>}
    </Drawer>
  </section>
}
