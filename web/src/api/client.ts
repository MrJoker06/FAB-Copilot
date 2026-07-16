export interface ApiEnvelope<T> {
  data: T
  request_id: string
}

export interface ProblemDetail {
  title: string
  status: number
  detail: string
  error_code: string
  request_id: string
  retryable: boolean
}

export class ApiError extends Error {
  constructor(public readonly problem: ProblemDetail) {
    super(problem.detail)
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      Accept: 'application/json',
      ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
      ...init?.headers,
    },
  })
  const payload = await response.json()
  if (!response.ok) throw new ApiError(payload as ProblemDetail)
  return (payload as ApiEnvelope<T>).data
}
