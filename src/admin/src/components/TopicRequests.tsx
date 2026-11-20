import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError } from '../api'
import { createTopicApi, topicStates } from '../topicApi'
import type { Topic, TopicApi, TopicAudit, TopicDecision, TopicFilter, TopicPage, TopicState } from '../topicApi'
import { createGuideApi } from '../guideApi'
import type { GuideApi, GuidePage, GuideSummary } from '../guideApi'
import type { AdminConnection } from './AccessBoundary'
import StatusMessage from './StatusMessage'

const labels: Record<TopicState, string> = { received: '접수', reviewing: '검토 중', completed: '답변 완료', declined: '보류 안내' }
const kinds = { life_guide: '생활 안내', video: '영상' }
const time = new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', dateStyle: 'medium', timeStyle: 'short' })
const message = (cause: unknown) => cause instanceof ApiError ? cause.message : '요청을 처리하지 못했습니다. 다시 확인해 주세요.'

export default function TopicRequests({ connection, onDirtyChange }: { connection: AdminConnection; onDirtyChange: (value: boolean) => void }) {
  const { api, session, invalidate } = connection
  const topics = useMemo(() => createTopicApi(api, session.token), [api, session.token])
  const guides = useMemo(() => createGuideApi(api, session.token), [api, session.token])
  const [filter, setFilter] = useState<TopicFilter>({ offset: 0 })
  const [query, setQuery] = useState('')
  const [kind, setKind] = useState('')
  const [status, setStatus] = useState('')
  const [selected, setSelected] = useState<string | null>(null)
  const [dirty, setDirty] = useState(false)
  const [refresh, setRefresh] = useState(0)
  const [result, setResult] = useState<{ data?: TopicPage<Topic>; error?: string; loading: boolean }>({ loading: true })
  const changed = useCallback((value: boolean) => { setDirty(value); onDirtyChange(value) }, [onDirtyChange])
  const fail = useCallback((cause: unknown) => {
    if (cause instanceof ApiError && [401, 403].includes(cause.status)) invalidate(session.token, cause.message)
  }, [invalidate, session.token])
  useEffect(() => () => onDirtyChange(false), [onDirtyChange])
  useEffect(() => {
    if (!dirty) return
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])
  useEffect(() => {
    const controller = new AbortController()
    topics.list(filter, controller.signal).then((data) => {
      if (!controller.signal.aborted) setResult({ data, loading: false })
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted) { fail(cause); setResult({ loading: false, error: message(cause) }) }
    })
    return () => controller.abort()
  }, [topics, filter, refresh, fail])
  function discard() { return !dirty || window.confirm('저장하지 않은 답변을 버리고 이동할까요?') }
  function reload() { setResult({ loading: true }); setRefresh((value) => value + 1) }
  function select(value: string | null) { if (selected === value || !discard()) return; changed(false); setSelected(value) }
  function move(offset: number) {
    if (!discard()) return
    changed(false); setSelected(null); setResult({ loading: true }); setFilter((current) => ({ ...current, offset }))
  }
  function search(event: FormEvent) {
    event.preventDefault()
    if (!discard()) return
    changed(false); setSelected(null); setResult({ loading: true })
    setFilter({ offset: 0, q: query, kind: kind ? kind as TopicFilter['kind'] : undefined, status: status ? status as TopicState : undefined })
  }
  return <div className="guide-workspace">
    <section className="card">
      <div className="guide-toolbar"><h3>주제 요청 처리함</h3><button className="secondary-button" onClick={reload}>요청 목록 새로고침</button></div>
      <p>앱에서 명시적으로 보낸 주제를 확인합니다. 취소한 요청과 사용자 프로필은 표시하지 않습니다. 영상의 답변 완료는 영상 자동 제작·게시가 아닙니다.</p>
      <form className="collection-filters" onSubmit={search}>
        <label>요청 종류<select value={kind} onChange={(event) => setKind(event.target.value)}><option value="">전체 종류</option><option value="life_guide">생활 안내</option><option value="video">영상</option></select></label>
        <label>주제 검색<input value={query} maxLength={100} onChange={(event) => setQuery(event.target.value)} /></label>
        <label>처리 상태<select value={status} onChange={(event) => setStatus(event.target.value)}><option value="">전체 상태</option>{topicStates.map((value) => <option key={value} value={value}>{labels[value]}</option>)}</select></label>
        <button className="retry-button" type="submit">요청 검색</button>
      </form>
      {result.loading ? <StatusMessage status="loading" /> : result.error ? <p role="alert">{result.error}</p> : <>
        <p role="status">요청 {result.data?.total ?? 0}건</p>
        {result.data?.items.length === 0 && <p>조건에 맞는 요청이 없습니다.</p>}
        <ul className="guide-list">{result.data?.items.map((row) => <li key={row.id}><button className="guide-select" aria-pressed={selected === row.id} onClick={() => select(row.id)}><strong>{row.topic}</strong><span>{kinds[row.kind]} · {labels[row.status]}</span><small>{time.format(new Date(row.created_at))} · 판본 {row.version}</small></button></li>)}</ul>
        <div className="pagination"><button className="secondary-button" disabled={!filter.offset} onClick={() => move(Math.max(0, (filter.offset ?? 0) - 20))}>이전 요청</button><button className="secondary-button" disabled={(filter.offset ?? 0) + 20 >= (result.data?.total ?? 0) || (filter.offset ?? 0) >= 10000} onClick={() => move((filter.offset ?? 0) + 20)}>다음 요청</button></div>
      </>}
    </section>
    {selected && <TopicEditor key={`${session.userId}:${selected}`} id={selected} api={topics} guides={guides} onDirty={changed} onFailure={fail} onSaved={reload} onClose={() => select(null)} />}
  </div>
}

