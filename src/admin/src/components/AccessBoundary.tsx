import { useState } from 'react'
import type { ReactNode } from 'react'

type Access = 'checking' | 'admin' | 'denied'

export default function AccessBoundary({
  children,
}: {
  children: ReactNode
}) {
  const [access, setAccess] = useState<Access>(
    import.meta.env.DEV ? 'checking' : 'denied',
  )

  return (
    <>
      {import.meta.env.DEV && (
        <section aria-label="개발용 권한 확인">
          <p>개발용 예시입니다. 실제 인증 결과가 아닙니다.</p>
          <label>
            권한 상태{' '}
            <select
              value={access}
              onChange={(event) =>
                setAccess(event.target.value as Access)
              }
            >
              <option value="checking">권한 확인 중</option>
              <option value="admin">관리자</option>
              <option value="denied">접근 거부</option>
            </select>
          </label>
        </section>
      )}

      {access === 'checking' ? (
        <main>
          <p role="status">관리자 권한을 확인하는 중입니다.</p>
        </main>
      ) : access === 'admin' ? (
        children
      ) : (
        <main>
          <h1>접근할 수 없습니다.</h1>
          <p role="alert">
            관리자 권한이 필요합니다. 실제 인증 연동은 준비 중입니다.
          </p>
        </main>
      )}
    </>
  )
}