import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { createAdminApi } from '../src/api'
import Guides from '../src/components/Guides'
import App from '../src/App'
import { createGuideApi } from '../src/guideApi'
import type { GuideDetail } from '../src/guideApi'

const guideId = '00000000-0000-4000-8000-000000000011'
const actorId = '00000000-0000-4000-8000-000000000012'
const token = 'G'.repeat(43)
const root = '/api/v1/admin/life-guides'
const initial = (): GuideDetail => ({ id: guideId, slug: 'safe-cooking', title: '안전한 요리', source_reference: '공공기관 안내 자료', checked_on: '2026-11-19',
  version: 1, review_status: 'draft', is_published: false, reviewed_by: null, reviewed_at: null, updated_at: '2026-11-20T00:00:00Z',
  steps: [{ text: '손을 먼저 씻으세요.' }], review_note: null })
const reply = (data: unknown, status = 200) => new Response(JSON.stringify({ data, meta: { request_id: actorId } }), { status })
const page = (items: unknown[]) => ({ items, limit: 20, offset: 0, total: items.length })
function fixture(value = initial()) {
  const send = vi.fn<typeof fetch>().mockImplementation(async (url, options) => {
    const path = new URL(url.toString()).pathname
    if (options?.method === 'POST' || options?.method === 'PUT') return reply(value)
    return reply(path.endsWith('/audit') ? page([]) : path === root ? page([value]) : value)
  })
  const api = createAdminApi('https://example.test', send)
  const invalidate = vi.fn()
  const onDirty = vi.fn()
  const show = () => render(<Guides connection={{ api, session: { token, userId: actorId, expiresAt: '2099-01-01T00:00:00Z' }, invalidate, logout: vi.fn() }} onDirtyChange={onDirty} />)
  return { send, api, invalidate, onDirty, show }
}
async function openGuide() { fireEvent.click(await screen.findByRole('button', { name: /안전한 요리/ })); await screen.findByLabelText('제목') }

it('가이드 목록 필터·출처·단계를 실제 DTO로 읽고 관리자 토큰을 같은 origin에만 보낸다', async () => {
  const { send, api } = fixture()
  const guides = createGuideApi(api, token)
  expect((await guides.list({ q: ' 요리 ', review_status: 'review', is_published: false, offset: 20 })).items[0].id).toBe(guideId)
  expect(Object.fromEntries(new URL(send.mock.calls[0][0].toString()).searchParams)).toEqual({ q: '요리', review_status: 'review', is_published: 'false', offset: '20', limit: '20' })
  expect((send.mock.calls[0][1]?.headers as Headers).get('Authorization')).toBe(`Bearer ${token}`)
  expect((await guides.get(guideId)).steps[0].text).toBe('손을 먼저 씻으세요.')
  await expect(guides.get('../../elsewhere')).rejects.toThrow()
  expect(send).toHaveBeenCalledTimes(2)
})

it('수정·검수 명령은 읽었던 판본을 보내며 승인과 게시 요청을 구분한다', async () => {
  const { send, api } = fixture()
  const guides = createGuideApi(api, token)
  const { title, source_reference, checked_on, steps } = initial()
  await guides.edit(guideId, { title, source_reference, checked_on, steps }, 3)
  expect(JSON.parse(send.mock.calls[0][1]!.body as string)).toEqual({ title, source_reference, checked_on, steps, expected_version: 3 })
  await guides.action(guideId, 'approve', 4, '출처 확인')
  await guides.action(guideId, 'publish', 5)
  expect(JSON.parse(send.mock.calls[1][1]!.body as string)).toEqual({ action: 'approve', expected_version: 4, note: '출처 확인' })
  expect(JSON.parse(send.mock.calls[2][1]!.body as string)).toEqual({ action: 'publish', expected_version: 5 })
})

it('모르는 검수 상태나 잘못된 상세 형식은 정상 가이드로 표시하지 않는다', async () => {
  for (const bad of [{ ...initial(), review_status: 'unknown' }, { ...initial(), is_published: 'yes' }, { ...initial(), steps: [{ text: 123 }] }]) {
    const { send, api } = fixture()
    send.mockResolvedValueOnce(reply(bad))
    await expect(createGuideApi(api, token).get(guideId)).rejects.toThrow()
  }
})

