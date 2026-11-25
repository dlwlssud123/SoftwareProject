import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import App from '../src/App'
import AccessBoundary from '../src/components/AccessBoundary'
import type { AdminApi, AdminSession, JobPage } from '../src/api'
import { ApiError } from '../src/api'

const makeSession = (char = 'A'): AdminSession => ({ token: char.repeat(43), userId: '00000000-0000-4000-8000-000000000001', expiresAt: new Date(Date.now() + 3600000).toISOString() })
const page = (): JobPage => ({ total: 25, limit: 20, offset: 0, items: [{ id: '00000000-0000-4000-8000-000000000002', status: 'failed', attempts: 2,
  created_at: '2026-11-19T23:50:00Z', next_run_at: '2026-11-20T00:00:00Z', started_at: null, finished_at: null, error_code: 'import_welfare' }] })
function service(): AdminApi {
  return { configured: true, requestJson: vi.fn(), login: vi.fn().mockResolvedValue(makeSession()), logout: vi.fn().mockResolvedValue(undefined), identity: vi.fn(), jobs: vi.fn().mockResolvedValue(page()) }
}
function show(api: AdminApi) {
  window.history.replaceState(null, '', '/#collections')
  return render(<AccessBoundary api={api}>{(connection) => <App key={`${connection.session.userId}:${connection.session.expiresAt}`} connection={connection} />}</AccessBoundary>)
}
function enter() {
  fireEvent.change(screen.getByLabelText('관리자 아이디'), { target: { value: 'operator' } })
  fireEvent.change(screen.getByLabelText('비밀번호'), { target: { value: 'fixture password' } })
  fireEvent.click(screen.getByRole('button', { name: '로그인' }))
}

it('잘못된 로그인은 관리자 화면을 열지 않고 비밀번호를 비운다', async () => {
  const api = service()
  vi.mocked(api.login).mockRejectedValue(new ApiError(401, '로그인 실패'))
  show(api)
  expect(screen.queryByRole('navigation')).toBeNull()
  enter()
  expect(await screen.findByRole('alert')).toHaveProperty('textContent', '로그인 실패')
  expect((screen.getByLabelText('비밀번호') as HTMLInputElement).value).toBe('')
  expect(api.jobs).not.toHaveBeenCalled()
})

it('세션은 브라우저 저장소에 쓰지 않고 성공 후 한국 시간 수집 현황을 표시한다', async () => {
  const save = vi.spyOn(Storage.prototype, 'setItem')
  const api = service()
  show(api); enter()
  expect(await screen.findByRole('table')).toBeTruthy()
  expect(screen.getByText('import_welfare')).toBeTruthy()
  expect(screen.getByText('실패', { selector: '.job-status' })).toBeTruthy()
  expect(within(screen.getByRole('table')).getByText(/2026\. 11\. 20\..*8:50/)).toBeTruthy()
  expect(save).not.toHaveBeenCalled()
  expect(api.jobs).toHaveBeenCalledWith(expect.any(String), { q: '', offset: 0 }, expect.any(AbortSignal))
})

it('필터는 조회 버튼으로 적용하고 페이지 이동과 새로고침도 같은 조건을 유지한다', async () => {
  const api = service(); show(api); enter()
  await screen.findByRole('table')
  fireEvent.click(screen.getByRole('button', { name: '다음 페이지' }))
  await waitFor(() => expect(api.jobs).toHaveBeenLastCalledWith(expect.any(String), { q: '', offset: 20 }, expect.any(AbortSignal)))
  fireEvent.change(screen.getByLabelText('처리 상태'), { target: { value: 'failed' } })
  fireEvent.change(screen.getByLabelText('실패 단계 코드'), { target: { value: 'import_' } })
  fireEvent.click(screen.getByRole('button', { name: '조회' }))
  await waitFor(() => expect(api.jobs).toHaveBeenLastCalledWith(expect.any(String), { status: 'failed', q: 'import_', offset: 0 }, expect.any(AbortSignal)))
  await screen.findByRole('table')
  fireEvent.click(screen.getByRole('button', { name: '새로고침' }))
  await waitFor(() => expect(api.jobs).toHaveBeenCalledTimes(4))
})

