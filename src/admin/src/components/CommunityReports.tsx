import { useEffect, useMemo, useRef, useState } from 'react'
import { ApiError } from '../api'
import { createCommunityApi } from '../communityApi'
import type { Report, ReportPage } from '../communityApi'
import type { AdminConnection } from './AccessBoundary'

const reasons: Record<string, string> = { spam: '광고·도배', abuse: '욕설·괴롭힘', misinformation: '잘못된 정보', privacy: '개인정보 노출', other: '기타' }
export default function CommunityReports({ connection, onDirtyChange }: {
  connection: AdminConnection; onDirtyChange: (dirty: boolean) => void
}) {
  const { api, session, invalidate } = connection
  const reports = useMemo(() => createCommunityApi(api, session.token), [api, session.token])
  const [page, setPage] = useState<ReportPage | null>(null)
  const [selected, setSelected] = useState<Report | null>(null)
  const [resolution, setResolution] = useState('')
  const [offset, setOffset] = useState(0), [reload, setReload] = useState(0)
  const [loading, setLoading] = useState(true), [busy, setBusy] = useState(false)
  const [error, setError] = useState(''), [message, setMessage] = useState('')
  const mutation = useRef<AbortController | null>(null)
  const dirty = selected !== null && resolution !== ''
  useEffect(() => { onDirtyChange(dirty); return () => onDirtyChange(false) }, [dirty, onDirtyChange])
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => { if (dirty || busy) event.preventDefault() }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty, busy])
  useEffect(() => {
    const abort = new AbortController()
    reports.list(offset, abort.signal).then((result) => {
      if (!abort.signal.aborted) setPage(result)
    }).catch((e: unknown) => {
      if (abort.signal.aborted) return
      if (e instanceof ApiError && [401, 403].includes(e.status)) invalidate(session.token, '관리자 권한을 다시 확인해 주세요.')
      setError(e instanceof Error ? e.message : '신고 목록을 불러오지 못했습니다.')
    }).finally(() => { if (!abort.signal.aborted) setLoading(false) })
    return () => abort.abort()
  }, [reports, offset, reload, invalidate, session.token])
  useEffect(() => () => mutation.current?.abort(), [])
  function reset() { setSelected(null); setResolution(''); onDirtyChange(false) }
  function refresh(nextOffset = offset) {
    setLoading(true); setError(''); setPage(null); setOffset(nextOffset); setReload((n) => n + 1)
  }
  function leave() { return !dirty || window.confirm('저장하지 않은 신고 처리 내용을 버릴까요?') }
  async function resolve(decision: 'hide' | 'dismiss') {
    if (!selected || mutation.current) return
    if (!resolution.trim() || [...resolution.trim()].length > 200) { setError('처리 사유를 1~200자로 적어 주세요.'); return }
    if (!window.confirm(decision === 'hide' ? '이 글을 모든 이용자에게서 숨길까요?' : '신고를 기각하고 글을 유지할까요?')) return
    const row = selected, abort = new AbortController()
    mutation.current = abort; setBusy(true); setError(''); setMessage('')
    try {
      await reports.resolve(row, decision, resolution, abort.signal)
      if (abort.signal.aborted) return
      reset(); setMessage(decision === 'hide' ? '글을 숨기고 신고를 처리했습니다.' : '신고를 기각했습니다.')
      refresh(0)
    } catch (e) {
      if (abort.signal.aborted) return
      if (e instanceof ApiError && [401, 403].includes(e.status)) invalidate(session.token, '관리자 권한을 다시 확인해 주세요.')
      if (e instanceof ApiError && e.status === 409) {
        reset(); refresh()
        setError('글이나 신고 상태가 바뀌었습니다. 목록에서 다시 선택해 주세요.')
      } else setError(e instanceof Error ? e.message : '처리 결과를 확인하지 못했습니다. 새로고침 후 확인해 주세요.')
    } finally {
      if (mutation.current === abort) mutation.current = null
      if (!abort.signal.aborted) setBusy(false)
    }
  }
  return <section className="card">
    <h3>커뮤니티 신고 처리</h3>
    <p>미처리 신고를 확인하고 글 숨김 또는 기각을 결정합니다. 신고자 정보는 표시하지 않습니다.</p>
    {message && <p role="status">{message}</p>}{error && <p role="alert">{error}</p>}
    <button disabled={loading || busy} onClick={() => { if (leave()) { reset(); refresh() } }}>새로고침</button>
    {loading && <p role="status">신고를 불러오고 있습니다.</p>}
    {page && <><p>미처리 신고 {page.total}건</p>
      <ul>{page.items.map((row) => <li key={row.id}><button disabled={busy} onClick={() => {
        if (!leave()) return
        setSelected(row); setResolution(''); setError(''); setMessage('')
      }}>{reasons[row.reason]} · {row.post.title}</button></li>)}</ul>
      {offset > 0 && <button disabled={busy} onClick={() => { if (leave()) { reset(); refresh(Math.max(0, offset - 20)) } }}>이전 목록</button>}
      {offset + page.items.length < page.total && <button disabled={busy} onClick={() => { if (leave()) { reset(); refresh(offset + page.limit) } }}>다음 목록</button>}
    </>}
    {selected && <fieldset disabled={busy}>
      <legend>신고 내용 확인</legend><p>신고 번호: {selected.id}</p>
      <h4>{selected.post.title}</h4><p>{selected.post.author_label} · 상태 {selected.post.status}</p>
      <p style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{selected.post.body}</p>
      <p>신고 이유: {reasons[selected.reason]}</p><p>{selected.note || '추가 설명 없음'}</p>
      <label>처리 사유<textarea value={resolution} maxLength={200} onChange={(e) => setResolution(e.target.value)} /></label>
      <button disabled={selected.post.status === 'deleted'} onClick={() => resolve('hide')}>글 숨김 처리</button>
      <button onClick={() => resolve('dismiss')}>신고 기각</button>
    </fieldset>}
  </section>
}
