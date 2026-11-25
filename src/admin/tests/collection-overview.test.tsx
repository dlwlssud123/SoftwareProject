import { render, screen, within } from '@testing-library/react'
import { expect, it } from 'vitest'
import CollectionOverview from '../src/components/CollectionOverview'
import type { DataJob, JobPage } from '../src/api'

function job(index: number, changes: Partial<DataJob> = {}): DataJob {
  return { id: `00000000-0000-4000-8000-${String(index).padStart(12, '0')}`, status: 'succeeded', attempts: 1,
    created_at: '2026-11-23T13:00:00Z', started_at: '2026-11-23T13:05:00Z', finished_at: '2026-11-23T15:00:00Z',
    next_run_at: '2026-11-24T15:00:00Z', error_code: null, ...changes }
}
function value(label: string) {
  return within(screen.getByText(label, { selector: 'dt' }).parentElement as HTMLElement).getByRole('definition').textContent
}

it('필터 전체 건수와 현재 페이지 상태 건수를 구분하고 한국 시간으로 최근 기록를 표시한다', () => {
  const page: JobPage = { total: 100, offset: 20, limit: 20, items: [
    job(1, { status: 'failed', finished_at: '2026-11-23T15:10:00Z', error_code: 'import_welfare' }),
    job(2, { status: 'running', finished_at: null, started_at: '2026-11-23T14:30:00Z' }),
    job(3, { status: 'queued', finished_at: null, started_at: null, created_at: '2026-11-23T14:45:00Z' }),
    job(4),
  ] }
  render(<CollectionOverview page={page} />)
  expect(value('조회 조건에 맞는 작업')).toBe('100건')
  expect(value('현재 페이지 실패')).toBe('1건')
  expect(value('현재 페이지 대기·실행')).toBe('2건')
  expect(value('현재 페이지 최근 기록 · 한국시간')).toMatch(/2026\. 11\. 24\..*12:10/)
  const table = screen.getByRole('table')
  expect(within(table).getAllByRole('rowheader')).toHaveLength(4)
  expect(within(table).getByText('import_welfare')).toBeTruthy()
  expect(within(table).getAllByRole('columnheader')).toHaveLength(7)
  expect(screen.queryByText(/가상 데이터/)).toBeNull()
})

it('빈 결과는 이전 시간이나 가상 수치를 채우지 않는다', () => {
  render(<CollectionOverview page={{ total: 0, items: [], limit: 20, offset: 0 }} />)
  expect(value('조회 조건에 맞는 작업')).toBe('0건')
  expect(value('현재 페이지 최근 기록 · 한국시간')).toBe('—')
  expect(value('현재 페이지 실패')).toBe('0건')
  expect(value('현재 페이지 대기·실행')).toBe('0건')
  expect(screen.getByRole('status').textContent).toMatch(/조건에 맞는 수집 작업이 없습니다/)
  expect(screen.queryByRole('table')).toBeNull()
})

it('다음 페이지 응답으로 요약과 행을 함께 교체한다', () => {
  const view = render(<CollectionOverview page={{ total: 21, items: [job(1, { status: 'failed', error_code: 'first_page_failure' })], offset: 0, limit: 20 }} />)
  expect(value('현재 페이지 실패')).toBe('1건')
  view.rerender(<CollectionOverview page={{ total: 21, items: [job(2, { status: 'running', finished_at: null })], offset: 20, limit: 20 }} />)
  expect(value('현재 페이지 실패')).toBe('0건')
  expect(value('현재 페이지 대기·실행')).toBe('1건')
  expect(screen.queryByText('first_page_failure')).toBeNull()
})