it('초안 저장은 입력한 모든 단계를 전송하고 생성된 가이드를 최신 조회할 수 있다', async () => {
  const { show, send } = fixture(); show()
  fireEvent.click(screen.getByRole('button', { name: '새 가이드 작성' }))
  fireEvent.change(screen.getByLabelText('가이드 주소'), { target: { value: 'safe-cooking' } })
  fireEvent.change(screen.getByLabelText('제목'), { target: { value: '안전한 요리' } })
  fireEvent.change(screen.getByLabelText('출처'), { target: { value: '공공기관 안내 자료' } })
  fireEvent.change(screen.getByLabelText('단계 1 설명'), { target: { value: '손을 먼저 씻으세요.' } })
  fireEvent.click(screen.getByRole('button', { name: '단계 추가' }))
  fireEvent.change(screen.getByLabelText('단계 2 설명'), { target: { value: '음식을 충분히 익히세요.' } })
  fireEvent.click(screen.getByRole('button', { name: '초안 저장' }))
  await screen.findByText('초안을 저장했습니다. 검수와 게시가 필요합니다.')
  const call = send.mock.calls.find(([, options]) => options?.method === 'POST')!
  expect(JSON.parse(call[1]!.body as string).steps).toEqual([{ text: '손을 먼저 씻으세요.' }, { text: '음식을 충분히 익히세요.' }])
  expect((screen.getByLabelText('가이드 주소') as HTMLInputElement).disabled).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: '최신 내용 불러오기' }))
  await waitFor(() => expect(send.mock.calls.filter(([url]) => new URL(url.toString()).pathname === `${root}/${guideId}`).length).toBe(1))
  await screen.findByLabelText('제목')
  fireEvent.click(screen.getByRole('button', { name: '새 가이드 작성' }))
  expect((screen.getByLabelText('제목') as HTMLInputElement).value).toBe('')
  expect((screen.getByLabelText('가이드 주소') as HTMLInputElement).disabled).toBe(false)
})

it('승인은 자동 게시하지 않고 승인된 판본으로 별도 게시한다', async () => {
  const { show, send } = fixture({ ...initial(), review_status: 'review', version: 3 }); show(); await openGuide()
  const reject = screen.getByRole('button', { name: '반려' }) as HTMLButtonElement
  expect(reject.disabled).toBe(true)
  expect(screen.queryByRole('button', { name: '게시' })).toBeNull()
  send.mockResolvedValueOnce(reply({ ...initial(), review_status: 'approved', version: 4, reviewed_by: actorId, reviewed_at: '2026-11-20T00:00:00Z' }))
  fireEvent.click(screen.getByRole('button', { name: '승인' }))
  await screen.findByText(/승인 처리했습니다/)
  expect(send.mock.calls.filter(([, o]) => o?.method === 'POST').length).toBe(1)
  send.mockResolvedValueOnce(reply({ ...initial(), review_status: 'approved', version: 5, is_published: true }))
  fireEvent.click(screen.getByRole('button', { name: '게시' }))
  await screen.findByRole('button', { name: '비공개' })
  const calls = send.mock.calls.filter(([, o]) => o?.method === 'POST')
  expect(calls.map(([, o]) => JSON.parse(o!.body as string))).toEqual([{ action: 'approve', expected_version: 3 }, { action: 'publish', expected_version: 4 }])
})

it('반려 의견은 필수이고 입력하면 판본과 함께 반려 API로 보낸다', async () => {
  const { show, send } = fixture({ ...initial(), review_status: 'review' }); show(); await openGuide()
  fireEvent.change(screen.getByLabelText('검수 의견'), { target: { value: ' 출처를 보완해 주세요. ' } })
  send.mockResolvedValueOnce(reply({ ...initial(), review_status: 'rejected', version: 2, review_note: '출처를 보완해 주세요.' }))
  fireEvent.click(screen.getByRole('button', { name: '반려' }))
  await screen.findByText('반려 처리했습니다.')
  expect(JSON.parse(send.mock.calls.find(([, o]) => o?.method === 'POST')![1]!.body as string)).toEqual({ action: 'reject', expected_version: 1, note: '출처를 보완해 주세요.' })
  expect(screen.getByText('검수 의견: 출처를 보완해 주세요.')).toBeTruthy()
})

it('판본 충돌은 입력을 보존하고 최신 내용을 명시적으로 읽기 전까지 덮어쓰지 않는다', async () => {
  const { show, send } = fixture(); show(); await openGuide()
  fireEvent.change(screen.getByLabelText('제목'), { target: { value: '내가 수정한 제목' } })
  expect((screen.getByRole('button', { name: '검수 요청' }) as HTMLButtonElement).disabled).toBe(true)
  send.mockResolvedValueOnce(reply(null, 409))
  fireEvent.click(screen.getByRole('button', { name: '초안 저장' }))
  await screen.findByRole('alert')
  expect((screen.getByLabelText('제목') as HTMLInputElement).value).toBe('내가 수정한 제목')
  expect((screen.getByRole('button', { name: '초안 저장' }) as HTMLButtonElement).disabled).toBe(true)
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
  fireEvent.click(screen.getByRole('button', { name: '최신 내용 불러오기' }))
  expect((screen.getByLabelText('제목') as HTMLInputElement).value).toBe('내가 수정한 제목')
  confirm.mockReturnValue(true)
  fireEvent.click(screen.getByRole('button', { name: '최신 내용 불러오기' }))
  await waitFor(() => expect((screen.getByLabelText('제목') as HTMLInputElement).value).toBe('안전한 요리'))
  expect(send.mock.calls.filter(([, o]) => o?.method === 'PUT').length).toBe(1)
})

