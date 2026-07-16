import { useQuery } from '@tanstack/react-query'
import { Card, Table, Tag, Typography } from 'antd'

import { api } from '../api/client'
import type { KnowledgeDocument } from '../api/types'

export default function KnowledgePage() {
  const query = useQuery({
    queryKey: ['knowledge-documents'],
    queryFn: () => api<KnowledgeDocument[]>('/api/v1/knowledge/documents'),
  })
  return <section>
    <div className="page-heading"><div><Typography.Text type="secondary">CONTROLLED KNOWLEDGE</Typography.Text><h2>知识中心</h2><p>厂内受控文档与引用章节；制造事实仍由 Data MCP 提供。</p></div><Tag color="cyan">{query.data?.length ?? 0} DOCUMENTS</Tag></div>
    <Card className="panel-card"><Table rowKey="source" loading={query.isLoading} dataSource={query.data ?? []} pagination={{ pageSize: 8 }} columns={[
      { title: '文档', dataIndex: 'title' },
      { title: '类型', dataIndex: 'doc_type', render: (value: string) => <Tag>{value}</Tag> },
      { title: '版本', dataIndex: 'version' },
      { title: '责任人', dataIndex: 'owner' },
      { title: '生效日期', dataIndex: 'effective_date' },
      { title: '章节', dataIndex: 'section_count', width: 80 },
    ]} /></Card>
  </section>
}
