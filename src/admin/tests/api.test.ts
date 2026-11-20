import { describe, expect, it, vi } from 'vitest'
import { ApiError, createAdminApi } from '../src/api'

const token = 'T'.repeat(43)
const userId = '00000000-0000-4000-8000-000000000001'
const expires = () => new Date(Date.now() + 3600000).toISOString()
const reply = (data: unknown, status = 200) => new Response(JSON.stringify({ data }), { status, headers: { 'Content-Type': 'application/json' } })
const session = () => ({ user_id: userId, role: 'admin', access_token: token, expires_at: expires() })
const job = () => ({ id: userId, kind: 'public_data_daily', status: 'succeeded', attempts: 1,
  created_at: '2026-11-19T23:50:00Z', next_run_at: '2026-11-20T00:00:00Z', started_at: null, finished_at: null, error_code: null })

describe('관리자 API 경계', () => {
  it('기존 공통 요청의 data/meta 응답 형식과 헤더를 유지한다', async () => {
    const send = vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify({ data: { role: 'admin' }, meta: { request_id: 'fixture' } })))
    const result = await createAdminApi('https://example.test', send).requestJson('/api/v1/admin/me', { headers: { Authorization: `Bearer ${token}` } })
    expect(result).toEqual({ data: { role: 'admin' }, meta: { request_id: 'fixture' } })
    expect((send.mock.calls[0][1]?.headers as Headers).get('Authorization')).toBe(`Bearer ${token}`)
    expect(send.mock.calls[0][1]?.redirect).toBe('error')
  })
  it.each(['', 'http://public.test', 'https://user:fixture@example.test', 'https://example.test/api', 'https://example.test?q=x', 'javascript:bad'])('잘못된 서버 주소에는 비밀번호를 보내지 않는다: %s', async (base) => {
    const send = vi.fn<typeof fetch>()
    const api = createAdminApi(base, send, false)
    expect(api.configured).toBe(false)
    await expect(api.login('admin', 'fixture')).rejects.toBeInstanceOf(ApiError)
    expect(send).not.toHaveBeenCalled()
  })

  it('HTTP는 명시적으로 허용한 개발용 루프백에서만 사용한다', () => {
    expect(createAdminApi('http://127.0.0.1:8000', fetch, true).configured).toBe(true)
    expect(createAdminApi('http://127.0.0.1:8000', fetch, false).configured).toBe(false)
    expect(createAdminApi('http://other.test', fetch, true).configured).toBe(false)
  })

  it('로그인 후 서버 권한·계정·만료를 확인하고 토큰은 승인된 HTTPS API에만 보낸다', async () => {
    const send = vi.fn<typeof fetch>().mockResolvedValueOnce(reply(session())).mockResolvedValueOnce(reply(session()))
    const api = createAdminApi('https://example.test', send)
    const result = await api.login(' Admin ', 'fixture password')
    expect(result.userId).toBe(userId)
    expect(send.mock.calls[0][0].toString()).toBe('https://example.test/api/v1/admin/login')
    expect(JSON.parse(send.mock.calls[0][1]!.body as string)).toEqual({ username: 'admin', password: 'fixture password' })
    expect((send.mock.calls[0][1]!.headers as Headers).has('Authorization')).toBe(false)
    expect((send.mock.calls[1][1]!.headers as Headers).get('Authorization')).toBe(`Bearer ${token}`)
    for (const [, options] of send.mock.calls) {
      expect(options).toMatchObject({ credentials: 'omit', redirect: 'error', cache: 'no-store', referrerPolicy: 'no-referrer' })
    }
  })

  it.each(['user', 'operator', null])('응답의 관리자 아닌 역할은 진입을 허용하지 않는다: %s', async (role) => {
    const send = vi.fn<typeof fetch>().mockResolvedValue(reply({ ...session(), role }))
    await expect(createAdminApi('https://example.test', send).login('admin', 'fixture')).rejects.toBeInstanceOf(ApiError)
    expect(send).toHaveBeenCalledTimes(1)
  })

  it('추가 권한 확인에서 다른 사용자나 만료 세션이면 거절한다', async () => {
    for (const wrong of [{ ...session(), user_id: '00000000-0000-4000-8000-000000000002' }, { ...session(), expires_at: '2000-01-01T00:00:00Z' }]) {
      const send = vi.fn<typeof fetch>().mockResolvedValueOnce(reply(session())).mockResolvedValueOnce(reply(wrong))
      await expect(createAdminApi('https://example.test', send).login('admin', 'fixture')).rejects.toBeInstanceOf(ApiError)
    }
  })

  it.each([401, 403, 429, 503])('서버 오류 본문에 있는 개인/연결 정보를 표시하지 않는다: %s', async (status) => {
    const send = vi.fn<typeof fetch>().mockResolvedValue(new Response('private-password-and-connection', { status }))
    const error = await createAdminApi('https://example.test', send).login('admin', 'fixture').catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).status).toBe(status)
    expect((error as Error).message).not.toContain('private-password')
  })

  it('수집 현황은 같은 토큰과 필터로 조회하고 로그아웃은 현재 세션만 폐기한다', async () => {
    const send = vi.fn<typeof fetch>().mockResolvedValueOnce(reply({ items: [job()], total: 25, offset: 20, limit: 20 })).mockResolvedValueOnce(reply({ revoked: true }))
    const api = createAdminApi('https://example.test', send)
    const page = await api.jobs(token, { status: 'failed', q: ' import_welfare ', offset: 20 })
    const url = new URL(send.mock.calls[0][0].toString())
    expect(Object.fromEntries(url.searchParams)).toEqual({ limit: '20', offset: '20', status: 'failed', q: 'import_welfare' })
    expect(page.items[0].created_at).toBe('2026-11-19T23:50:00Z')
    await api.logout(token)
    expect(send.mock.calls[1][1]?.method).toBe('DELETE')
    expect((send.mock.calls[1][1]?.headers as Headers).get('Authorization')).toBe(`Bearer ${token}`)
  })

  it.each([{ kind: 'photo_analysis' }, { attempts: -1 }, { status: 'unknown' }, { created_at: '2026-11-20T00:00:00' }, { id: 'invalid' }])('잘못된 수집 작업 형식은 정상 데이터로 표시하지 않는다', async (changes) => {
    const send = vi.fn<typeof fetch>().mockResolvedValue(reply({ items: [{ ...job(), ...changes }], total: 1, offset: 0, limit: 20 }))
    await expect(createAdminApi('https://example.test', send).jobs(token)).rejects.toBeInstanceOf(ApiError)
  })

  it('호출자가 취소한 요청은 화면 오류 대신 AbortError로 구분한다', async () => {
    const send = vi.fn<typeof fetch>().mockImplementation((_, options) => new Promise((_, reject) => options!.signal!.addEventListener('abort', () => reject(new DOMException('Cancelled', 'AbortError')))))
    const controller = new AbortController()
    const request = createAdminApi('https://example.test', send).jobs(token, {}, controller.signal)
    controller.abort()
    await expect(request).rejects.toMatchObject({ name: 'AbortError' })
  })
})
