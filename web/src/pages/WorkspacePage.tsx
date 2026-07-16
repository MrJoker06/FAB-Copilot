import { Card, Empty, Typography } from 'antd'

export default function WorkspacePage({ title, description }: { title: string; description: string }) {
  return <section><div className="page-heading"><div><Typography.Text type="secondary">FAB INSIGHT V2</Typography.Text><h2>{title}</h2><p>{description}</p></div></div><Card className="panel-card workspace-placeholder"><Empty description="该工作区正在接入 V2 领域 API；旧版功能在迁移完成前仍可使用。" /></Card></section>
}
