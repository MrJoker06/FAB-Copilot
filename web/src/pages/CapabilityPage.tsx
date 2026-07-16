import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Card, Segmented, Skeleton, Table, Tag, Typography } from 'antd'

import { api } from '../api/client'
import type { CapabilityRow } from '../api/types'

const steps = [
  { label: '光刻', value: 'LITHO' },
  { label: '刻蚀', value: 'ETCH' },
  { label: 'CVD', value: 'CVD' },
  { label: 'PVD', value: 'PVD' },
  { label: '扩散', value: 'DIFFUSION' },
  { label: '注入', value: 'IMPLANT' },
  { label: 'CMP', value: 'CMP' },
  { label: '清洗', value: 'CLEAN' },
  { label: '量测', value: 'METROLOGY' },
]

export default function CapabilityPage() {
  const [step, setStep] = useState('CVD')
  const query = useQuery({ queryKey:['capability',step], queryFn:()=>api<CapabilityRow[]>(`/api/v1/reports/capability?process_step=${step}`) })
  return <section><div className="page-heading"><div><Typography.Text type="secondary">PROCESS CONTROL</Typography.Text><h2>制程能力分析</h2><p>按设备比较均值、变异与 Cpk</p></div><Segmented className="process-segmented" value={step} onChange={(value)=>setStep(String(value))} options={steps} /></div><Card title={<div><strong>{step} 制程能力</strong><small>关键量测规格与设备能力比较</small></div>} className="panel-card capability-panel-v1">{query.isLoading?<Skeleton active/>:<Table<CapabilityRow> rowKey="equipment_id" dataSource={query.data} pagination={false} columns={[{title:'设备',dataIndex:'equipment_id'},{title:'量测',dataIndex:'metric_name'},{title:'样本',dataIndex:'samples'},{title:'均值',dataIndex:'mean_value'},{title:'Sigma',dataIndex:'sigma'},{title:'Cpk',dataIndex:'cpk',render:(value:number)=><Tag color={value<1.33?'red':value<1.67?'gold':'green'}>{value?.toFixed(2)}</Tag>}]} />}</Card></section>
}
