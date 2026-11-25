import { useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError } from '../api'
import { createGuideApi, reviewStatuses } from '../guideApi'
import type { GuideAction, GuideApi, GuideContent, GuideDetail, GuideFilter, GuidePage, GuideSummary, ReviewStatus } from '../guideApi'
import type { AdminConnection } from './AccessBoundary'
import StatusMessage from './StatusMessage'

const reviewLabels: Record<ReviewStatus, string> = { draft: '초안', review: '검수 대기', approved: '승인', rejected: '반려' }
const actionLabels = { create: '초안 작성', edit: '내용 수정', submit: '검수 요청', approve: '승인', reject: '반려', publish: '게시', unpublish: '비공개' }
const time = new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', dateStyle: 'medium', timeStyle: 'short' })
function message(cause: unknown) { return cause instanceof ApiError ? cause.message : '가이드 작업을 처리하지 못했습니다.' }
function today() { return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date()) }

export default function Guides({ connection, onDirtyChange }: { connection: AdminConnection; onDirtyChange: (dirty: boolean) => void }) {
  const { api, session, invalidate } = connection
  const guides = useMemo(() => createGuideApi(api, session.token), [api, session.token])
  const [selection, setSelection] = useState<string | null>(null)
  const [draftSequence, setDraftSequence] = useState(0)
  const [filter, setFilter] = useState<GuideFilter>({ offset: 0 })
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState('')
  const [refresh, setRefresh] = useState(0)
  const [result, setResult] = useState<{ data?: GuidePage<GuideSummary>; error?: string; loading: boolean }>({ loading: true })
  const [dirty, setDirty] = useState(false)
  function fail(cause: unknown) {
    if (cause instanceof ApiError && [401, 403].includes(cause.status)) invalidate(session.token, cause.message)
  }
  useEffect(() => { onDirtyChange(dirty); return () => onDirtyChange(false) }, [dirty, onDirtyChange])
  useEffect(() => {
    if (!dirty) return
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])
  useEffect(() => {
    const controller = new AbortController()
    guides.list(filter, controller.signal).then((data) => {
      if (!controller.signal.aborted) setResult({ data, loading: false })
    }).catch((cause: unknown) => {
      if (controller.signal.aborted) return
      if (cause instanceof ApiError && [401, 403].includes(cause.status)) { invalidate(session.token, cause.message); return }
      setResult({ loading: false, error: message(cause) })
    })
    return () => controller.abort()
  }, [guides, filter, refresh, invalidate, session.token])
  function reload() { setResult({ loading: true }); setRefresh((n) => n + 1) }
  function select(value: string | null) {
    if (selection === value && value !== 'new') return
    if (dirty && !window.confirm('저장하지 않은 변경을 버리고 이동할까요?')) return
    setDirty(false); setSelection(value)
    if (value === 'new') setDraftSequence((current) => current + 1)
  }
  function search(event: FormEvent) {
    event.preventDefault(); setResult({ loading: true })
    setFilter({ q: query.trim(), review_status: status ? status as ReviewStatus : undefined, offset: 0 })
  }
  return <div className="guide-workspace">
    <section className="card" aria-labelledby="guide-list-title">
      <div className="guide-toolbar"><h3 id="guide-list-title">생활 가이드</h3>
        <button className="retry-button" onClick={() => select('new')}>새 가이드 작성</button></div>
      <p>검수 승인은 게시와 별개입니다. 승인 후 게시한 자료만 앱에 표시됩니다.</p>
      <form className="collection-filters" onSubmit={search}>
        <label>검수 상태<select value={status} onChange={(event) => setStatus(event.target.value)}>
          <option value="">전체</option>{reviewStatuses.map((s) => <option key={s} value={s}>{reviewLabels[s]}</option>)}
        </select></label>
        <label>가이드 제목 검색<input value={query} maxLength={100} onChange={(event) => setQuery(event.target.value)} /></label>
        <button className="retry-button" type="submit">가이드 조회</button>
        <button className="secondary-button" type="button" onClick={reload}>목록 새로고침</button>
      </form>
      {result.loading ? <StatusMessage status="loading" /> : result.error ? <StatusMessage status="error" message={result.error} onRetry={reload} /> : result.data && <>
        <p role="status">가이드 {result.data.total}건</p>
        {!result.data.items.length ? <StatusMessage status="empty" message="조건에 맞는 가이드가 없습니다." /> :
          <ul className="guide-list">{result.data.items.map((guide) => <li key={guide.id}>
            <button className="guide-select" aria-pressed={selection === guide.id} onClick={() => select(guide.id)}>
              <strong>{guide.title}</strong><span>{reviewLabels[guide.review_status]} · {guide.is_published ? '게시 중' : '비공개'} · 판본 {guide.version}</span>
              <small>확인일 {guide.checked_on} · 수정 {time.format(new Date(guide.updated_at))}</small>
            </button>
          </li>)}</ul>}
        <div className="pagination">
          <button className="secondary-button" disabled={!filter.offset} onClick={() => { setResult({ loading: true }); setFilter({ ...filter, offset: Math.max(0, (filter.offset ?? 0) - 20) }) }}>가이드 이전 페이지</button>
          <button className="secondary-button" disabled={(filter.offset ?? 0) + 20 >= result.data.total || (filter.offset ?? 0) >= 10000} onClick={() => { setResult({ loading: true }); setFilter({ ...filter, offset: (filter.offset ?? 0) + 20 }) }}>가이드 다음 페이지</button>
        </div>
      </>}
    </section>
    {selection !== null && <GuideEditor key={selection === 'new' ? `new-${draftSequence}` : selection} guideId={selection} api={guides} onDirty={setDirty} onFailure={fail}
      onSaved={reload} onClose={() => select(null)} />}
  </div>
}

