import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { createAdminApi } from '../src/api'
import { createTopicApi } from '../src/topicApi'
import type { Topic } from '../src/topicApi'
import TopicRequests from '../src/components/TopicRequests'
import App from '../src/App'

const requestId = '00000000-0000-4000-8000-000000000010'
const guideId = '00000000-0000-4000-8000-000000000011'
const actorId = '00000000-0000-4000-8000-000000000012'
const root = '/api/v1/admin/content-topic-requests'
const token = 'owner'
const summary = { id: guideId, slug: 'phone-text', title: '휴대폰 글씨 크게 보기', source_reference: '서비스 이용 안내', checked_on: '2026-11-20' }
const published = { ...summary, version: 2, review_status: 'approved', is_published: true, reviewed_by: actorId, reviewed_at: '2026-11-20T00:00:00Z', updated_at: '2026-11-20T00:00:00Z' }
const initial = (): Topic => ({ id: requestId, kind: 'life_guide', topic: '큰 글씨 안내 요청', status: 'received', version: 1, reply: null, guide: null, guide_id: null, created_at: '2026-11-20T00:00:00Z', updated_at: '2026-11-20T00:00:00Z' })
const envelope = (data: unknown, status = 200) => new Response(JSON.stringify({ data, meta: { request_id: actorId } }), { status })
const page = (items: unknown[]) => ({ items, limit: 20, offset: 0, total: items.length })
function fixture(row = initial()) {
  const behavior = { status: 200, network: false, auth: 200, gone: false, empty: false }
  const send = vi.fn<typeof fetch>().mockImplementation(async (url, options) => {
    const path = new URL(url.toString()).pathname
    if (behavior.auth !== 200) return envelope(null, behavior.auth)
    if (path === '/api/v1/admin/life-guides') return envelope(page(behavior.empty ? [] : [published]))
    if (options?.method === 'PUT') {
      if (behavior.status !== 200) return envelope(null, behavior.status)
      const body = JSON.parse(options.body as string)
      Object.assign(row, body, { version: row.version + 1, guide: body.guide_id ? summary : null })
      if (behavior.network) throw new TypeError('private connection detail')
      return envelope(row)
    }
    if (path.endsWith('/audit')) return envelope(page([{ id: guideId, actor_id: actorId, action: 'create', before_state: null, after_state: { status: row.status, version: row.version }, request_id: actorId, created_at: row.created_at }]))
    if (path === root) return envelope(page(behavior.gone ? [] : [row]))
    return envelope(behavior.gone ? null : row, behavior.gone ? 404 : 200)
  })
  const api = createAdminApi('https://example.test', send)
  const invalidate = vi.fn(), onDirty = vi.fn(), logout = vi.fn().mockResolvedValue(undefined)
  const connection = { api, session: { token, userId: actorId, expiresAt: '2099-01-01T00:00:00Z' }, invalidate, logout }
  return { row, behavior, send, api, invalidate, onDirty, logout, connection, show: () => render(<TopicRequests connection={connection} onDirtyChange={onDirty} />) }
}
async function open() {
  fireEvent.click(await screen.findByRole('button', { name: /큰 글씨 안내 요청/ }))
  await screen.findByLabelText('운영자 답변')
}
const putCalls = (send: ReturnType<typeof fixture>['send']) => send.mock.calls.filter(([, options]) => options?.method === 'PUT')

it('종류·상태·검색 조건과 본 판본을 보내고 조회에는 같은 origin의 관리자 토큰을 쓴다', async () => {
  const { api, send } = fixture()
  const topics = createTopicApi(api, token)
  expect((await topics.list({ q: ' 글씨 ', kind: 'life_guide', status: 'received', offset: 20 })).items[0].id).toBe(requestId)
  const [url, options] = send.mock.calls[0]
  expect(Object.fromEntries(new URL(url.toString()).searchParams)).toEqual({ q: '글씨', kind: 'life_guide', status: 'received', limit: '20', offset: '20' })
  expect((options?.headers as Headers).get('Authorization')).toBe('Bearer owner')
  expect(options?.cache).toBe('no-store')
  expect(options?.redirect).toBe('error')
  const record = await topics.review(requestId, 1, { status: 'reviewing', reply: null, guide_id: null })
  expect(record.version).toBe(2)
  expect(JSON.parse(putCalls(send)[0][1]!.body as string)).toEqual({ expected_version: 1, status: 'reviewing', reply: null, guide_id: null })
  await expect(topics.get('../../outside')).rejects.toThrow()
  expect(send).toHaveBeenCalledTimes(2)
})

