import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Input, Spin } from 'antd'
import ReactMarkdown from 'react-markdown'
import { useSearchParams } from 'react-router-dom'

import { api } from '../api/client'
import type { KnowledgeDocument, KnowledgePreview } from '../api/types'

export default function KnowledgePage() {
  const [search, setSearch] = useState('')
  const [params, setParams] = useSearchParams()
  const selectedId = Number(params.get('chunk')) || undefined
  const documents = useQuery({
    queryKey: ['knowledge-documents'],
    queryFn: () => api<KnowledgeDocument[]>('/api/v1/knowledge/documents'),
  })
  const preview = useQuery({
    queryKey: ['knowledge-preview', selectedId],
    queryFn: () => api<KnowledgePreview>(`/api/v1/knowledge/chunks/${selectedId}`),
    enabled: Boolean(selectedId),
  })
  const filtered = useMemo(() => (documents.data ?? []).filter(document =>
    `${document.title} ${document.source} ${document.sections}`.toLowerCase().includes(search.toLowerCase().trim())
  ), [documents.data, search])
  const openDocument = (chunkId: number) => setParams({ chunk: String(chunkId) })

  return <section>
    <div className="page-heading">
      <div><span className="eyebrow">CONTROLLED KNOWLEDGE</span><h2>知识中心</h2><p>厂内受控文档与引用章节；制造事实仍由 Data MCP 提供。</p></div>
      <div className="knowledge-search"><Input allowClear placeholder="筛选文档或章节" value={search} onChange={event => setSearch(event.target.value)} /><span>{filtered.length} 份文档</span></div>
    </div>
    <div className="knowledge-layout">
      <aside className="panel-card knowledge-index">
        <div className="knowledge-index-heading"><strong>文档目录</strong><small>按文档浏览章节</small></div>
        <div className="knowledge-document-list">
          {documents.isLoading && <div className="knowledge-empty"><Spin size="small" /> 正在加载文档…</div>}
          {!documents.isLoading && !filtered.length && <div className="knowledge-empty">没有匹配的文档</div>}
          {filtered.map(document => <button
            key={document.source}
            className={`knowledge-document${preview.data?.document.source === document.source ? ' active' : ''}`}
            title={document.sections}
            onClick={() => openDocument(document.first_chunk_id)}
          ><strong>{document.title}</strong><span>{document.doc_type} · v{document.version} · {document.section_count} 章</span></button>)}
        </div>
      </aside>
      <article className="panel-card knowledge-reader">
        {preview.isLoading && <div className="knowledge-empty reader"><Spin /> 正在加载文档正文…</div>}
        {!preview.isLoading && !preview.data && <div className="knowledge-empty reader"><strong>选择一份知识文档</strong><span>从左侧选择文档，或点击 Agent 回答中的知识来源。</span></div>}
        {preview.data && <>
          <header className="knowledge-reader-heading">
            <div><span className="eyebrow">{preview.data.document.source} · v{preview.data.document.version} · {preview.data.document.status}</span><h2>{preview.data.document.title}</h2><div className="knowledge-meta"><span>{preview.data.document.doc_type}</span><span>{preview.data.document.owner}</span><span>{preview.data.document.authority}</span><span>生效 {preview.data.document.effective_date}</span></div></div>
          </header>
          <div className="knowledge-content">
            {preview.data.chunks.map(chunk => <section key={chunk.chunk_id} id={`knowledge-chunk-${chunk.chunk_id}`} className={`knowledge-chunk${chunk.chunk_id === preview.data.selected_chunk_id ? ' target-chunk' : ''}`}>
              <h3>{chunk.section}</h3>
              <div className="markdown-content"><ReactMarkdown>{chunk.content}</ReactMarkdown></div>
            </section>)}
          </div>
        </>}
      </article>
    </div>
  </section>
}