function GuideEditor({ guideId, api, onDirty, onFailure, onSaved, onClose }: {
  guideId: string; api: GuideApi; onDirty: (value: boolean) => void; onFailure: (cause: unknown) => void; onSaved: () => void; onClose: () => void;
}) {
  const [row, setRow] = useState<GuideDetail | null>(null)
  const [slug, setSlug] = useState('')
  const [content, setContent] = useState<GuideContent>({ title: '', source_reference: '', checked_on: today(), steps: [{ text: '' }] })
  const [dirty, setDirty] = useState(false)
  const [loading, setLoading] = useState(guideId !== 'new')
  const [busy, setBusy] = useState(false)
  const [conflict, setConflict] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [note, setNote] = useState('')
  const [refresh, setRefresh] = useState(0)
  const [auditOffset, setAuditOffset] = useState(0)
  const [audit, setAudit] = useState<Awaited<ReturnType<GuideApi['audit']>> | null>(null)
  const [auditError, setAuditError] = useState('')
  const operation = useRef<AbortController | null>(null)
  const createdId = useRef<string | null>(null)
  const failure = useRef(onFailure)
  useEffect(() => { failure.current = onFailure }, [onFailure])
  useEffect(() => () => operation.current?.abort(), [])
  useEffect(() => { onDirty(dirty || busy || note.length > 0) }, [dirty, busy, note, onDirty])
  function apply(value: GuideDetail) {
    setRow(value); setSlug(value.slug)
    setContent({ title: value.title, source_reference: value.source_reference, checked_on: value.checked_on, steps: value.steps })
    setDirty(false); setConflict(false); setNote('')
  }
  useEffect(() => {
    const target = guideId === 'new' ? createdId.current : guideId
    if (target === null) return
    const controller = new AbortController()
    api.get(target, controller.signal).then((value) => { if (!controller.signal.aborted) { apply(value); setLoading(false) } }).catch((cause: unknown) => {
      if (!controller.signal.aborted) { failure.current(cause); setError(message(cause)); setLoading(false) }
    })
    return () => controller.abort()
  }, [api, guideId, refresh])
  useEffect(() => {
    if (!row) return
    const controller = new AbortController()
    api.audit(row.id, auditOffset, controller.signal).then((value) => { if (!controller.signal.aborted) { setAudit(value); setAuditError('') } }).catch((cause: unknown) => {
      if (!controller.signal.aborted) { failure.current(cause); setAuditError(message(cause)) }
    })
    return () => controller.abort()
  }, [api, row, auditOffset, refresh])
  function update(value: Partial<GuideContent>) { setContent((current) => ({ ...current, ...value })); setDirty(true); setNotice('') }
  function latest() {
    if ((dirty || note.length > 0) && !window.confirm('저장하지 않은 변경을 버리고 최신 내용을 불러올까요?')) return
    setError(''); setNotice(''); setLoading(true); setAudit(null); setAuditError(''); setRefresh((n) => n + 1)
  }
  async function perform(action?: GuideAction) {
    if (operation.current || conflict) return
    const controller = new AbortController(); operation.current = controller; setBusy(true); setError(''); setNotice('')
    try {
      const value = action && row ? await api.action(row.id, action, row.version, note.trim() || undefined, controller.signal) :
        row ? await api.edit(row.id, content, row.version, controller.signal) : await api.create({ ...content, slug }, controller.signal)
      if (controller.signal.aborted) return
      createdId.current = value.id
      apply(value); setAudit(null); setAuditOffset(0); onSaved()
      setNotice(action ? `${actionLabels[action]} 처리했습니다.${action === 'approve' ? ' 앱에 표시하려면 게시를 눌러 주세요.' : ''}` : '초안을 저장했습니다. 검수와 게시가 필요합니다.')
    } catch (cause: unknown) {
      if (controller.signal.aborted) return
      failure.current(cause)
      const uncertain = !(cause instanceof ApiError) || cause.status === 0 || cause.status >= 500
      setConflict(uncertain || (cause instanceof ApiError && cause.status === 409 && row !== null))
      setError(uncertain ? '처리 결과를 확인하지 못했습니다. 중복 요청을 막기 위해 최신 내용이나 목록에서 저장 여부를 확인해 주세요.' : message(cause))
    } finally {
      if (operation.current === controller) operation.current = null
      if (!controller.signal.aborted) setBusy(false)
    }
  }
  const available: GuideAction[] = row ? row.is_published ? ['unpublish'] : row.review_status === 'review' ? ['approve', 'reject'] : row.review_status === 'approved' ? ['publish'] : ['submit'] : []
  return <section className="card guide-editor" aria-labelledby="guide-editor-title" aria-busy={loading || busy}>
    <div className="guide-toolbar"><h3 id="guide-editor-title">{row ? '가이드 상세·검수' : '가이드 초안 작성'}</h3><button className="secondary-button" disabled={busy} onClick={onClose}>상세 닫기</button></div>
    {loading ? <StatusMessage status="loading" /> : <>
      {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
      {(row || (guideId !== 'new' && !loading)) && <button className="secondary-button" disabled={busy} onClick={latest}>최신 내용 불러오기</button>}
      {conflict && <p className="notice">입력 내용은 유지됩니다. 다시 저장하기 전에 최신 내용을 확인하세요. 새로 작성한 자료는 목록에서 저장 여부를 확인한 뒤 다시 여세요.</p>}
      {(row || guideId === 'new') && <>
        {row && <p>{reviewLabels[row.review_status]} · {row.is_published ? '게시 중' : '비공개'} · 판본 {row.version}</p>}
        {row?.review_note && <p className="notice">검수 의견: {row.review_note}</p>}
        <form className="guide-form" onSubmit={(event) => { event.preventDefault(); void perform() }}>
          <fieldset disabled={busy || conflict}>
            <label>가이드 주소<input value={slug} required maxLength={128} pattern="[a-z0-9]+(-[a-z0-9]+)*" disabled={row !== null} onChange={(event) => { setSlug(event.target.value); setDirty(true) }} /></label>
            <small>영문 소문자·숫자·하이픈을 사용하며 생성 후 주소는 바꿀 수 없습니다.</small>
            <label>제목<input required value={content.title} maxLength={200} onChange={(event) => update({ title: event.target.value })} /></label>
            <label>출처<textarea required value={content.source_reference} maxLength={1000} rows={2} onChange={(event) => update({ source_reference: event.target.value })} /></label>
            <label>자료 확인일<input type="date" required max={today()} value={content.checked_on} onChange={(event) => update({ checked_on: event.target.value })} /></label>
            {content.steps.map((step, index) => <fieldset className="guide-step" key={index}>
              <legend>단계 {index + 1}</legend>
              <label>단계 {index + 1} 제목 (선택)<input value={step.title ?? ''} maxLength={120} onChange={(event) => update({ steps: content.steps.map((s, i) => i === index ? { text: s.text, ...(event.target.value.trim() ? { title: event.target.value } : {}) } : s) })} /></label>
              <label>단계 {index + 1} 설명<textarea required value={step.text} rows={4} maxLength={3000} onChange={(event) => update({ steps: content.steps.map((s, i) => i === index ? { ...s, text: event.target.value } : s) })} /></label>
              <button type="button" className="secondary-button" disabled={content.steps.length === 1} onClick={() => update({ steps: content.steps.filter((_, i) => i !== index) })}>단계 {index + 1} 삭제</button>
            </fieldset>)}
            <button type="button" className="secondary-button" disabled={content.steps.length >= 30} onClick={() => update({ steps: [...content.steps, { text: '' }] })}>단계 추가</button>
            <p>내용을 저장하면 검수 상태가 초안으로 바뀌고 게시 중인 자료도 비공개로 전환됩니다.</p>
            <button type="submit" className="retry-button" disabled={busy || conflict || (row !== null && !dirty)}>{busy ? '처리 중…' : '초안 저장'}</button>
          </fieldset>
        </form>
        {row && <section aria-labelledby="guide-review-title">
          <h4 id="guide-review-title">검수·게시</h4>
          {dirty && <p>변경한 내용을 먼저 저장한 뒤 검수해 주세요.</p>}
          {row.review_status === 'review' && !row.is_published && <label>검수 의견<textarea value={note} rows={2} maxLength={1000} disabled={busy || conflict || dirty} onChange={(event) => setNote(event.target.value)} /></label>}
          <div className="guide-actions">{available.map((action) => <button key={action} className={action === 'publish' ? 'retry-button' : 'secondary-button'} disabled={busy || conflict || dirty || (action === 'reject' && !note.trim())} onClick={() => void perform(action)}>{actionLabels[action]}</button>)}</div>
          {row.review_status === 'review' && <small>반려하려면 의견을 입력하세요. 승인은 즉시 게시하지 않습니다.</small>}
        </section>}
        {row && <section aria-labelledby="guide-audit-title"><h4 id="guide-audit-title">변경 이력 (한국 시간)</h4>
          {auditError ? <p role="alert">{auditError} 이력을 다시 확인하려면 최신 내용을 불러오세요.</p> : audit ? <>
            <ol className="guide-audit">{audit.items.map((event) => <li key={event.id}>{actionLabels[event.action]} · {time.format(new Date(event.created_at))}<br /><small>담당자 {event.actor_id ?? '삭제된 계정'} · 판본 {typeof event.after_state.version === 'number' ? event.after_state.version : '확인 필요'}</small></li>)}</ol>
            {!audit.items.length && <p>변경 이력이 없습니다. 기존에 적재된 자료는 이력이 없을 수 있습니다.</p>}
            <div className="pagination"><button className="secondary-button" disabled={busy || auditOffset === 0} onClick={() => { setAudit(null); setAuditOffset(Math.max(0, auditOffset - 20)) }}>이력 이전 페이지</button>
              <button className="secondary-button" disabled={busy || auditOffset + 20 >= audit.total || auditOffset >= 10000} onClick={() => { setAudit(null); setAuditOffset(auditOffset + 20) }}>이력 다음 페이지</button></div>
          </> : <p role="status">이력을 불러오는 중입니다.</p>}
        </section>}
      </>}
    </>}
  </section>
}
