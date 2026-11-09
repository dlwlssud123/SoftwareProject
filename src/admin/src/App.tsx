import { useEffect, useState } from 'react'
import './App.css'
import StatePreview from './components/StatePreview'

const pages = {
  overview: {
    title: '관리자 홈',
    description: '수집·콘텐츠·품질 검토 현황을 확인하는 공간입니다.',
  },
  collections: {
    title: '수집 상태',
    description: '수집 작업과 처리 결과를 표시할 예정입니다.',
  },
  contents: {
    title: '콘텐츠 검수',
    description: '콘텐츠 원문과 출처를 확인하는 화면을 준비합니다.',
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

export default function App() {
  const [page, setPage] = useState<PageKey>(readPage)

  useEffect(() => {
    const update = () => setPage(readPage())
    window.addEventListener('hashchange', update)
    return () => window.removeEventListener('hashchange', update)
  }, [])

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
          <span className="badge">개발 중</span>
        </header>

        <p className="notice">
          기본 화면 구성 단계입니다. 실제 운영 데이터와 연결되지 않았으며,
          관리자 인증·권한은 서버 담당자와 협의 후 적용합니다.
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
        ) : (
          <section className="card">
            <h3>{pages[page].title}</h3>
            <p>{pages[page].description}</p>
            <StatePreview />
          </section>
        )}
      </main>
    </div>
  )
}