import { ApiError } from './api'
import type { AdminApi } from './api'

export const features = {
  app: '앱',
  meal: '식단 추천',
  recipes: '레시피',
  nutrition: '영양 분석',
  assistant: 'AI 도우미',
  welfare: '복지',
  playground: '놀이터',
  shorts: '건강쇼츠',
  community: '이웃 이야기',
  guides: '생활 안내',
  meal_plan: '하루 식단표',
  saved_recipes: '레시피 저장',
  shopping: '장보기',
  settings: '설정',
  account: '계정',
} as const
export const outcomes = {
  success: '성공',
  failure: '실패',
  cancelled: '취소',
  started: '시작',
} as const
export const events = {
  app_open: '앱·계정 진입',
  app_error: '앱 처리 오류',
  screen_view: '화면 진입',
  screen_exit: '탭에서 나감',
  request_started: '요청 시작',
  request_finished: '요청 완료',
  setting_changed: '설정 변경',
  read_aloud: '읽어주기',
  photo_selected: '사진 선택',
  food_selected: '음식 선택',
  video_open: '영상 링크 누름',
  game_started: '게임 시작',
  game_completed: '게임 완료',
} as const
export const actions = {
  view: '조회',
  recommend: '추천',
  save: '저장',
  delete: '삭제',
  recognize: '인식',
  calculate: '계산',
  record: '기록',
  ask: '질문',
  open: '열기',
  complete: '완료',
  change: '변경',
  start: '시작',
} as const
export const errors = {
  network: '연결 오류',
  timeout: '시간 초과',
  server: '서버 오류',
  unauthorized: '인증 만료',
  forbidden: '권한 없음',
  validation: '입력 확인',
  conflict: '변경 충돌',
  cancelled: '요청 취소',
  bad_response: '응답 형식',
  unknown: '기타 오류',
} as const
export type UsageFilter = {
  days: number
  feature: string
  outcome: string
  offset: number
}
export type FeatureStats = {
  feature: keyof typeof features
  events: number
  requests: number
  success: number
  failure: number
  cancelled: number
  avg_ms: number | null
}
export type UsageRow = {
  event_id: string
  created_at: string
  event: keyof typeof events
  feature: keyof typeof features
  action: keyof typeof actions
  outcome: keyof typeof outcomes
  app_version: string
  platform: string
  duration_ms: number | null
  error_kind: keyof typeof errors | null
  request_id: string | null
  result_count: number | null
  result_kind: string | null
  setting_kind: string | null
  setting_value: string | null
}
export type UsagePage = {
  checked_at: string
  retention_days: number
  total: number
  offset: number
  limit: number
  app_opens: number
  features: FeatureStats[]
  daily: { day: string; count: number }[]
  items: UsageRow[]
}
const invalid = () =>
  new ApiError(
    0,
    '이용 현황 응답을 확인할 수 없습니다. 다시 조회해 주세요.',
    true,
  )
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
function object(v: unknown): Record<string, unknown> {
  if (!v || typeof v !== 'object' || Array.isArray(v)) throw invalid()
  return v as Record<string, unknown>
}
function number(v: unknown): number {
  if (typeof v !== 'number' || !Number.isSafeInteger(v) || v < 0)
    throw invalid()
  return v
}
function optionalNumber(v: unknown) {
  return v === null ? null : number(v)
}
function label<T extends string>(v: unknown, labels: Record<T, string>): T {
  if (typeof v !== 'string' || !Object.hasOwn(labels, v)) throw invalid()
  return v as T
}
function one(v: unknown, values: readonly string[]): string {
  if (typeof v !== 'string' || !values.includes(v)) throw invalid()
  return v
}
function stamp(v: unknown): string {
  if (
    typeof v !== 'string' ||
    !/(Z|[+-]\d{2}:\d{2})$/.test(v) ||
    !Number.isFinite(Date.parse(v))
  )
    throw invalid()
  return v
}
function id(v: unknown): string {
  if (typeof v !== 'string' || !uuid.test(v)) throw invalid()
  return v
}
function row(v: unknown): UsageRow {
  const r = object(v)
  if (
    typeof r.app_version !== 'string' ||
    !/^\d{1,3}\.\d{1,3}\.\d{1,3}(?:\+\d{1,10})?$/.test(r.app_version)
  )
    throw invalid()
  return {
    event_id: id(r.event_id),
    created_at: stamp(r.created_at),
    event: label(r.event, events),
    feature: label(r.feature, features),
    action: label(r.action, actions),
    outcome: label(r.outcome, outcomes),
    app_version: r.app_version,
    platform: one(r.platform, ['android', 'ios', 'web', 'desktop']),
    duration_ms: optionalNumber(r.duration_ms),
    error_kind: r.error_kind === null ? null : label(r.error_kind, errors),
    request_id: r.request_id === null ? null : id(r.request_id),
    result_count: optionalNumber(r.result_count),
    result_kind:
      r.result_kind === null
        ? null
        : one(r.result_kind, ['generated', 'references_only', 'no_evidence']),
    setting_kind:
      r.setting_kind === null
        ? null
        : one(r.setting_kind, ['text_size', 'voice']),
    setting_value:
      r.setting_value === null
        ? null
        : one(r.setting_value, [
            'normal',
            'large',
            'largest',
            'enabled',
            'disabled',
          ]),
  }
}
function page(v: unknown): UsagePage {
  const r = object(v)
  if (
    !Array.isArray(r.features) ||
    !Array.isArray(r.daily) ||
    !Array.isArray(r.items)
  )
    throw invalid()
  const total = number(r.total),
    offset = number(r.offset),
    limit = number(r.limit)
  if (
    limit < 1 ||
    limit > 100 ||
    r.items.length > limit ||
    r.items.length > total ||
    r.features.length > 15 ||
    r.daily.length > 30
  )
    throw invalid()
  return {
    checked_at: stamp(r.checked_at),
    retention_days: number(r.retention_days),
    total,
    offset,
    limit,
    app_opens: number(r.app_opens),
    features: r.features.map((v) => {
      const f = object(v)
      const item = {
        feature: label(f.feature, features),
        events: number(f.events),
        requests: number(f.requests),
        success: number(f.success),
        failure: number(f.failure),
        cancelled: number(f.cancelled),
        avg_ms: optionalNumber(f.avg_ms),
      }
      if (item.requests !== item.success + item.failure + item.cancelled)
        throw invalid()
      return item
    }),
    daily: r.daily.map((v) => {
      const d = object(v)
      if (
        typeof d.day !== 'string' ||
        !/^\d{4}-\d{2}-\d{2}$/.test(d.day) ||
        !Number.isFinite(Date.parse(d.day)) ||
        new Date(d.day).toISOString().slice(0, 10) !== d.day
      )
        throw invalid()
      return { day: d.day, count: number(d.count) }
    }),
    items: r.items.map(row),
  }
}
export function createUsageApi(
  api: Pick<AdminApi, 'requestJson'>,
  token: string,
) {
  async function request(path: string, method = 'GET', signal?: AbortSignal) {
    return object(
      await api.requestJson<unknown>(path, {
        method,
        signal,
        headers: { Authorization: `Bearer ${token}` },
      }),
    ).data
  }
  return {
    async list(filter: UsageFilter, signal?: AbortSignal) {
      const q = new URLSearchParams({
        days: String(filter.days),
        offset: String(filter.offset),
        limit: '20',
      })
      if (filter.feature) q.set('feature', filter.feature)
      if (filter.outcome) q.set('outcome', filter.outcome)
      return page(
        await request(`/api/v1/admin/usage-events?${q}`, 'GET', signal),
      )
    },
    async prune(signal?: AbortSignal) {
      return number(
        object(
          await request('/api/v1/admin/usage-events/prune', 'POST', signal),
        ).removed,
      )
    },
  }
}