function TopicEditor({ id, api, guides, onDirty, onFailure, onSaved, onClose }: {
  id: string; api: TopicApi; guides: GuideApi; onDirty: (value: boolean) => void;
  onFailure: (cause: unknown) => void; onSaved: () => void; onClose: () => void;
}) {
  const [row, setRow] = useState<Topic | null>(null)
  const [status, setStatus] = useState<TopicDecision['status']>('reviewing')
  const [reply, setReply] = useState('')
  const [guideId, setGuideId] = useState('')
  const [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [blocked, setBlocked] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [refresh, setRefresh] = useState(0)
  const [auditOffset, setAuditOffset] = useState(0)
  const [audit, setAudit] = useState<TopicPage<TopicAudit> | null>(null)
  const [auditError, setAuditError] = useState('')
  const [auditRefresh, setAuditRefresh] = useState(0)
  const operation = useRef<AbortController | null>(null)
  const failure = useRef(onFailure)
  const saved = useRef(onSaved)
  useEffect(() => { failure.current = onFailure }, [onFailure])
  useEffect(() => { saved.current = onSaved }, [onSaved])
  const forget = useCallback(() => {
    setRow(null); setReply(''); setGuideId(''); setDirty(false); setAudit(null)
    saved.current()
  }, [])
  useEffect(() => { onDirty(dirty); return () => onDirty(false) }, [dirty, onDirty])
  useEffect(() => () => operation.current?.abort(), [])
  function apply(value: Topic) {
    setRow(value); setStatus(value.status === 'received' ? 'reviewing' : value.status)
    setReply(value.reply ?? ''); setGuideId(value.guide_id ?? ''); setDirty(false); setBlocked(false)
  }
  useEffect(() => {
    const controller = new AbortController()
    api.get(id, controller.signal).then((value) => { if (!controller.signal.aborted) { apply(value); setLoading(false) } }).catch((cause: unknown) => {
      if (!controller.signal.aborted) {
        failure.current(cause); setError(message(cause)); setLoading(false); setBlocked(true)
        if (cause instanceof ApiError && cause.status === 404) forget()
      }
    })
    return () => controller.abort()
  }, [api, id, refresh, forget])
  useEffect(() => {
    if (!row) return
    const controller = new AbortController()
    api.audit(id, auditOffset, controller.signal).then((value) => { if (!controller.signal.aborted) { setAudit(value); setAuditError('') } }).catch((cause: unknown) => {
      if (!controller.signal.aborted) {
        failure.current(cause); setAudit(null); setAuditError(message(cause))
        if (cause instanceof ApiError && cause.status === 404) forget()
      }
    })
    return () => controller.abort()
  }, [api, id, row, auditOffset, refresh, auditRefresh, forget])
  function latest() {
    if (busy || (dirty && !window.confirm('저장하지 않은 답변을 버리고 최신 내용을 불러올까요?'))) return
    setLoading(true); setError(''); setNotice(''); setAudit(null); setAuditError(''); setRefresh((value) => value + 1)
  }
  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!row || operation.current || blocked) return
    if ((status !== 'reviewing' && !reply.trim()) || [...reply].length > 1000 || reply.includes('\0')) { setError('완료·보류 답변을 1~1,000자로 작성해 주세요.'); return }
    if (status === 'completed' && row.kind === 'life_guide' && !guideId) { setError('승인·게시한 생활 가이드를 연결해 주세요.'); return }
    const controller = new AbortController(); operation.current = controller; setBusy(true); setError(''); setNotice(''); setDirty(true)
    try {
      const value = await api.review(row.id, row.version, { status, reply: reply.trim() || null, guide_id: status === 'completed' && row.kind === 'life_guide' ? guideId : null }, controller.signal)
      if (!controller.signal.aborted) { apply(value); setAudit(null); setAuditOffset(0); setNotice('처리 내용을 저장했습니다. 사용자가 앱에서 답변을 확인할 수 있습니다.'); onSaved() }
    } catch (cause: unknown) {
      if (!controller.signal.aborted) {
        failure.current(cause)
        const uncertain = !(cause instanceof ApiError) || cause.status === 0 || cause.status >= 500
        setBlocked(uncertain || (cause instanceof ApiError && [404, 409].includes(cause.status)))
        setError(uncertain ? '처리 결과를 확인하지 못했습니다. 다시 저장하기 전에 최신 내용을 불러와 확인해 주세요.' : message(cause))
        if (cause instanceof ApiError && cause.status === 404) forget()
      }
    } finally {
      if (operation.current === controller) operation.current = null
      if (!controller.signal.aborted) setBusy(false)
    }
  }
  const options = row?.status === 'completed' || row?.status === 'declined' ? ['reviewing', row.status] as const : ['reviewing', 'completed', 'declined'] as const
  return <section className="card guide-editor" aria-busy={loading || busy} aria-labelledby="topic-detail-title">
    <div className="guide-toolbar"><h3 id="topic-detail-title">요청 상세·답변</h3><button className="secondary-button" disabled={busy} onClick={onClose}>요청 상세 닫기</button></div>
    {loading ? <StatusMessage status="loading" /> : <>
      {row && <><h4>{row.topic}</h4><p>{kinds[row.kind]} · {labels[row.status]} · 판본 {row.version}</p><p>접수 {time.format(new Date(row.created_at))} · 최근 변경 {time.format(new Date(row.updated_at))}</p></>}
      {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
      <button className="secondary-button" disabled={busy} onClick={latest}>최신 요청 불러오기</button>
      {row && <form className="guide-form" onSubmit={submit}><fieldset disabled={busy || blocked}>
        <label>변경할 처리 상태<select value={status} onChange={(event) => { setStatus(event.target.value as TopicDecision['status']); setDirty(true) }}>{options.map((value) => <option key={value} value={value}>{labels[value]}</option>)}</select></label>
        {(row.status === 'completed' || row.status === 'declined') && <p>완료와 보류를 서로 바꾸려면 먼저 검토 중으로 저장해 주세요.</p>}
        <label>운영자 답변<textarea value={reply} rows={5} maxLength={2000} onChange={(event) => { setReply(event.target.value); setDirty(true) }} /></label>
        <p>{[...reply].length}/1,000자 · 완료·보류에는 답변이 필요합니다.</p>
        {row.kind === 'life_guide' && status === 'completed' && <GuidePicker api={guides} selected={guideId} current={row} onChange={(value) => { setGuideId(value); setDirty(true) }} onFailure={onFailure} />}
        {row.kind === 'video' && <p>영상 요청 답변은 제작·게시를 자동으로 실행하지 않습니다.</p>}
        <button className="retry-button" type="submit" disabled={busy || blocked}>{busy ? '답변 저장 중…' : '처리 내용 저장'}</button>
      </fieldset></form>}
      <h4>처리 이력</h4>{auditError ? <><p role="alert">{auditError}</p>{row && <button className="secondary-button" onClick={() => setAuditRefresh((value) => value + 1)}>처리 이력 다시 확인</button>}</> : !row ? <p>조회 가능한 요청이 없습니다.</p> : !audit ? <p>처리 이력을 확인하고 있습니다.</p> : <>
        <ol className="guide-audit">{audit.items.map((item) => <li key={item.id}>{time.format(new Date(item.created_at))} · {item.action === 'create' ? '접수' : item.action === 'review' ? '검토·답변' : '취소'}<br />상태 {String(item.after_state.status ?? '확인 필요')} · 판본 {String(item.after_state.version ?? '확인 필요')}<br /><small>서버 요청 번호 {item.request_id}</small></li>)}</ol>
        <div className="pagination"><button className="secondary-button" disabled={auditOffset === 0} onClick={() => { setAudit(null); setAuditOffset(Math.max(0, auditOffset - 20)) }}>이전 이력</button><button className="secondary-button" disabled={auditOffset + 20 >= audit.total || auditOffset >= 10000} onClick={() => { setAudit(null); setAuditOffset(auditOffset + 20) }}>다음 이력</button></div>
      </>}
    </>}
  </section>
}