it('취소 상태·잘못된 판본·시간대 누락·불일치한 연결은 정상 요청으로 표시하지 않는다', async () => {
  for (const bad of [{ ...initial(), status: 'withdrawn', topic: null }, { ...initial(), version: 0 }, { ...initial(), created_at: '2026-11-20T00:00:00' }, { ...initial(), status: 'completed', reply: '답변', guide: summary, guide_id: null }]) {
    const api = createAdminApi('https://example.test', vi.fn().mockResolvedValue(envelope(bad)))
    await expect(createTopicApi(api, token).get(requestId)).rejects.toThrow()
  }
})

it('접수 주제·상태·처리 이력을 읽고 검토 중으로 저장한다', async () => {
  const { show, send } = fixture(); show(); await open()
  expect(await screen.findByText(/서버 요청 번호/)).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '처리 내용 저장' }))
  await screen.findByText('처리 내용을 저장했습니다. 사용자가 앱에서 답변을 확인할 수 있습니다.')
  expect(JSON.parse(putCalls(send)[0][1]!.body as string).expected_version).toBe(1)
  expect(putCalls(send)).toHaveLength(1)
})

it('생활 안내 완료는 답변과 승인·게시 가이드가 모두 필요하다', async () => {
  const { show, send } = fixture(); show(); await open()
  fireEvent.change(screen.getByLabelText('변경할 처리 상태'), { target: { value: 'completed' } })
  fireEvent.click(screen.getByRole('button', { name: '처리 내용 저장' }))
  expect(await screen.findByRole('alert')).toHaveProperty('textContent', expect.stringContaining('답변'))
  expect(putCalls(send)).toHaveLength(0)
  fireEvent.change(screen.getByLabelText('운영자 답변'), { target: { value: '안내를 준비했습니다.' } })
  fireEvent.click(screen.getByRole('button', { name: '처리 내용 저장' }))
  expect(await screen.findByRole('alert')).toHaveProperty('textContent', expect.stringContaining('가이드'))
  await screen.findByRole('option', { name: /휴대폰 글씨 크게 보기/ })
  const lookup = send.mock.calls.find(([url]) => new URL(url.toString()).pathname === '/api/v1/admin/life-guides')!
  expect(new URL(lookup[0].toString()).searchParams.get('is_published')).toBe('true')
  expect(new URL(lookup[0].toString()).searchParams.get('review_status')).toBe('approved')
  fireEvent.change(screen.getByLabelText('연결할 생활 가이드'), { target: { value: guideId } })
  fireEvent.click(screen.getByRole('button', { name: '처리 내용 저장' }))
  await screen.findByText('처리 내용을 저장했습니다. 사용자가 앱에서 답변을 확인할 수 있습니다.')
  expect(JSON.parse(putCalls(send)[0][1]!.body as string)).toEqual({ expected_version: 1, status: 'completed', reply: '안내를 준비했습니다.', guide_id: guideId })
})

it('게시 안내가 없으면 완료를 가장하지 않고 검수·게시가 필요함을 안내한다', async () => {
  const { show, behavior, send } = fixture(); behavior.empty = true; show(); await open()
  fireEvent.change(screen.getByLabelText('변경할 처리 상태'), { target: { value: 'completed' } })
  expect(await screen.findByText(/게시된 안내가 없습니다/)).toBeTruthy()
  expect(putCalls(send)).toHaveLength(0)
})

it('영상 요청은 가이드 없이 답변하고 제작 완료라고 표시하지 않는다', async () => {
  const { show, send } = fixture({ ...initial(), kind: 'video' }); show(); await open()
  fireEvent.change(screen.getByLabelText('변경할 처리 상태'), { target: { value: 'completed' } })
  fireEvent.change(screen.getByLabelText('운영자 답변'), { target: { value: '제안한 주제를 검토했습니다.' } })
  expect(screen.queryByLabelText('연결할 생활 가이드')).toBeNull()
  expect(screen.getByText('영상 요청 답변은 제작·게시를 자동으로 실행하지 않습니다.')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '처리 내용 저장' }))
  await screen.findByText('처리 내용을 저장했습니다. 사용자가 앱에서 답변을 확인할 수 있습니다.')
  expect(JSON.parse(putCalls(send)[0][1]!.body as string).guide_id).toBeNull()
})

it('최종 결정 변경은 검토 중으로 먼저 되돌리도록 안내한다', async () => {
  const { show } = fixture({ ...initial(), kind: 'video', status: 'completed', reply: '기존 답변' }); show(); await open()
  const select = screen.getByLabelText('변경할 처리 상태') as HTMLSelectElement
  expect([...select.options].map((option) => option.value)).toEqual(['reviewing', 'completed'])
  expect(screen.getByText('완료와 보류를 서로 바꾸려면 먼저 검토 중으로 저장해 주세요.')).toBeTruthy()
})

