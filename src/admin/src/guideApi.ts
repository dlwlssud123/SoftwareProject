import { ApiError } from './api'
import type { AdminApi } from './api'

export const reviewStatuses = ['draft', 'review', 'approved', 'rejected'] as const
export type ReviewStatus = (typeof reviewStatuses)[number]
export type GuideAction = 'submit' | 'approve' | 'reject' | 'publish' | 'unpublish'
export type GuideStep = { title?: string; text: string }
export type GuideContent = { title: string; source_reference: string; checked_on: string; steps: GuideStep[] }
export type GuideSummary = Omit<GuideContent, 'steps'> & {
  id: string; slug: string; version: number; review_status: ReviewStatus; is_published: boolean;
  reviewed_by: string | null; reviewed_at: string | null; updated_at: string;
}
export type GuideDetail = GuideSummary & { steps: GuideStep[]; review_note: string | null }
export type GuideAudit = {
  id: string; guide_id: string; actor_id: string | null; request_id: string;
  action: GuideAction | 'create' | 'edit'; created_at: string;
  before_state: Record<string, unknown> | null; after_state: Record<string, unknown>;
}
export type GuidePage<T> = { items: T[]; total: number; offset: number; limit: number }
export type GuideFilter = { q?: string; review_status?: ReviewStatus; is_published?: boolean; offset?: number }
const root = '/api/v1/admin/life-guides'
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
const invalid = () => new ApiError(0, '가이드 응답 형식을 확인할 수 없습니다. 새로고침해 주세요.', true)
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw invalid()
  return value as Record<string, unknown>
}
function text(value: unknown): string { if (typeof value !== 'string') throw invalid(); return value }
function id(value: unknown): string { const result = text(value); if (!uuid.test(result)) throw invalid(); return result }
function stamp(value: unknown): string {
  const result = text(value)
  if (!/(Z|[+-]\d{2}:\d{2})$/.test(result) || !Number.isFinite(Date.parse(result))) throw invalid()
  return result
}
function natural(value: unknown): number { if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0) throw invalid(); return value }
function summary(value: unknown): GuideSummary {
  const row = object(value)
  if (!reviewStatuses.includes(row.review_status as ReviewStatus) || typeof row.is_published !== 'boolean' ||
      !/^\d{4}-\d{2}-\d{2}$/.test(text(row.checked_on))) throw invalid()
  return { id: id(row.id), slug: text(row.slug), title: text(row.title), source_reference: text(row.source_reference), checked_on: text(row.checked_on),
    version: natural(row.version), review_status: row.review_status as ReviewStatus, is_published: row.is_published,
    reviewed_by: row.reviewed_by === null ? null : id(row.reviewed_by), reviewed_at: row.reviewed_at === null ? null : stamp(row.reviewed_at), updated_at: stamp(row.updated_at) }
}
function detail(value: unknown): GuideDetail {
  const row = object(value)
  if (!Array.isArray(row.steps)) throw invalid()
  return { ...summary(row), review_note: row.review_note === null ? null : text(row.review_note), steps: row.steps.map((value) => {
    const step = object(value)
    return { text: text(step.text), ...(step.title == null ? {} : { title: text(step.title) }) }
  }) }
}
function page<T>(value: unknown, parse: (value: unknown) => T): GuidePage<T> {
  const row = object(value)
  if (!Array.isArray(row.items) || natural(row.limit) === 0) throw invalid()
  return { items: row.items.map(parse), total: natural(row.total), offset: natural(row.offset), limit: natural(row.limit) }
}

export function createGuideApi(api: Pick<AdminApi, 'requestJson'>, token: string) {
  async function request(path: string, method = 'GET', body?: unknown, signal?: AbortSignal) {
    const envelope = object(await api.requestJson<unknown>(path, { method, signal,
      headers: { Authorization: `Bearer ${token}`, ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }) }))
    return envelope.data
  }
  const path = (guideId: string) => `${root}/${id(guideId)}`
  return {
    async list(filter: GuideFilter, signal?: AbortSignal) {
      const query = new URLSearchParams({ limit: '20', offset: String(filter.offset ?? 0) })
      if (filter.q?.trim()) query.set('q', filter.q.trim())
      if (filter.review_status) query.set('review_status', filter.review_status)
      if (filter.is_published !== undefined) query.set('is_published', String(filter.is_published))
      return page(await request(`${root}?${query}`, 'GET', undefined, signal), summary)
    },
    async get(guideId: string, signal?: AbortSignal) { return detail(await request(path(guideId), 'GET', undefined, signal)) },
    async create(content: GuideContent & { slug: string }, signal?: AbortSignal) { return detail(await request(root, 'POST', content, signal)) },
    async edit(guideId: string, content: GuideContent, version: number, signal?: AbortSignal) {
      return detail(await request(path(guideId), 'PUT', { ...content, expected_version: version }, signal))
    },
    async action(guideId: string, action: GuideAction, version: number, note?: string, signal?: AbortSignal) {
      return detail(await request(`${path(guideId)}/actions`, 'POST', { action, expected_version: version, ...(note ? { note } : {}) }, signal))
    },
    async audit(guideId: string, offset = 0, signal?: AbortSignal) {
      return page(await request(`${path(guideId)}/audit?limit=20&offset=${offset}`, 'GET', undefined, signal), (value): GuideAudit => {
        const row = object(value)
        if (!['create', 'edit', 'submit', 'approve', 'reject', 'publish', 'unpublish'].includes(text(row.action))) throw invalid()
        return { id: id(row.id), guide_id: id(row.guide_id), actor_id: row.actor_id === null ? null : id(row.actor_id),
          request_id: id(row.request_id), action: row.action as GuideAudit['action'], created_at: stamp(row.created_at),
          before_state: row.before_state === null ? null : object(row.before_state), after_state: object(row.after_state) }
      })
    },
  }
}
export type GuideApi = ReturnType<typeof createGuideApi>