function GuidePicker({ api, selected, current, onChange, onFailure }: { api: GuideApi; selected: string; current: Topic; onChange: (value: string) => void; onFailure: (cause: unknown) => void }) {
  const [search, setSearch] = useState('')
  const [query, setQuery] = useState({ q: '', offset: 0 })
  const [page, setPage] = useState<GuidePage<GuideSummary> | null>(null)
  const [error, setError] = useState('')
  const failure = useRef(onFailure)
  useEffect(() => { failure.current = onFailure }, [onFailure])
  useEffect(() => {
    const controller = new AbortController()
    api.list({ ...query, is_published: true, review_status: 'approved' }, controller.signal).then((value) => {
      if (value.items.some((item) => !item.is_published || item.review_status !== 'approved')) throw new ApiError(0, '안내의 게시 상태를 확인하지 못했습니다. 다시 조회해 주세요.', true)
      if (!controller.signal.aborted) { setPage(value); setError('') }
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted) { failure.current(cause); setError(message(cause)) }
    })
    return () => controller.abort()
  }, [api, query])
  function move(q: string, offset: number) { setPage(null); setError(''); setQuery({ q, offset }) }
  return <div className="guide-step"><h4>게시된 생활 가이드 연결</h4>
    <label>연결할 안내 검색<input value={search} maxLength={100} onChange={(event) => setSearch(event.target.value)} /></label>
    <button className="secondary-button" type="button" onClick={() => move(search, 0)}>게시 안내 검색</button>
    {error && <p role="alert">{error}</p>}{!page && !error && <p>게시된 안내를 확인하고 있습니다.</p>}
    <label>연결할 생활 가이드<select value={selected} onChange={(event) => onChange(event.target.value)}><option value="">안내를 선택해 주세요</option>
      {selected && !page?.items.some((item) => item.id === selected) && <option value={selected}>{current.guide?.id === selected ? current.guide.title : '기존 선택 · 게시 여부를 다시 확인해 주세요'}</option>}
      {page?.items.map((item) => <option key={item.id} value={item.id}>{item.title} · {item.checked_on}</option>)}
    </select></label>
    {current.guide_id && current.guide === null && <p>기존 연결 안내는 현재 게시되어 있지 않습니다. 게시 안내를 다시 선택해 주세요.</p>}
    {page?.items.length === 0 && <p>게시된 안내가 없습니다. 콘텐츠 검수에서 승인·게시 후 다시 조회해 주세요.</p>}
    {page && <div className="pagination"><button className="secondary-button" type="button" disabled={query.offset === 0} onClick={() => move(query.q, Math.max(0, query.offset - 20))}>이전 게시 안내</button><button className="secondary-button" type="button" disabled={query.offset + 20 >= page.total || query.offset >= 10000} onClick={() => move(query.q, query.offset + 20)}>다음 게시 안내</button></div>}
  </div>
}
