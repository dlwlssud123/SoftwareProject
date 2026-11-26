import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import UsageDashboard from '../src/components/UsageDashboard'
import { createAdminApi } from '../src/api'
import { createUsageApi } from '../src/usageApi'
const id = '00000000-0000-4000-8000-000000000001'
function record() {
  return {
    event_id: id,
    created_at: '2026-11-26T01:00:00Z',
    event: 'request_finished',
    feature: 'meal',
    action: 'recommend',
    outcome: 'failure',
    app_version: '0.1.0',
    platform: 'android',
    duration_ms: 800,
    error_kind: 'timeout',
    request_id: id,
    result_count: null,
    result_kind: null,
    setting_kind: null,
    setting_value: null,
  }
}
function page(total = 41) {
  return {
    checked_at: '2026-11-26T01:00:01Z',
    retention_days: 30,
    total,
    offset: 0,
    limit: 20,
    app_opens: 0,
    features: total
      ? [
          {
            feature: 'meal',
            events: total,
            requests: 20,
            success: 15,
            failure: 4,
            cancelled: 1,
            avg_ms: 800,
          },
        ]
      : [],
    daily: total ? [{ day: '2026-11-26', count: total }] : [],
    items: total ? [record()] : [],
  }
}
function response(data: unknown, status = 200) {
  return new Response(JSON.stringify({ data }), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}
function setup(send: typeof fetch) {
  const api = createAdminApi('https://example.test', send)
  const connection = {
    api,
    session: {
      token: 'fixture-session',
      userId: id,
      expiresAt: '2099-01-01T00:00:00Z',
    },
    invalidate: vi.fn(),
    logout: vi.fn(),
  }
  render(<UsageDashboard connection={connection} />)
  return connection
}
function value(label: string) {
  return within(
    screen.getByText(label, { selector: 'dt' }).parentElement as HTMLElement,
  ).getByRole('definition').textContent
}

it('uses full filtered totals, completed-request denominators, Korean time and safe request IDs', async () => {
  setup(vi.fn(async () => response(page())) as typeof fetch)
  expect(await screen.findByText('41건', { selector: 'dd' })).toBeTruthy()
  expect(value('완료된 기능 요청')).toBe('20건')
  expect(value('요청 성공률')).toBe('75.0%')
  expect(screen.getByText(id, { selector: 'code' })).toBeTruthy()
  expect(screen.getByText('시간 초과')).toBeTruthy()
  expect(screen.getByText(/확인 시각:/).textContent).toMatch(/10:00/)
  expect(screen.getAllByText('800ms', { selector: 'td' })).toHaveLength(2)
})

it('empty, filtered, paginated states have no fabricated values', async () => {
  const send = vi.fn<typeof fetch>(async () => response(page(0)))
  setup(send as typeof fetch)
  expect(
    await screen.findByText(/조건에 맞는 이용 기록이 없습니다/),
  ).toBeTruthy()
  expect(value('요청 성공률')).toBe('—')
  fireEvent.change(screen.getByLabelText('기능'), {
    target: { value: 'welfare' },
  })
  await waitFor(() => expect(send.mock.calls.length).toBe(2))
  expect(String(send.mock.calls[1][0])).toContain('feature=welfare')
  fireEvent.change(screen.getByLabelText('결과'), {
    target: { value: 'failure' },
  })
  await waitFor(() => expect(send.mock.calls.length).toBe(3))
  expect(String(send.mock.calls[2][0])).toContain('outcome=failure')
})

it('a previous response cannot replace the newly filtered page', async () => {
  let resolve!: (value: Response) => void
  const send = vi
    .fn()
    .mockImplementationOnce(
      () =>
        new Promise<Response>((done) => {
          resolve = done
        }),
    )
    .mockImplementation(() => Promise.resolve(response(page(0))))
  setup(send as typeof fetch)
  fireEvent.change(screen.getByLabelText('조회 기간'), {
    target: { value: '1' },
  })
  await screen.findByText(/조건에 맞는 이용 기록이 없습니다/)
  await act(async () => resolve(response(page())))
  expect(value('수집 이벤트')).toBe('0건')
})

it('authorization failures invalidate the current admin session', async () => {
  const connection = setup(vi.fn(async () => response({}, 403)) as typeof fetch)
  await waitFor(() =>
    expect(connection.invalidate).toHaveBeenCalledWith(
      'fixture-session',
      '관리자 권한이 없습니다.',
    ),
  )
})

it('expired-only cleanup requires an explicit click and confirmation', async () => {
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
  const send = vi.fn(async (url: RequestInfo | URL) =>
    response(String(url).endsWith('/prune') ? { removed: 7 } : page()),
  )
  setup(send as typeof fetch)
  await screen.findByText('41건', { selector: 'dd' })
  fireEvent.click(screen.getByText('30일 지난 기록 정리'))
  expect(send).toHaveBeenCalledTimes(1)
  confirm.mockReturnValue(true)
  fireEvent.click(screen.getByText('30일 지난 기록 정리'))
  expect(
    await screen.findByText('기간이 지난 기록 7건을 정리했습니다.'),
  ).toBeTruthy()
  expect(
    send.mock.calls.some((call) => String(call[0]).endsWith('/prune')),
  ).toBe(true)
  confirm.mockRestore()
})

it('malformed or sensitive free text is rejected before display', async () => {
  const bad = {
    ...page(),
    items: [{ ...record(), feature: 'private-health-condition' }],
  }
  const api = createUsageApi(
    createAdminApi(
      'https://example.test',
      vi.fn(async () => response(bad)) as typeof fetch,
    ),
    'fixture-session',
  )
  await expect(
    api.list({ days: 7, feature: '', outcome: '', offset: 0 }),
  ).rejects.toThrow(/응답을 확인/)
})


it('page navigation, retry and failed cleanup retain the selected filter and recover', async () => {
  let failNext = false
  let pruneCalls = 0
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
  const send = vi.fn<typeof fetch>(async (input) => {
    const url = new URL(String(input))
    if (url.pathname.endsWith('/prune')) {
      pruneCalls++
      return response({}, 503)
    }
    if (failNext) { failNext = false; return response({}, 503) }
    return response({ ...page(), offset: Number(url.searchParams.get('offset') ?? 0) })
  })
  setup(send)
  await screen.findByText('41건', { selector: 'dd' })
  fireEvent.click(screen.getByText('다음 페이지'))
  await waitFor(() => expect(screen.getByText('이전 페이지').hasAttribute('disabled')).toBe(false))
  expect(String(send.mock.calls.at(-1)?.[0])).toContain('offset=20')
  failNext = true
  fireEvent.click(screen.getByText('새로고침'))
  await screen.findByRole('alert')
  fireEvent.click(screen.getByText('다시 불러오기'))
  await screen.findByText('41건', { selector: 'dd' })
  expect(String(send.mock.calls.at(-1)?.[0])).toContain('offset=20')
  fireEvent.click(screen.getByText('30일 지난 기록 정리'))
  await screen.findByText('기록을 정리하지 못했습니다. 다시 시도해 주세요.')
  expect(pruneCalls).toBe(1)
  expect(value('수집 이벤트')).toBe('41건')
  expect(screen.getByText('30일 지난 기록 정리').hasAttribute('disabled')).toBe(false)
  fireEvent.click(screen.getByText('이전 페이지'))
  await waitFor(() => expect(String(send.mock.calls.at(-1)?.[0])).toContain('offset=0'))
  confirm.mockRestore()
})
