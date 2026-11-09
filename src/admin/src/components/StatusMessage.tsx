type StatusMessageProps =
  | { status: 'loading' }
  | { status: 'empty'; message?: string }
  | { status: 'disconnected' }
  | { status: 'error'; message?: string; onRetry?: () => void }

export default function StatusMessage(props: StatusMessageProps) {
  if (props.status === 'loading') {
    return (
      <div className="empty-state" role="status" aria-live="polite">
        불러오는 중입니다.
      </div>
    )
  }

  if (props.status === 'error') {
    return (
      <div className="empty-state">
        <p role="alert">
          {props.message ?? '정보를 불러오지 못했습니다.'}
        </p>
        {props.onRetry && (
          <button
            className="retry-button"
            type="button"
            onClick={props.onRetry}
          >
            다시 시도
          </button>
        )}
      </div>
    )
  }

  return (
    <div className="empty-state" role="status">
      {props.status === 'disconnected'
        ? 'API 연결 대기 중입니다. 서버 연결 후 데이터를 표시합니다.'
        : (props.message ?? '표시할 데이터가 없습니다.')}
    </div>
  )
}