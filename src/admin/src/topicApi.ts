import { ApiError } from './api'
import type { AdminApi } from './api'

export const topicStates = ['received', 'reviewing', 'completed', 'declined'] as const
export type TopicState = (typeof topicStates)[number]
export type TopicKind = 'life_guide' | 'video'
export type TopicGuide = { id: string; slug: string; title: string; source_reference: string; checked_on: string }
export type Topic = {
  id: string; kind: TopicKind; topic: string; status: TopicState; version: number;
  reply: string | null; guide: TopicGuide | null; guide_id: string | null;
  created_at: string; updated_at: string;
}
export type TopicDecision = { status: Exclude<TopicState, 'received'>; reply: string | null; guide_id: string | null }
export type TopicFilter = { q?: string; kind?: TopicKind; status?: TopicState; offset?: number }
export type TopicAudit = { id: string; actor_id: string | null; action: 'create' | 'review' | 'withdraw'; before_state: Record<string, unknown> | null; after_state: Record<string, unknown>; request_id: string; created_at: string }
export type TopicPage<T> = { items: T[]; total: number; offset: number; limit: number }
const root = '/api/v1/admin/content-topic-requests'
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
const invalid = () => new ApiError(0, '주제 요청 응답을 확인할 수 없습니다. 다시 조회해 주세요.', true)
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw invalid()
  return value as Record<string, unknown>
}
function text(value: unknown, max = 3000): string {
  if (typeof value !== 'string' || !value.trim() || [...value].length > max) throw invalid()
  return value
}
function id(value: unknown) { const result = text(value, 36); if (!uuid.test(result)) throw invalid(); return result }
function integer(value: unknown) { if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0) throw invalid(); return value }
function stamp(value: unknown) {
  const result = text(value, 64)
  if (!/(Z|[+-]\d{2}:\d{2})$/.test(result) || !Number.isFinite(Date.parse(result))) throw invalid()
  return result
}
function guide(value: unknown): TopicGuide {
  const row = object(value), slug = text(row.slug, 128), checked = text(row.checked_on, 10)
  if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(slug) || !/^\d{4}-\d{2}-\d{2}$/.test(checked) ||
      !Number.isFinite(Date.parse(checked)) || new Date(checked).toISOString().slice(0, 10) !== checked) throw invalid()
  return { id: id(row.id), slug, title: text(row.title, 200), source_reference: text(row.source_reference, 1000), checked_on: checked }
}
function topic(value: unknown): Topic {
  const row = object(value), kind = row.kind, status = row.status, version = integer(row.version)
  if (!['life_guide', 'video'].includes(kind as string) || !topicStates.includes(status as TopicState) || version < 1) throw invalid()
  const reply = row.reply === null ? null : text(row.reply, 1000)
  const linked = row.guide === null ? null : guide(row.guide)
  const guideId = row.guide_id === null ? null : id(row.guide_id)
  if ((['completed', 'declined'].includes(status as string) && reply === null) ||
      (guideId !== null && (kind !== 'life_guide' || status !== 'completed')) ||
      (linked !== null && linked.id !== guideId)) throw invalid()
  return { id: id(row.id), kind: kind as TopicKind, topic: text(row.topic, 60), status: status as TopicState, version,
    reply, guide: linked, guide_id: guideId, created_at: stamp(row.created_at), updated_at: stamp(row.updated_at) }
}
function page<T>(value: unknown, parse: (row: unknown) => T): TopicPage<T> {
  const row = object(value), total = integer(row.total), offset = integer(row.offset), limit = integer(row.limit)
  if (!Array.isArray(row.items) || limit < 1 || limit > 100 || row.items.length > limit) throw invalid()
  return { items: row.items.map(parse), total, offset, limit }
}

export function createTopicApi(api: Pick<AdminApi, 'requestJson'>, token: string) {
  async function request(path: string, method = 'GET', body?: unknown, signal?: AbortSignal) {
    return object(await api.requestJson<unknown>(path, { method, signal,
      headers: { Authorization: `Bearer ${token}`, ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }) })).data
  }
  const path = (value: string) => `${root}/${id(value)}`
  return {
    async list(filter: TopicFilter, signal?: AbortSignal) {
      const query = new URLSearchParams({ limit: '20', offset: String(filter.offset ?? 0) })
      if (filter.q?.trim()) query.set('q', filter.q.trim())
      if (filter.kind) query.set('kind', filter.kind)
      if (filter.status) query.set('status', filter.status)
      return page(await request(`${root}?${query}`, 'GET', undefined, signal), topic)
    },
    async get(value: string, signal?: AbortSignal) { return topic(await request(path(value), 'GET', undefined, signal)) },
    async review(value: string, version: number, decision: TopicDecision, signal?: AbortSignal) {
      return topic(await request(path(value), 'PUT', { expected_version: version, ...decision }, signal))
    },
    async audit(value: string, offset = 0, signal?: AbortSignal) {
      return page(await request(`${path(value)}/audit?limit=20&offset=${offset}`, 'GET', undefined, signal), (value): TopicAudit => {
        const row = object(value)
        if (!['create', 'review', 'withdraw'].includes(row.action as string)) throw invalid()
        return { id: id(row.id), actor_id: row.actor_id === null ? null : id(row.actor_id), action: row.action as TopicAudit['action'],
          request_id: id(row.request_id), created_at: stamp(row.created_at), before_state: row.before_state === null ? null : object(row.before_state), after_state: object(row.after_state) }
      })
    },
  }
}
export type TopicApi = ReturnType<typeof createTopicApi>