it('판본 충돌은 답변을 보존하고 조회 전 덮어쓰기와 중복 저장을 막는다', async () => {
  const { show, behavior, send } = fixture(); show(); await open()
  fireEvent.change(screen.getByLabelText('운영자 답변'), { target: { value: '유지할 답변' } })
  behavior.status = 409
  fireEvent.click(screen.getByRole('button', { name: '처리 내용 저장' }))
  await screen.findByRole('alert')
  expect((screen.getByLabelText('운영자 답변') as HTMLTextAreaElement).value).toBe('유지할 답변')
  expect((screen.getByRole('button', { name: '처리 내용 저장' }) as HTMLButtonElement).disabled).toBe(true)
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
  fireEvent.click(screen.getByRole('button', { name: '최신 요청 불러오기' }))
  expect((screen.getByLabelText('운영자 답변') as HTMLTextAreaElement).value).toBe('유지할 답변')
  confirm.mockReturnValue(true)
  fireEvent.click(screen.getByRole('button', { name: '최신 요청 불러오기' }))
  await waitFor(() => expect((screen.getByLabelText('운영자 답변') as HTMLTextAreaElement).value).toBe(''))
  expect(putCalls(send)).toHaveLength(1)
})

it('서버가 저장했지만 응답을 잃으면 자동 재전송 없이 최신 조회로 확인한다', async () => {
  const { show, behavior, send } = fixture(); show(); await open()
  fireEvent.change(screen.getByLabelText('운영자 답변'), { target: { value: '서버에 저장된 답변' } })
  behavior.network = true
  fireEvent.click(screen.getByRole('button', { name: '처리 내용 저장' }))
  expect(await screen.findByRole('alert')).toHaveProperty('textContent', expect.stringContaining('처리 결과를 확인하지 못했습니다'))
  expect(screen.queryByText('private connection detail')).toBeNull()
  expect((screen.getByRole('button', { name: '처리 내용 저장' }) as HTMLButtonElement).disabled).toBe(true)
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  fireEvent.click(screen.getByRole('button', { name: '최신 요청 불러오기' }))
  await waitFor(() => expect((screen.getByRole('button', { name: '처리 내용 저장' }) as HTMLButtonElement).disabled).toBe(false))
  expect((screen.getByLabelText('운영자 답변') as HTMLTextAreaElement).value).toBe('서버에 저장된 답변')
  expect(putCalls(send)).toHaveLength(1)
})

it('같은 주제를 재선택해도 미저장 답변 보호를 해제하지 않는다', async () => {
  const { show, onDirty } = fixture(); show(); await open()
  fireEvent.change(screen.getByLabelText('운영자 답변'), { target: { value: '작성 중' } })
  await waitFor(() => expect(onDirty).toHaveBeenLastCalledWith(true))
  fireEvent.click(screen.getByRole('button', { name: /큰 글씨 안내 요청/ }))
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
  fireEvent.click(screen.getByRole('button', { name: '요청 상세 닫기' }))
  expect(confirm).toHaveBeenCalledOnce()
  expect((screen.getByLabelText('운영자 답변') as HTMLTextAreaElement).value).toBe('작성 중')
})

it('메뉴 이동·브라우저 뒤로가기·로그아웃에서도 미저장 답변을 보호한다', async () => {
  const { connection, logout } = fixture()
  window.history.replaceState(null, '', '/#requests')
  render(<App connection={connection} />); await open()
  fireEvent.change(screen.getByLabelText('운영자 답변'), { target: { value: '작성 중' } })
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
  fireEvent.click(screen.getByRole('button', { name: '로그아웃' }))
  expect(logout).not.toHaveBeenCalled()
  await act(async () => { window.history.pushState(null, '', '/#overview'); window.dispatchEvent(new HashChangeEvent('hashchange')) })
  expect(window.location.hash).toBe('#requests')
  expect((screen.getByLabelText('운영자 답변') as HTMLTextAreaElement).value).toBe('작성 중')
  confirm.mockReturnValue(true)
  fireEvent.click(screen.getByRole('button', { name: '로그아웃' }))
  await waitFor(() => expect(logout).toHaveBeenCalledOnce())
})

