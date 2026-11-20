export class ApiError extends Error {
  readonly status: number
  readonly retryable: boolean
  constructor(status: number, message: string, retryable = false) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.retryable = retryable
  }
}

export type AdminSession = { token: string; userId: string; expiresAt: string }
export const jobStatuses = ['queued', 'running', 'succeeded', 'failed', 'cancelled'] as const
export type JobStatus = (typeof jobStatuses)[number]
export type DataJob = {
  id: string; status: JobStatus; attempts: number; created_at: string;
  next_run_at: string; started_at: string | null; finished_at: string | null;
  error_code: string | null;
}
export type JobPage = { items: DataJob[]; total: number; offset: number; limit: number }
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
const invalid = () => new ApiError(0, '서버 응답을 확인할 수 없습니다. 다시 시도해 주세요.', true)
function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw invalid()
  return value as Record<string, unknown>
}
function instant(value: unknown): string {
  if (typeof value !== 'string' || !/(Z|[+-]\d{2}:\d{2})$/.test(value) || !Number.isFinite(Date.parse(value))) throw invalid()
  return value
}
function integer(value: unknown): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0) throw invalid()
  return value
}

export function createAdminApi(
  baseUrl = import.meta.env?.VITE_API_BASE_URL ?? '',
  send: typeof fetch = fetch,
  allowLocalHttp = import.meta.env?.DEV ?? false,
) {
  let origin: string | null = null
  try {
    const url = new URL(baseUrl)
    const local = ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)
    if (url.username || url.password || url.search || url.hash || url.pathname !== '/' ||
        (url.protocol !== 'https:' && !(allowLocalHttp && local && url.protocol === 'http:'))) throw new Error()
    origin = url.origin
  } catch { /* Configuration errors never send credentials. */ }

  async function request(path: string, options: { token?: string; body?: unknown; rawBody?: BodyInit; headers?: HeadersInit; envelope?: boolean; method?: string; signal?: AbortSignal } = {}) {
    if (!origin) throw new ApiError(0, 'API 서버 주소를 확인해 주세요. 운영 환경은 HTTPS 주소가 필요합니다.')
    const url = new URL(path, origin)
    if (!path.startsWith('/api/v1/') || url.origin !== origin) throw invalid()
    const controller = new AbortController()
    const abort = () => controller.abort()
    options.signal?.addEventListener('abort', abort, { once: true })
    if (options.signal?.aborted) controller.abort()
    const timeout = setTimeout(abort, 10000)
    try {
      const headers = new Headers(options.headers)
      headers.set('Accept', 'application/json')
      if (options.token) headers.set('Authorization', `Bearer ${options.token}`)
      if (options.body !== undefined) headers.set('Content-Type', 'application/json')
      const response = await send(url, {
        method: options.method ?? 'GET', headers,
        body: options.body === undefined ? options.rawBody : JSON.stringify(options.body),
        credentials: 'omit', redirect: 'error', cache: 'no-store', referrerPolicy: 'no-referrer',
        signal: controller.signal,
      })
      if (!response.ok) {
        const login = path === '/api/v1/admin/login'
        throw new ApiError(response.status,
          response.status === 401 ? (login ? '아이디 또는 비밀번호를 확인해 주세요. 연속 실패 시 잠시 후 시도해 주세요.' : '로그인이 만료됐습니다. 다시 로그인해 주세요.') :
          response.status === 403 ? '관리자 권한이 없습니다.' :
          response.status === 404 ? '자료를 찾을 수 없습니다. 목록에서 다시 확인해 주세요.' :
          response.status === 409 ? '주소가 중복되거나 자료의 판본·처리 상태가 변경됐습니다. 최신 내용을 확인해 주세요.' :
          response.status === 422 ? '입력값의 형식과 길이를 확인해 주세요.' :
          response.status === 429 ? '로그인 시도가 많습니다. 잠시 후 다시 시도해 주세요.' :
          response.status === 503 ? '서버에서 처리할 수 없습니다. 잠시 후 다시 시도해 주세요.' : '요청을 처리하지 못했습니다.',
          [429, 503].includes(response.status))
      }
      if (response.status === 204) return null
      const envelope = record(await response.json())
      return options.envelope ? envelope : envelope.data
    } catch (error) {
      if (options.signal?.aborted) throw new DOMException('Cancelled', 'AbortError')
      if (error instanceof ApiError) throw error
      throw new ApiError(0, '서버에 연결할 수 없습니다. 연결 상태와 서버 주소를 확인해 주세요.', true)
    } finally {
      clearTimeout(timeout)
      options.signal?.removeEventListener('abort', abort)
    }
  }

  async function identity(token: string, signal?: AbortSignal) {
    const row = record(await request('/api/v1/admin/me', { token, signal }))
    if (row.role !== 'admin' || typeof row.user_id !== 'string' || !uuid.test(row.user_id)) throw invalid()
    return { userId: row.user_id, expiresAt: instant(row.expires_at) }
  }

  return {
    configured: origin !== null,
    async requestJson<T>(path: string, options: RequestInit = {}): Promise<T> {
      return await request(path, { method: options.method, headers: options.headers, rawBody: options.body ?? undefined,
        signal: options.signal ?? undefined, envelope: true }) as T
    },
    async login(username: string, password: string, signal?: AbortSignal): Promise<AdminSession> {
      const row = record(await request('/api/v1/admin/login', { method: 'POST', body: { username: username.trim().toLowerCase(), password }, signal }))
      if (row.role !== 'admin' || typeof row.access_token !== 'string' || !/^[A-Za-z0-9_-]{43}$/.test(row.access_token)) throw invalid()
      const token = row.access_token
      const me = await identity(token, signal)
      if (me.userId !== row.user_id || Date.parse(me.expiresAt) <= Date.now()) throw invalid()
      return { token, ...me }
    },
    identity,
    async logout(token: string) { await request('/api/v1/auth/session', { method: 'DELETE', token }) },
    async jobs(token: string, query: { status?: JobStatus; q?: string; offset?: number } = {}, signal?: AbortSignal): Promise<JobPage> {
      const params = new URLSearchParams({ limit: '20', offset: String(query.offset ?? 0) })
      if (query.status) params.set('status', query.status)
      if (query.q?.trim()) params.set('q', query.q.trim())
      const page = record(await request(`/api/v1/admin/data-jobs?${params}`, { token, signal }))
      if (!Array.isArray(page.items)) throw invalid()
      return {
        total: integer(page.total), offset: integer(page.offset), limit: integer(page.limit),
        items: page.items.map((value) => {
          const row = record(value)
          if (typeof row.id !== 'string' || !uuid.test(row.id) || row.kind !== 'public_data_daily' ||
              !jobStatuses.includes(row.status as JobStatus) ||
              (row.error_code !== null && typeof row.error_code !== 'string')) throw invalid()
          return { id: row.id, status: row.status as JobStatus, attempts: integer(row.attempts),
            created_at: instant(row.created_at), next_run_at: instant(row.next_run_at),
            started_at: row.started_at === null ? null : instant(row.started_at),
            finished_at: row.finished_at === null ? null : instant(row.finished_at),
            error_code: row.error_code as string | null }
        }),
      }
    },
  }
}

export type AdminApi = ReturnType<typeof createAdminApi>

// Preserve the foundation's common request export for teammate integrations.
export function requestJson<T>(path: string, options: RequestInit = {}): Promise<T> {
  return createAdminApi().requestJson<T>(path, options)
}
