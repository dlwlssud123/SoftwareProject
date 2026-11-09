const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL ?? ''
).replace(/\/+$/, '')

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export async function requestJson<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  if (!API_BASE_URL) {
    throw new Error('API 서버 주소가 설정되지 않았습니다.')
  }

  if (!path.startsWith('/') || path.startsWith('//')) {
    throw new Error('API 경로는 /로 시작하는 상대 경로여야 합니다.')
  }

  const headers = new Headers(options.headers)
  headers.set('Accept', 'application/json')

  // 인증·쿠키 전달 방식은 서버 담당자와 합의 후 적용합니다.
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers,
    credentials: 'omit',
  })

  if (!response.ok) {
    const message =
      response.status === 401
        ? '로그인이 필요합니다.'
        : response.status === 403
          ? '접근 권한이 없습니다.'
          : `요청 처리에 실패했습니다. (${response.status})`

    throw new ApiError(response.status, message)
  }

  if (response.status === 204) {
    return undefined as T
  }

  return (await response.json()) as T
}