it('전송 결과가 불명확한 저장은 자동 재시도하지 않고 조회로 확인하도록 막는다', async () => {
  const { show, send } = fixture(); show(); await openGuide()
  fireEvent.change(screen.getByLabelText('제목'), { target: { value: '수정한 제목' } })
  send.mockRejectedValueOnce(new TypeError('private connection detail'))
  fireEvent.click(screen.getByRole('button', { name: '초안 저장' }))
  expect(await screen.findByRole('alert')).toHaveProperty('textContent', expect.stringContaining('처리 결과를 확인하지 못했습니다'))
  expect(screen.queryByText('private connection detail')).toBeNull()
  expect((screen.getByRole('button', { name: '초안 저장' }) as HTMLButtonElement).disabled).toBe(true)
  expect(send.mock.calls.filter(([, o]) => o?.method === 'PUT').length).toBe(1)
})

it('로그인 만료는 관리자 경계에 전달하고 늦은 상세 응답은 닫은 편집기를 되살리지 못한다', async () => {
  const { show, send, invalidate } = fixture(); show(); await screen.findByRole('button', { name: /안전한 요리/ })
  let complete: (value: Response) => void = () => {}
  send.mockImplementationOnce(() => new Promise((resolve) => { complete = resolve }))
  fireEvent.click(screen.getByRole('button', { name: /안전한 요리/ }))
  fireEvent.click(screen.getByRole('button', { name: '상세 닫기' }))
  await act(async () => complete(reply(initial())))
  expect(screen.queryByLabelText('제목')).toBeNull()
  send.mockResolvedValueOnce(reply(null, 401))
  fireEvent.click(screen.getByRole('button', { name: '목록 새로고침' }))
  await waitFor(() => expect(invalidate).toHaveBeenCalledWith(token, expect.any(String)))
})

it('출처·본문의 HTML은 실행 가능한 마크업으로 해석하지 않는다', async () => {
  const value = { ...initial(), source_reference: '<img src=x onerror=alert(1)>', steps: [{ text: '<script>alert(1)</script>' }] }
  const { show } = fixture(value); show(); await openGuide()
  expect((screen.getByLabelText('출처') as HTMLTextAreaElement).value).toBe(value.source_reference)
  expect(document.querySelector('img, script')).toBeNull()
})

it('같은 가이드를 다시 눌러도 미저장 변경 보호를 해제하지 않는다', async () => {
  const { show, onDirty } = fixture(); show(); await openGuide()
  fireEvent.change(screen.getByLabelText('제목'), { target: { value: '저장 전 제목' } })
  await waitFor(() => expect(onDirty).toHaveBeenLastCalledWith(true))
  fireEvent.click(screen.getByRole('button', { name: /안전한 요리/ }))
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
  fireEvent.click(screen.getByRole('button', { name: '상세 닫기' }))
  expect(confirm).toHaveBeenCalledOnce()
  expect((screen.getByLabelText('제목') as HTMLInputElement).value).toBe('저장 전 제목')
})

it('앱 메뉴·브라우저 뒤로가기의 화면 이동도 미저장 가이드 변경을 보호한다', async () => {
  const { api } = fixture()
  const logout = vi.fn().mockResolvedValue(undefined)
  window.history.replaceState(null, '', '/#contents')
  render(<App connection={{ api, session: { token, userId: actorId, expiresAt: '2099-01-01T00:00:00Z' }, invalidate: vi.fn(), logout }} />)
  await openGuide()
  fireEvent.change(screen.getByLabelText('제목'), { target: { value: '작성 중인 가이드' } })
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
  fireEvent.click(screen.getByRole('button', { name: '로그아웃' }))
  expect(logout).not.toHaveBeenCalled()
  expect((screen.getByLabelText('제목') as HTMLInputElement).value).toBe('작성 중인 가이드')
  confirm.mockClear()
  await act(async () => { window.history.pushState(null, '', '/#overview'); window.dispatchEvent(new HashChangeEvent('hashchange')) })
  expect(confirm).toHaveBeenCalledOnce()
  expect(window.location.hash).toBe('#contents')
  expect((screen.getByLabelText('제목') as HTMLInputElement).value).toBe('작성 중인 가이드')
  confirm.mockReturnValue(true)
  await act(async () => { window.history.pushState(null, '', '/#overview'); window.dispatchEvent(new HashChangeEvent('hashchange')) })
  expect(screen.queryByLabelText('제목')).toBeNull()
  expect(screen.getByRole('heading', { name: '관리자 홈' })).toBeTruthy()
})

it('최신 내용 조회는 작성 중인 검수 의견도 확인 없이 지우지 않는다', async () => {
  const { show } = fixture({ ...initial(), review_status: 'review' }); show(); await openGuide()
  fireEvent.change(screen.getByLabelText('검수 의견'), { target: { value: '출처에 대한 의견 작성 중' } })
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
  fireEvent.click(screen.getByRole('button', { name: '최신 내용 불러오기' }))
  expect(confirm).toHaveBeenCalledOnce()
  expect((screen.getByLabelText('검수 의견') as HTMLTextAreaElement).value).toBe('출처에 대한 의견 작성 중')
  confirm.mockReturnValue(true)
  fireEvent.click(screen.getByRole('button', { name: '최신 내용 불러오기' }))
  await waitFor(() => expect((screen.getByLabelText('검수 의견') as HTMLTextAreaElement).value).toBe(''))
})
