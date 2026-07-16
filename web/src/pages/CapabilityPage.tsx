import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Card, Select, Skeleton, Table, Tag, Typography } from 'antd'

import { api } from '../api/client'
import type { CapabilityRow } from '../api/types'

const steps = ['LITHO','ETCH','CVD','PVD','DIFFUSION','IMPLANT','CMP','CLEAN','METROLOGY']

export default function CapabilityPage() {
  const [step, setStep] = useState('CVD')
  const query = useQuery({ queryKey:['capability',step], queryFn:()=>api<CapabilityRow[]>(`/api/v1/reports/capability?process_step=${step}`) })
  return <section><div className="page-heading"><div><Typography.Text type="secondary">PROCESS CAPABILITY</Typography.Text><h2>制程能力</h2></div><Select value={step} onChange={setStep} options={steps.map(value=>({value,label:value}))} /></div><Card className="panel-card">{query.isLoading?<Skeleton active/>:<Table<CapabilityRow> rowKey="equipment_id" dataSource={query.data} pagination={false} columns={[{title:'设备',dataIndex:'equipment_id'},{title:'量测',dataIndex:'metric_name'},{title:'样本',dataIndex:'samples'},{title:'均值',dataIndex:'mean_value'},{title:'σ',dataIndex:'sigma'},{title:'Cpk',dataIndex:'cpk',render:(value:number)=><Tag color={value<1.33?'red':value<1.67?'gold':'green'}>{value?.toFixed(2)}</Tag>}]} />}</Card></section>
}
