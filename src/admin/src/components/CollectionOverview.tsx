const sampleJobs = [
  {
    id: 'sample-001',
    name: '레시피 수집',
    status: '성공',
    updatedAt: '2026-11-23 09:00',
    error: '—',
  },
  {
    id: 'sample-002',
    name: '복지 자료 갱신',
    status: '실패',
    updatedAt: '2026-11-23 09:10',
    error: '외부 서버 응답 시간 초과',
  },
  {
    id: 'sample-003',
    name: '제철 자료 수집',
    status: '진행 중',
    updatedAt: '2026-11-23 09:20',
    error: '—',
  },
]

export default function CollectionOverview() {
  return (
    <div className="collection-overview">
      <p>
        아래 건수·시각·작업 내역은 화면 확인용 가상 데이터입니다.
        실제 수집 결과가 아닙니다.
      </p>

      <dl className="collection-summary">
        <div>
          <dt>데이터 건수</dt>
          <dd>184건</dd>
        </div>
        <div>
          <dt>최근 갱신 · 한국시간</dt>
          <dd>2026-11-23 09:20</dd>
        </div>
        <div>
          <dt>필수 항목 누락</dt>
          <dd>7건</dd>
        </div>
        <div>
          <dt>검토 대기</dt>
          <dd>12건</dd>
        </div>
      </dl>

      <div className="collection-table-wrapper">
        <table className="collection-table">
          <caption>수집 작업 목록 · 가상 데이터</caption>
          <thead>
            <tr>
              <th scope="col">작업명</th>
              <th scope="col">상태</th>
              <th scope="col">최근 처리 시각 · 한국시간</th>
              <th scope="col">실패 원인</th>
              <th scope="col">재시도</th>
            </tr>
          </thead>
          <tbody>
            {sampleJobs.map((job) => (
              <tr key={job.id}>
                <th scope="row">{job.name}</th>
                <td>{job.status}</td>
                <td>{job.updatedAt}</td>
                <td>{job.error}</td>
                <td>
                  {job.status === '실패'
                    ? 'API 연결 후 제공'
                    : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}