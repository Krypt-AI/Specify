// All Google access goes through the backend; the browser only holds an httpOnly session cookie.
export const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_URL}/api${path}`, {
    ...init,
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...init.headers },
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new ApiError(response.status, body.detail ?? response.statusText)
  }
  return (response.status === 204 ? undefined : await response.json()) as T
}

export function oauthStartUrl(purpose: 'login' | 'gmail' | 'sheets') {
  return `${API_URL}/api/auth/google/start?purpose=${purpose}`
}
