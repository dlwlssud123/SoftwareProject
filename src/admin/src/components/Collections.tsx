import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError, jobStatuses, jobStatusLabels } from '../api'
import type { JobPage, JobStatus } from '../api'
import type { AdminConnection } from './AccessBoundary'
import CollectionOverview from './CollectionOverview'
import StatusMessage from './StatusMessage'

export default function Collections({ connection }: { connection: AdminConnection }) {
  const { api, session, invalidate } = connection
  const [filter, setFilter] = useState<{ status?: JobStatus; q: string; offset: number }>({ q: '', offset: 0 })
  const [status, setStatus] = useState('')
  const [query, setQuery] = useState('')
  const [refresh, setRefresh] = useState(0)
  const [result, setResult] = useState<{ data?: JobPage; error?: string; loading: boolean }>({ loading: true })

  useEffect(() => {
    const controller = new AbortController()
    api.jobs(session.token, filter, controller.signal).then((data) => {
      if (!controller.signal.aborted) setResult({ data, loading: false })
    }).catch((cause: unknown) => {
      if (controller.signal.aborted) return
      if (cause instanceof ApiError && [401, 403].includes(cause.status)) { invalidate(session.token, cause.message); return }
      setResult({ error: cause instanceof ApiError ? cause.message : '수집 현황을 불러오지 못했습니다.', loading: false })
    })
    return () => controller.abort()
  }, [api, session.token, filter, refresh, invalidate])

  function search(event: FormEvent) {
    event.preventDefault()
    setResult({ loading: true })
    setFilter({ status: status ? status as JobStatus : undefined, q: query.trim(), offset: 0 })
  }
  function reload() { setResult({ loading: true }); setRefresh((n) => n + 1) }
  function move(offset: number) { setResult({ loading: true }); setFilter((current) => ({ ...current, offset })) }

  return <section className="card" aria-labelledby="collection-title">
    <h3 id="collection-title">공공데이터 수집 작업</h3>
    <p>한국 시간 기준입니다. 공통 데이터 갱신 작업만 표시하며 개인 사진·AI 작업은 포함하지 않습니다.</p>
    <form className="collection-filters" onSubmit={search}>
      <label>처리 상태<select value={status} onChange={(event) => setStatus(event.target.value)}>
        <option value="">전체</option>{jobStatuses.map((value) => <option key={value} value={value}>{jobStatusLabels[value]}</option>)}
      </select></label>
      <label>실패 단계 코드<input value={query} onChange={(event) => setQuery(event.target.value)} maxLength={100} placeholder="예: import_welfare" /></label>
      <button type="submit" className="retry-button">조회</button>
      <button type="button" className="secondary-button" onClick={reload}>새로고침</button>
    </form>
    {result.loading ? <StatusMessage status="loading" /> : result.error ?
      <StatusMessage status="error" message={result.error} onRetry={reload} /> : result.data && <>
        <p role="status">조회 결과 {result.data.total}건</p>
        <CollectionOverview page={result.data} />
        <div className="pagination">
          <button className="secondary-button" disabled={filter.offset === 0} onClick={() => move(Math.max(0, filter.offset - 20))}>이전 페이지</button>
          <button className="secondary-button" disabled={filter.offset + 20 >= result.data.total || filter.offset >= 10000} onClick={() => move(filter.offset + 20)}>다음 페이지</button>
        </div>
      </>}
    <p className="notice">성공은 기록된 작업의 전체 상태입니다. 단계별 건수·RAG 검증·자료 갱신 여부는 실행 결과를 함께 확인하세요. 이 화면은 수집 시작·재시도·예약 설치를 수행하지 않습니다.</p>
  </section>
}
