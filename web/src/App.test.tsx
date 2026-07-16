import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { expect, test, vi } from 'vitest'

import App from './App'

vi.mock('echarts-for-react', () => ({ default: () => <div data-testid="chart" /> }))

vi.stubGlobal('fetch', vi.fn(async () => ({
  ok: true,
  json: async () => ({ data: { overview:{lots:2,wafers:50,yield_pct:91,avg_cycle_hours:88,avg_hold_hours:1,held_lots:1,excursions:1,start:'2026-07-01',end:'2026-07-17'}, yield_trend:[], equipment:[], defects:[], excursions:[] }, request_id:'req-test0001' }),
})))

test('renders the V1-style FAB shell and Copilot', async () => {
  render(<QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={['/dashboard']}><App /></MemoryRouter></QueryClientProvider>)
  expect(screen.getByText('Fab Insight')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /隐藏分析助手/ })).toBeInTheDocument()
  expect(await screen.findByText('制造绩效总览')).toBeInTheDocument()
  expect(await screen.findByText('完成批次')).toBeInTheDocument()
})