it('개인 정보가 담길 수 있는 서버 오류는 화면 예시로 대체하지 않고 재시도한다', async () => {
  const api = service()
  vi.mocked(api.jobs).mockRejectedValueOnce(new ApiError(503, '수집 연결 오류')).mockResolvedValueOnce({ total: 0, items: [], offset: 0, limit: 20 })
  show(api); enter()
  expect(await screen.findByRole('alert')).toHaveProperty('textContent', '수집 연결 오류')
  fireEvent.click(screen.getByRole('button', { name: '다시 시도' }))
  expect(await screen.findByText(/조건에 맞는 수집 작업이 없습니다/)).toBeTruthy()
  expect(screen.queryByText('예시 항목 A')).toBeNull()
})

it.each([401, 403])('수집 조회 중 인증·권한이 사라지면 이전 내용을 지운다: %s', async (status) => {
  const api = service(); show(api); enter()
  await screen.findByRole('table')
  vi.mocked(api.jobs).mockRejectedValueOnce(new ApiError(status, '다시 로그인하세요'))
  fireEvent.click(screen.getByRole('button', { name: '새로고침' }))
  expect(await screen.findByRole('heading', { name: '관리자 로그인' })).toBeTruthy()
  expect(screen.queryByRole('table')).toBeNull()
  expect(screen.queryByLabelText('수집 작업 요약')).toBeNull()
})

it('로그아웃 통신이 실패해도 브라우저에서 개인 작업 내용을 제거한다', async () => {
  const api = service(); show(api); enter()
  await screen.findByRole('table')
  vi.mocked(api.logout).mockRejectedValueOnce(new ApiError(0, 'offline'))
  fireEvent.click(screen.getByRole('button', { name: '로그아웃' }))
  expect(await screen.findByRole('heading', { name: '관리자 로그인' })).toBeTruthy()
  expect(screen.getByText(/서버 세션 폐기는 확인하지 못했/)).toBeTruthy()
  expect(screen.queryByText('import_welfare')).toBeNull()
})

it('늦게 도착한 이전 요청은 새로 로그인한 관리자의 화면을 바꾸지 못한다', async () => {
  const api = service()
  let finish: (value: JobPage) => void = () => {}
  vi.mocked(api.jobs).mockImplementationOnce(() => new Promise((resolve) => { finish = resolve }))
  const view = show(api); enter()
  await screen.findByRole('button', { name: '로그아웃' })
  fireEvent.click(screen.getByRole('button', { name: '로그아웃' }))
  await screen.findByRole('heading', { name: '관리자 로그인' })
  vi.mocked(api.login).mockResolvedValueOnce(makeSession('B'))
  vi.mocked(api.jobs).mockResolvedValueOnce({ total: 0, items: [], offset: 0, limit: 20 })
  enter()
  await screen.findByText(/조건에 맞는 수집 작업이 없습니다/)
  await act(async () => finish(page()))
  expect(screen.queryByText('import_welfare')).toBeNull()
  view.unmount()
})

it('설정이 없는 웹은 개발용 권한 선택으로 진입하지 못한다', () => {
  const api = service(); api.configured = false
  show(api)
  expect((screen.getByRole('button', { name: '로그인' }) as HTMLButtonElement).disabled).toBe(true)
  expect(screen.queryByLabelText('권한 상태')).toBeNull()
})

it('서버에서 받은 세션 만료 시각에는 다시 로그인하도록 전환한다', async () => {
  vi.useFakeTimers()
  const api = service()
  vi.mocked(api.login).mockResolvedValueOnce({ ...makeSession(), expiresAt: new Date(Date.now() + 5000).toISOString() })
  show(api)
  await act(async () => enter())
  expect(screen.getByRole('table')).toBeTruthy()
  await act(async () => { await vi.advanceTimersByTimeAsync(5001) })
  expect(screen.getByRole('heading', { name: '관리자 로그인' })).toBeTruthy()
})
