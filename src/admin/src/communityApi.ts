import { ApiError } from './api'
import type { AdminApi } from './api'

export type Report = {
  id: string; status: 'received' | 'dismissed' | 'actioned'; reason: string;
  note: string; resolution: string; created_at: string;
  post: { id: string; title: string; body: string; author_label: string;
    status: 'published' | 'hidden' | 'deleted'; version: number }
}
export type ReportPage = { items: Report[]; total: number; offset: number; limit: number }
const root = '/api/v1/admin/community/reports'
const invalid = () => new ApiError(0, '신고 응답을 확인할 수 없습니다. 다시 불러와 주세요.', true)
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
function obj(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw invalid()
  return value as Record<string, unknown>
}
function text(value: unknown, max: number, empty = false): string {
  if (typeof value !== 'string' || (!empty && !value.trim()) || [...value].length > max) throw invalid()
  return value
}
function id(value: unknown) { const result = text(value, 36); if (!uuid.test(result)) throw invalid(); return result }
function integer(value: unknown) { if (!Number.isSafeInteger(value) || (value as number) < 0) throw invalid(); return value as number }
function report(value: unknown): Report {
  const row = obj(value), post = obj(row.post), status = row.status, state = post.status
  const version = integer(post.version), date = text(row.created_at, 64)
  if (!['received', 'dismissed', 'actioned'].includes(status as string) ||
      !['published', 'hidden', 'deleted'].includes(state as string) || version < 1 ||
      !['spam', 'abuse', 'misinformation', 'privacy', 'other'].includes(row.reason as string) ||
      !/(Z|[+-]\d{2}:\d{2})$/.test(date) || !Number.isFinite(Date.parse(date))) throw invalid()
  return { id: id(row.id), status: status as Report['status'], reason: row.reason as string,
    note: text(row.note, 500, true), resolution: text(row.resolution, 200, true), created_at: date,
    post: { id: id(post.id), title: text(post.title, 60), body: text(post.body, 2000),
      author_label: text(post.author_label, 100), status: state as Report['post']['status'], version } }
}
export function createCommunityApi(api: Pick<AdminApi, 'requestJson'>, token: string) {
  async function request(path: string, method: string, signal?: AbortSignal, body?: unknown) {
    return obj(await api.requestJson<unknown>(path, { method, signal,
      headers: { Authorization: `Bearer ${token}`, ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }) })).data
  }
  return {
    async list(offset: number, signal?: AbortSignal): Promise<ReportPage> {
      const row = obj(await request(`${root}?status=received&limit=20&offset=${integer(offset)}`, 'GET', signal))
      const total = integer(row.total), start = integer(row.offset), limit = integer(row.limit)
      if (!Array.isArray(row.items) || limit < 1 || limit > 100 || row.items.length > limit) throw invalid()
      return { items: row.items.map(report), total, offset: start, limit }
    },
    async resolve(row: Report, decision: 'hide' | 'dismiss', resolution: string, signal?: AbortSignal) {
      return report(await request(`${root}/${id(row.id)}`, 'PATCH', signal,
        { decision, resolution: text(resolution.trim(), 200), expected_post_version: row.post.version }))
    },
  }
}
