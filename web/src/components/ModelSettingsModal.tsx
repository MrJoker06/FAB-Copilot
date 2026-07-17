import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Input, Modal, Select, Space, Tag, Typography } from 'antd'

import { api } from '../api/client'
import type { ModelConfigView } from '../api/types'

interface Props {
  open: boolean
  onClose: () => void
}

export default function ModelSettingsModal({ open, onClose }: Props) {
  const client = useQueryClient()
  const [model, setModel] = useState('')
  const [apiKey, setApiKey] = useState('')
  const query = useQuery({
    queryKey: ['model-config'],
    queryFn: () => api<ModelConfigView>('/api/v1/settings/model'),
    enabled: open,
  })
  const selectedModel = model || query.data?.model || ''
  const save = useMutation({
    mutationFn: () => api<ModelConfigView>('/api/v1/settings/model', {
      method: 'POST',
      body: JSON.stringify({ model: selectedModel, ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}) }),
    }),
    onSuccess: (result) => {
      client.setQueryData(['model-config'], result)
      setApiKey('')
      onClose()
    },
  })

  return <Modal
    title="模型配置"
    open={open}
    onCancel={onClose}
    onOk={() => save.mutate()}
    okText="保存配置"
    cancelText="取消"
    confirmLoading={save.isPending}
    okButtonProps={{ disabled: !selectedModel || query.isLoading }}
  >
    <div className="model-settings-form">
      <Typography.Text type="secondary">运行时模型</Typography.Text>
      <Select
        value={selectedModel || undefined}
        loading={query.isLoading}
        onChange={setModel}
        options={(query.data?.allowed_models ?? []).map(value => ({ value, label: value }))}
      />
      <Typography.Text type="secondary">API Key</Typography.Text>
      <Input.Password
        value={apiKey}
        onChange={event => setApiKey(event.target.value)}
        placeholder={query.data?.api_key_configured ? `保持现有配置 ${query.data.api_key_masked}` : '输入 DeepSeek API Key'}
        autoComplete="new-password"
      />
      {query.data && <Space wrap>
        <Tag color={query.data.api_key_configured ? 'green' : 'default'}>{query.data.api_key_configured ? 'API Key 已配置' : '离线模式'}</Tag>
        <Tag>{query.data.api_key_source === 'runtime' ? '运行时配置' : query.data.api_key_source === 'environment' ? '环境变量' : '未配置'}</Tag>
      </Space>}
      <Alert type="info" showIcon title="配置仅保存在当前服务进程中；重启后恢复环境变量配置。" />
      {query.isError && <Alert type="error" showIcon title="无法读取模型配置" description={query.error.message} />}
      {save.isError && <Alert type="error" showIcon title="保存失败" description={save.error.message} />}
    </div>
  </Modal>
}
