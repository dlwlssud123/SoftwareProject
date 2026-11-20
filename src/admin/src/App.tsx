import { useEffect, useState } from 'react'
import './App.css'
import Collections from './components/Collections'
import Guides from './components/Guides'
import StatusMessage from './components/StatusMessage'
import type { AdminConnection } from './components/AccessBoundary'

const pages = {
  overview: {
    title: '관리자 홈',
    description: '수집·콘텐츠·품질 검토 현황을 확인하는 공간입니다.',
  },
  collections: {
    title: '수집 상태',
    description: '실제 수집 작업·처리 결과·실패 단계를 확인합니다.',
  },
  contents: {
    title: '콘텐츠 검수',
    description: '생활 가이드를 작성하고 출처 확인·검수·게시를 진행합니다.',
  },
  quality: {
    title: '품질 검토',
    description: '누락·중복·형식 오류 등 데이터 품질을 검토합니다.',
  },
}

type PageKey = keyof typeof pages

function readPage(): PageKey {
  const key = window.location.hash.slice(1)
  return Object.hasOwn(pages, key) ? (key as PageKey) : 'overview'
}

export default function App({ connection }: { connection: AdminConnection }) {
  const [page, setPage] = useState<PageKey>(readPage)
  const [leaving, setLeaving] = useState(false)
  const [guideDirty, setGuideDirty] = useState(false)

  useEffect(() => {
    const update = () => {
      const target = readPage()
      if (target === page) return
      if (guideDirty && !window.confirm('저장하지 않은 가이드 변경을 버리고 이동할까요?')) {
        window.history.replaceState(null, '', `#${page}`)
        return
      }
      setPage(target)
    }
    window.addEventListener('hashchange', update)
    return () => window.removeEventListener('hashchange', update)
  }, [page, guideDirty])

  useEffect(() => {
    document.title = `${pages[page].title} | ValueFlow`
  }, [page])

  return (
    <div className="admin-layout">
      <aside className="sidebar">
        <h1>ValueFlow</h1>
        <p>관리자 웹</p>

        <nav aria-label="관리자 메뉴">
          {Object.entries(pages).map(([key, value]) => (
            <a
              key={key}
              href={`#${key}`}
              aria-current={page === key ? 'page' : undefined}
            >
              {value.title}
            </a>
          ))}
        </nav>
      </aside>

      <main className="main-content">
        <header className="page-header">
          <div>
            <span className="eyebrow">VALUEFLOW ADMIN</span>
            <h2>{pages[page].title}</h2>
          </div>
          <button className="secondary-button" disabled={leaving} onClick={async () => {
            if (guideDirty && !window.confirm('저장하지 않은 가이드 변경을 버리고 로그아웃할까요?')) return
            setLeaving(true)
            try { await connection.logout() } finally { setLeaving(false) }
          }}>{leaving ? '로그아웃 중…' : '로그아웃'}</button>
        </header>

        <p className="notice">
          서버에서 확인한 관리자 세션으로 접속했습니다. 수집 현황은 실제 API를 사용합니다.
          생활 가이드 검수·게시를 서버에 반영하며, 품질 검토 화면 연결은 준비 중입니다.
        </p>

        {page === 'overview' ? (
          <div className="card-grid">
            {Object.entries(pages)
              .filter(([key]) => key !== 'overview')
              .map(([key, value]) => (
                <a className="card menu-card" href={`#${key}`} key={key}>
                  <h3>{value.title}</h3>
                  <p>{value.description}</p>
                  <span>화면 열기 →</span>
                </a>
              ))}
          </div>
        ) : page === 'collections' ? <Collections connection={connection} /> : page === 'contents' ? <Guides connection={connection} onDirtyChange={setGuideDirty} /> : (
          <section className="card">
            <h3>{pages[page].title}</h3>
            <p>{pages[page].description}</p>
            <StatusMessage status="disconnected" />
          </section>
        )}
      </main>
    </div>
  )
}
