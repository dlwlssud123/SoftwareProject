import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { ApiError, createAdminApi } from '../api'
import type { AdminApi, AdminSession } from '../api'

export type AdminConnection = {
  api: AdminApi
  session: AdminSession
  invalidate: (token: string, message: string) => void
  logout: () => Promise<void>
}

export default function AccessBoundary({ children, api: suppliedApi }: {
  children: (connection: AdminConnection) => ReactNode
  api?: AdminApi
}) {
  const api = useMemo(() => suppliedApi ?? createAdminApi(), [suppliedApi])
  const [auth, setAuth] = useState<{ session: AdminSession | null; message: string }>({ session: null, message: '' })
  const invalidate = useCallback((token: string, message: string) => {
    setAuth((current) => current.session?.token === token ? { session: null, message } : current)
  }, [])

  useEffect(() => {
    const session = auth.session
    if (!session) return
    const timeout = setTimeout(() => invalidate(session.token, '이용 시간이 만료됐습니다. 다시 로그인해 주세요.'),
      Math.min(2147483647, Math.max(0, Date.parse(session.expiresAt) - Date.now())))
    return () => clearTimeout(timeout)
  }, [auth.session, invalidate])

  if (!auth.session) return <LoginForm api={api} message={auth.message} onLogin={(session) => setAuth({ session, message: '' })} />
  const session = auth.session
  async function logout() {
    let message = '로그아웃했습니다.'
    try { await api.logout(session.token) }
    catch { message = '이 브라우저의 연결은 해제했습니다. 서버 세션 폐기는 확인하지 못했으므로 공용 기기에서는 브라우저를 닫아 주세요.' }
    invalidate(session.token, message)
  }
  return children({ api, session, invalidate, logout })
}

function LoginForm({ api, message, onLogin }: {
  api: AdminApi; message: string; onLogin: (session: AdminSession) => void
}) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const pending = useRef<AbortController | null>(null)
  useEffect(() => () => pending.current?.abort(), [])

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (pending.current || !api.configured) return
    const controller = new AbortController()
    pending.current = controller
    setBusy(true)
    setError('')
    try {
      const session = await api.login(username, password, controller.signal)
      if (!controller.signal.aborted) onLogin(session)
    } catch (cause) {
      if (!controller.signal.aborted) setError(cause instanceof ApiError ? cause.message : '로그인하지 못했습니다. 다시 시도해 주세요.')
    } finally {
      if (!controller.signal.aborted) { setBusy(false); setPassword('') }
      pending.current = null
    }
  }

  return <main className="login-layout">
    <section className="card login-card">
      <p className="eyebrow">VALUEFLOW ADMIN</p><h1>관리자 로그인</h1>
      <p>서버 운영자가 발급한 관리자 계정으로 로그인하세요.</p>
      {message && <p role="status" className="notice">{message}</p>}
      {!api.configured && <p role="alert" className="notice">API 서버 주소가 설정되지 않았거나 올바르지 않습니다. 운영 환경은 HTTPS 주소가 필요합니다.</p>}
      {error && <p role="alert" className="notice">{error}</p>}
      <form onSubmit={submit}>
        <label htmlFor="admin-username">관리자 아이디</label>
        <input id="admin-username" autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)}
          required minLength={3} maxLength={64} pattern="[A-Za-z0-9][A-Za-z0-9._-]{2,63}" disabled={busy || !api.configured} />
        <label htmlFor="admin-password">비밀번호</label>
        <input id="admin-password" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)}
          required maxLength={128} disabled={busy || !api.configured} />
        <button className="retry-button" type="submit" disabled={busy || !api.configured}>{busy ? '관리자 권한 확인 중…' : '로그인'}</button>
      </form>
      <p>로그인 정보는 브라우저 저장소에 보관하지 않습니다. 새로고침하거나 브라우저를 다시 열면 로그인해 주세요.</p>
    </section>
  </main>
}
