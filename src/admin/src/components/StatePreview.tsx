import { useState } from 'react'
import StatusMessage from './StatusMessage'

type PreviewState =
  | 'disconnected'
  | 'loading'
  | 'error'
  | 'empty'
  | 'success'

export default function StatePreview() {
  const [status, setStatus] =
    useState<PreviewState>('disconnected')

  if (!import.meta.env.DEV) {
    return <StatusMessage status="disconnected" />
  }

  return (
    <>
      <p>개발용 예시입니다. 실제 운영 데이터가 아닙니다.</p>

      <label>
        데이터 상태{' '}
        <select
          value={status}
          onChange={(event) =>
            setStatus(event.target.value as PreviewState)
          }
        >
          <option value="disconnected">API 연결 대기</option>
          <option value="loading">로딩</option>
          <option value="error">오류</option>
          <option value="empty">빈 결과</option>
          <option value="success">예시 데이터</option>
        </select>
      </label>

      {status === 'success' ? (
        <ul>
          <li>예시 항목 A — 확인 대기</li>
          <li>예시 항목 B — 확인 완료</li>
        </ul>
      ) : status === 'error' ? (
        <StatusMessage
          status="error"
          message="개발용 오류 예시입니다."
          onRetry={() => setStatus('loading')}
        />
      ) : (
        <StatusMessage status={status} />
      )}
    </>
  )
}