export interface FabOverview {
  lots: number
  wafers: number
  yield_pct: number
  avg_cycle_hours: number
  avg_hold_hours: number
  held_lots: number
  excursions: number
  start: string
  end: string
}

export interface YieldPoint {
  week: string
  yield_pct: number
  cycle_time_hours: number
  lots: number
}

export interface EquipmentHealth {
  equipment_id: string
  runs: number
  excursions: number
  downtime_hours: number
  health: 'Healthy' | 'Watch' | 'Risk'
}

export interface DashboardData {
  overview: FabOverview
  yield_trend: YieldPoint[]
  equipment: EquipmentHealth[]
  defects: Array<{ defect_type: string; defect_count: number; share_pct: number }>
  excursions: Array<Record<string, unknown>>
}

export interface CapabilityRow {
  equipment_id: string
  samples: number
  mean_value: number
  sigma: number
  cpk: number
  metric_name: string
  metric_unit: string
}

export interface KnowledgeDocument {
  title: string
  source: string
  doc_type: string
  version: string
  owner: string
  authority: string
  effective_date: string
  section_count: number
  sections: string
  first_chunk_id: number
}

export interface HistoricalCase {
  case_id: string
  title: string
  process_step: string
  equipment_id: string
  occurred_date: string
  severity: string
  problem: string
  summary: string
  root_cause_confidence: string
  recurrence_status: string
}

export interface SessionSummary {
  session_id: string
  title: string
  updated_at: string
  model: string | null
  archived_at: string | null
  last_message_preview: string | null
  message_count: number
}

export interface MonitorSummary {
  runs: number
  success_runs: number
  failed_runs: number
  success_rate_pct: number | null
  avg_duration_ms: number | null
  p95_duration_ms: number | null
  model_calls: number
  tool_calls: number
  tool_usage: Array<{ tool: string; count: number }>
  errors: Array<{ type: string; count: number }>
}

export interface ChatResult {
  answer: string
  mode: string
  session_id: string
  message_id: number
  tool_trace: Array<{ tool: string; status: string; rows: number | null; truncated: boolean }>
}