it('취소되어 없어진 요청은 저장을 막고 인증 만료는 관리자 경계로 전달한다', async () => {
  const { show, behavior, invalidate } = fixture(); show(); await open()
  behavior.status = 404; behavior.gone = true
  fireEvent.click(screen.getByRole('button', { name: '처리 내용 저장' }))
  await screen.findByRole('alert')
  await waitFor(() => expect(screen.queryByText('큰 글씨 안내 요청')).toBeNull())
  expect(screen.queryByLabelText('운영자 답변')).toBeNull()
  behavior.auth = 401
  fireEvent.click(screen.getByRole('button', { name: '요청 목록 새로고침' }))
  await waitFor(() => expect(invalidate).toHaveBeenCalledWith(token, expect.any(String)))
})

it('요청 원문은 HTML로 실행하지 않고 그대로 표시한다', async () => {
  const { show } = fixture({ ...initial(), topic: '<img src=x onerror=alert(1)>' }); show()
  expect(await screen.findByText('<img src=x onerror=alert(1)>')).toBeTruthy()
  expect(document.querySelector('img, script')).toBeNull()
})

it('닫은 상세의 늦은 응답은 이전 원문과 답변을 되살리지 않는다', async () => {
  const { show, send } = fixture(); show()
  await screen.findByRole('button', { name: /큰 글씨 안내 요청/ })
  let complete: (value: Response) => void = () => {}
  send.mockImplementationOnce(() => new Promise((resolve) => { complete = resolve }))
  fireEvent.click(screen.getByRole('button', { name: /큰 글씨 안내 요청/ }))
  fireEvent.click(screen.getByRole('button', { name: '요청 상세 닫기' }))
  await act(async () => complete(envelope(initial())))
  expect(screen.queryByLabelText('운영자 답변')).toBeNull()
  expect(screen.queryByRole('heading', { name: '요청 상세·답변' })).toBeNull()
})

it('감사 조회가 취소를 확인한 뒤 늦은 상세 성공 응답이 원문을 복원하지 않는다', async () => {
  const { show, send, behavior } = fixture(); show(); await open()
  await screen.findByText(/서버 요청 번호/)
  const original = send.getMockImplementation()!
  const old = { ...initial() }
  let complete: (value: Response) => void = () => {}
  send.mockImplementation((url, options) => {
    const path = new URL(url.toString()).pathname
    if (path === `${root}/${requestId}`) return new Promise((resolve) => { complete = resolve })
    if (path.endsWith('/audit')) return Promise.resolve(envelope(null, 404))
    return original(url, options)
  })
  behavior.gone = true
  fireEvent.click(screen.getByRole('button', { name: '최신 요청 불러오기' }))
  await screen.findByText('사용자가 취소했거나 조회할 수 없는 요청입니다. 목록을 다시 확인해 주세요.')
  await act(async () => complete(envelope(old)))
  expect(screen.queryByLabelText('운영자 답변')).toBeNull()
  expect(screen.queryByText(old.topic)).toBeNull()
  expect((screen.getByRole('button', { name: '최신 요청 불러오기' }) as HTMLButtonElement).disabled).toBe(true)
})

it('저장 응답을 기다리던 중 확인한 취소도 늦은 PUT 성공으로 되돌릴 수 없다', async () => {
  const { show, send, behavior } = fixture()
  const original = send.getMockImplementation()!
  let cancelSeen = false
  let complete: (value: Response) => void = () => {}
  send.mockImplementation((url, options) => {
    const path = new URL(url.toString()).pathname
    if (options?.method === 'PUT') return new Promise((resolve) => { complete = resolve })
    if (path.endsWith('/audit')) return Promise.resolve(envelope(null, cancelSeen ? 404 : 503))
    return original(url, options)
  })
  show(); await open()
  await screen.findByRole('button', { name: '처리 이력 다시 확인' })
  fireEvent.change(screen.getByLabelText('운영자 답변'), { target: { value: '저장 중 답변' } })
  fireEvent.click(screen.getByRole('button', { name: '처리 내용 저장' }))
  await screen.findByRole('button', { name: '답변 저장 중…' })
  cancelSeen = true; behavior.gone = true
  fireEvent.click(screen.getByRole('button', { name: '처리 이력 다시 확인' }))
  await screen.findByText('사용자가 취소했거나 조회할 수 없는 요청입니다. 목록을 다시 확인해 주세요.')
  await act(async () => complete(envelope({ ...initial(), status: 'reviewing', reply: '저장 중 답변', version: 2 })))
  expect(screen.queryByLabelText('운영자 답변')).toBeNull()
  expect(screen.queryByText('큰 글씨 안내 요청')).toBeNull()
  expect(screen.queryByText(/처리 내용을 저장했습니다/)).toBeNull()
})
