import { jobStatusLabels } from '../api'
import type { JobPage } from '../api'
import StatusMessage from './StatusMessage'

const formatter = new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', dateStyle: 'medium', timeStyle: 'short' })
function time(value: string | null) { return value === null ? '—' : formatter.format(new Date(value)) }

export default function CollectionOverview({ page }: { page: JobPage }) {
  const processed = page.items.map((job) => job.finished_at ?? job.started_at ?? job.created_at)
  const latest = processed.reduce<string | null>((current, value) => current === null || Date.parse(value) > Date.parse(current) ? value : current, null)
  const failed = page.items.filter((job) => job.status === 'failed').length
  const pending = page.items.filter((job) => job.status === 'queued' || job.status === 'running').length
  return (
    <div className="collection-overview">
      <dl className="collection-summary" aria-label="수집 작업 요약">
        <div><dt>조회 조건에 맞는 작업</dt><dd>{page.total}건</dd></div>
        <div><dt>현재 페이지 최근 기록 · 한국시간</dt><dd>{time(latest)}</dd></div>
        <div><dt>현재 페이지 실패</dt><dd>{failed}건</dd></div>
        <div><dt>현재 페이지 대기·실행</dt><dd>{pending}건</dd></div>
      </dl>
      <p>전체 작업 수는 조회 조건에 맞는 건수입니다. 최근 기록 시각과 상태별 건수는 현재 페이지의 작업을 기준으로 표시합니다.</p>
      {page.items.length === 0 ? <StatusMessage status="empty" message="조건에 맞는 수집 작업이 없습니다. 작업 기록이 없는 경우에도 이렇게 표시됩니다." /> : (
        <div className="collection-table-wrapper">
          <table className="collection-table">
            <caption>수집 작업 상태와 실행 시각 (한국 시간)</caption>
            <thead><tr><th scope="col">작업 ID</th><th scope="col">상태</th><th scope="col">시도</th><th scope="col">생성</th><th scope="col">시작 / 종료</th><th scope="col">실패 단계</th><th scope="col">다음 실행 시각</th></tr></thead>
            <tbody>{page.items.map((job) => <tr key={job.id}>
              <th scope="row"><code title={job.id}>{job.id.slice(0, 8)}</code></th>
              <td><span className={`job-status job-${job.status}`}>{jobStatusLabels[job.status]}</span></td>
              <td>{job.attempts}</td><td>{time(job.created_at)}</td>
              <td>{time(job.started_at)}<br />{time(job.finished_at)}</td>
              <td>{job.error_code ?? '—'}</td><td>{time(job.next_run_at)}</td>
            </tr>)}</tbody>
          </table>
        </div>
      )}
    </div>
  )
}
