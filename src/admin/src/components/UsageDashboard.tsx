import { useEffect, useRef, useState } from 'react'
import { ApiError } from '../api'
import {
  actions,
  createUsageApi,
  errors,
  events,
  features,
  outcomes,
} from '../usageApi'
import type { UsageFilter, UsagePage } from '../usageApi'
import type { AdminConnection } from './AccessBoundary'

const resultLabels: Record<string, string> = {
  generated: '답변 생성',
  references_only: '자료만 안내',
  no_evidence: '근거 없음',
}
const settingLabels: Record<string, string> = {
  normal: '보통',
  large: '크게',
  largest: '아주 크게',
  enabled: '사용',
  disabled: '끄기',
}
const stamp = (value: string) =>
  new Date(value).toLocaleString('ko-KR', { timeZone: 'Asia/Seoul' })
export default function UsageDashboard({
  connection,
}: {
  connection: AdminConnection
}) {
  const { api, session, invalidate } = connection
  const [filter, setFilter] = useState<UsageFilter>({
    days: 7,
    feature: '',
    outcome: '',
    offset: 0,
  })
  const [revision, setRevision] = useState(0)
  const [state, setState] = useState<{ data?: UsagePage; error?: string }>({})
  const [pruning, setPruning] = useState(false),
    [notice, setNotice] = useState('')
  const mutation = useRef<AbortController | null>(null)
  useEffect(() => () => mutation.current?.abort(), [])
  useEffect(() => {
    const controller = new AbortController()
    createUsageApi(api, session.token)
      .list(filter, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setState({ data })
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return
        if (cause instanceof ApiError && [401, 403].includes(cause.status)) {
          invalidate(session.token, cause.message)
          return
        }
        setState({
          error:
            cause instanceof ApiError
              ? cause.message
              : '이용 현황을 불러오지 못했습니다.',
        })
      })
    return () => controller.abort()
  }, [api, session.token, filter, revision, invalidate])
  function change(patch: Partial<UsageFilter>) {
    setState({})
    setNotice('')
    setFilter((current) => ({
      ...current,
      ...patch,
      offset: patch.offset ?? 0,
    }))
  }
  function reload() {
    setState({})
    setRevision((n) => n + 1)
  }
  async function prune() {
    if (
      mutation.current ||
      !window.confirm(
        '30일이 지난 이용 기록만 삭제할까요? 최근 기록과 사용자 자료는 유지됩니다.',
      )
    )
      return
    const controller = new AbortController()
    mutation.current = controller
    setPruning(true)
    setNotice('')
    try {
      const removed = await createUsageApi(api, session.token).prune(
        controller.signal,
      )
      if (!controller.signal.aborted) {
        setNotice(`기간이 지난 기록 ${removed}건을 정리했습니다.`)
        reload()
      }
    } catch (cause) {
      if (!controller.signal.aborted) {
        if (cause instanceof ApiError && [401, 403].includes(cause.status))
          invalidate(session.token, cause.message)
        else setNotice('기록을 정리하지 못했습니다. 다시 시도해 주세요.')
      }
    } finally {
      if (!controller.signal.aborted) {
        mutation.current = null
        setPruning(false)
      }
    }
  }
  const data = state.data
  const requests = data?.features.reduce((sum, f) => sum + f.requests, 0) ?? 0
  const failures = data?.features.reduce((sum, f) => sum + f.failure, 0) ?? 0
  const successes = data?.features.reduce((sum, f) => sum + f.success, 0) ?? 0
  const cancelled = data?.features.reduce((sum, f) => sum + f.cancelled, 0) ?? 0
  return (
    <section className="card" aria-labelledby="usage-title">
      <h3 id="usage-title">앱 이용 현황</h3>
      <p>
        이용 기록 전송에 동의한 앱이 보고한 기록입니다. 한국 시간·서버 수집 시각
        기준이며 전체 사용자 수나 고유 사용자 수를 뜻하지 않습니다.
      </p>
      <div className="collection-filters">
        <label>
          조회 기간
          <select
            value={filter.days}
            onChange={(e) => change({ days: Number(e.target.value) })}
          >
            <option value="1">오늘</option>
            <option value="7">최근 7일</option>
            <option value="30">최근 30일</option>
          </select>
        </label>
        <label>
          기능
          <select
            value={filter.feature}
            onChange={(e) => change({ feature: e.target.value })}
          >
            <option value="">전체 기능</option>
            {Object.entries(features).map(([key, value]) => (
              <option key={key} value={key}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <label>
          결과
          <select
            value={filter.outcome}
            onChange={(e) => change({ outcome: e.target.value })}
          >
            <option value="">전체 결과</option>
            {Object.entries(outcomes).map(([key, value]) => (
              <option key={key} value={key}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <button className="secondary-button" onClick={reload}>
          새로고침
        </button>
        <button
          className="secondary-button"
          disabled={pruning}
          onClick={() => void prune()}
        >
          {pruning ? '정리 중…' : '30일 지난 기록 정리'}
        </button>
      </div>
      {notice && <p role="status">{notice}</p>}
      {state.error ? (
        <div role="alert">
          <p>{state.error}</p>
          <button onClick={reload}>다시 불러오기</button>
        </div>
      ) : !data ? (
        <p role="status">이용 현황을 불러오는 중입니다.</p>
      ) : (
        <>
          <p>확인 시각: {stamp(data.checked_at)}</p>
          <dl className="collection-summary">
            <div>
              <dt>수집 이벤트</dt>
              <dd>{data.total.toLocaleString()}건</dd>
            </div>
            <div>
              <dt>완료된 기능 요청</dt>
              <dd>{requests.toLocaleString()}건</dd>
            </div>
            <div>
              <dt>성공 / 실패 / 취소</dt>
              <dd>
                {successes} / {failures} / {cancelled}건
              </dd>
            </div>
            <div>
              <dt>요청 성공률</dt>
              <dd>
                {requests
                  ? `${((successes / requests) * 100).toFixed(1)}%`
                  : '—'}
              </dd>
            </div>
          </dl>
          {data.total === 0 ? (
            <p role="status">
              조건에 맞는 이용 기록이 없습니다. 앱 설정에서 ‘앱 이용 기록
              보내기’를 켜고 기능을 사용하면 표시됩니다.
            </p>
          ) : (
            <>
              <div className="table-scroll">
                <table>
                  <caption>조회 조건 전체의 기능별 요청 현황</caption>
                  <thead>
                    <tr>
                      <th>기능</th>
                      <th>이벤트</th>
                      <th>완료 요청</th>
                      <th>성공</th>
                      <th>실패</th>
                      <th>취소</th>
                      <th>평균 응답</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.features.map((f) => (
                      <tr key={f.feature}>
                        <th scope="row">{features[f.feature]}</th>
                        <td>{f.events}</td>
                        <td>{f.requests}</td>
                        <td>{f.success}</td>
                        <td>{f.failure}</td>
                        <td>{f.cancelled}</td>
                        <td>
                          {f.avg_ms === null
                            ? '—'
                            : `${f.avg_ms.toLocaleString()}ms`}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <details>
                <summary>날짜별 수집 건수</summary>
                <div className="table-scroll">
                  <table>
                    <caption>한국 시간 기준 이벤트 수집 건수</caption>
                    <thead>
                      <tr>
                        <th>날짜</th>
                        <th>건수</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.daily.map((d) => (
                        <tr key={d.day}>
                          <th scope="row">{d.day}</th>
                          <td>{d.count}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>
              <div className="table-scroll">
                <table>
                  <caption>최근 이벤트 · 요청번호로 서버 오류 추적</caption>
                  <thead>
                    <tr>
                      <th>수집 시각</th>
                      <th>기능 / 행동</th>
                      <th>이벤트 / 결과</th>
                      <th>소요 시간</th>
                      <th>오류 분류 / 요청번호</th>
                      <th>앱 / 참고</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.items.map((row) => (
                      <tr key={row.event_id + row.created_at}>
                        <td>{stamp(row.created_at)}</td>
                        <td>
                          {features[row.feature]} / {actions[row.action]}
                        </td>
                        <td>
                          {events[row.event]} / {outcomes[row.outcome]}
                        </td>
                        <td>
                          {row.duration_ms === null
                            ? '—'
                            : `${row.duration_ms}ms`}
                        </td>
                        <td>
                          {row.error_kind ? errors[row.error_kind] : '—'}
                          {row.request_id && (
                            <div>
                              <code>{row.request_id}</code>
                            </div>
                          )}
                        </td>
                        <td>
                          {row.app_version} · {row.platform}
                          {row.result_count !== null && (
                            <div>결과 {row.result_count}건</div>
                          )}
                          {row.result_kind && (
                            <div>{resultLabels[row.result_kind]}</div>
                          )}
                          {row.setting_kind && (
                            <div>
                              {row.setting_kind === 'voice' ? '음성' : '글자'}:{' '}
                              {settingLabels[row.setting_value ?? '']}
                            </div>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="pagination">
                <button
                  className="secondary-button"
                  disabled={filter.offset === 0}
                  onClick={() =>
                    change({ offset: Math.max(0, filter.offset - 20) })
                  }
                >
                  이전 페이지
                </button>
                <span>
                  {filter.offset + 1}–
                  {Math.min(filter.offset + data.items.length, data.total)} /{' '}
                  {data.total}건
                </span>
                <button
                  className="secondary-button"
                  disabled={
                    filter.offset + 20 >= data.total || filter.offset >= 100000
                  }
                  onClick={() => change({ offset: filter.offset + 20 })}
                >
                  다음 페이지
                </button>
              </div>
            </>
          )}
        </>
      )}
      <p className="notice">
        질문·사진·건강정보·레시피/복지 ID·로그인 토큰은 수집하지 않습니다. 요청
        시작과 완료는 별도 이벤트이며 성공률은 완료된 요청 기준입니다. 앱
        종료·오프라인·수집 거절 때문에 기록이 누락될 수 있습니다. 게임 점수와
        외부 영상의 실제 재생 시간은 기록하지 않습니다.
      </p>
    </section>
  )
}
