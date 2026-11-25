import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { createAdminApi } from '../src/api'
import { createCommunityApi } from '../src/communityApi'
import CommunityReports from '../src/components/CommunityReports'
import type { AdminConnection } from '../src/components/AccessBoundary'

const id = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`
const initial = () => ({ id: id(1), status: 'received', reason: 'privacy', note: '연락처가 있어요', resolution: '',
  created_at: '2026-11-25T00:00:00Z', post: { id: id(2), title: '식사 이야기', body: '나눈 이야기',
    author_label: '이웃', status: 'published', version: 3 } })
const envelope = (data: unknown, status = 200) => new Response(JSON.stringify({ data, meta: {} }), { status })
function fixture() {
  let row = initial()
  const behavior = { status: 200, auth: false, done: false }
  const send = vi.fn<typeof fetch>().mockImplementation(async (_, options) => {
    if (behavior.auth) return envelope(null, 401)
    if (options?.method === 'PATCH') {
      if (behavior.status !== 200) return envelope(null, behavior.status)
      const body = JSON.parse(options.body as string)
      row = { ...row, status: body.decision === 'hide' ? 'actioned' : 'dismissed', resolution: body.resolution,
        post: { ...row.post, status: body.decision === 'hide' ? 'hidden' : 'published' } }
      behavior.done = true
      return envelope(row)
    }
    return envelope({ items: behavior.done ? [] : [row], total: behavior.done ? 0 : 1, limit: 20, offset: 0 })
  })
  const connection: AdminConnection = { api: createAdminApi('https://example.test', send),
    session: { token: 'test-session', userId: id(3), expiresAt: '2030-01-01T00:00:00Z' },
    invalidate: vi.fn(), logout: vi.fn() }
  const dirty = vi.fn()
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  const show = () => render(<CommunityReports connection={connection} onDirtyChange={dirty} />)
  return { show, connection, send, behavior, dirty }
}
const patches = (send: ReturnType<typeof fixture>['send']) => send.mock.calls.filter(([, options]) => options?.method === 'PATCH')

it('목록 인증과 숨김 요청의 실제 글 판본·처리 사유를 보낸다', async () => {
  const { show, send, dirty } = fixture(); show()
  fireEvent.click(await screen.findByRole('button', { name: '개인정보 노출 · 식사 이야기' }))
  fireEvent.click(screen.getByRole('button', { name: '글 숨김 처리' }))
  expect(patches(send)).toHaveLength(0)
  expect(await screen.findByRole('alert')).toHaveProperty('textContent', expect.stringContaining('처리 사유'))
  fireEvent.change(screen.getByLabelText('처리 사유'), { target: { value: '공개 연락처 포함' } })
  expect(dirty).toHaveBeenLastCalledWith(true)
  fireEvent.click(screen.getByRole('button', { name: '글 숨김 처리' }))
  await screen.findByText('글을 숨기고 신고를 처리했습니다.')
  expect(JSON.parse(patches(send)[0][1]!.body as string)).toEqual({ decision: 'hide', resolution: '공개 연락처 포함', expected_post_version: 3 })
  const headers = send.mock.calls[0][1]?.headers as Headers
  expect(headers.get('Authorization')).toBe('Bearer test-session')
  expect(send.mock.calls[0][1]?.redirect).toBe('error')
})
it('취소 확인에서는 쓰지 않고 기각은 별도 결정으로 처리한다', async () => {
  const { show, send } = fixture(); show()
  fireEvent.click(await screen.findByRole('button', { name: /개인정보 노출 ·/ }))
  fireEvent.change(screen.getByLabelText('처리 사유'), { target: { value: '문제 없음 확인' } })
  vi.mocked(window.confirm).mockReturnValueOnce(false)
  fireEvent.click(screen.getByRole('button', { name: '신고 기각' }))
  expect(patches(send)).toHaveLength(0)
  fireEvent.click(screen.getByRole('button', { name: '신고 기각' }))
  await screen.findByText('신고를 기각했습니다.')
  expect(JSON.parse(patches(send)[0][1]!.body as string).decision).toBe('dismiss')
})
it('409 충돌은 선택을 비우고 최신 목록을 다시 확인하게 한다', async () => {
  const { show, send, behavior } = fixture(); show()
  fireEvent.click(await screen.findByRole('button', { name: /개인정보 노출 ·/ }))
  fireEvent.change(screen.getByLabelText('처리 사유'), { target: { value: '확인' } })
  behavior.status = 409
  fireEvent.click(screen.getByRole('button', { name: '글 숨김 처리' }))
  await screen.findByText('글이나 신고 상태가 바뀌었습니다. 목록에서 다시 선택해 주세요.')
  expect(screen.queryByRole('button', { name: '글 숨김 처리' })).toBeNull()
  expect(patches(send)).toHaveLength(1)
  await waitFor(() => expect(send.mock.calls.filter(([, options]) => options?.method === 'GET').length).toBe(2))
})
it('권한 만료를 상위 인증 경계에 알린다', async () => {
  const { show, behavior, connection } = fixture(); behavior.auth = true; show()
  await waitFor(() => expect(connection.invalidate).toHaveBeenCalledWith('test-session', expect.any(String)))
})
it('깨진 글 판본이나 다른 경로로의 식별자를 정상 처리하지 않는다', async () => {
  const row = initial()
  const send = vi.fn<typeof fetch>().mockResolvedValue(envelope({ items: [{ ...row, post: { ...row.post, version: 0 } }], total: 1, offset: 0, limit: 20 }))
  const api = createCommunityApi(createAdminApi('https://example.test', send), 'test-session')
  await expect(api.list(0)).rejects.toThrow()
  await expect(api.resolve({ ...row, id: '../../wrong' } as never, 'hide', '확인')).rejects.toThrow()
  expect(send).toHaveBeenCalledTimes(1)
})
