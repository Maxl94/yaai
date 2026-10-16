import { isApiError } from '@/types'

/** Extract a human-readable message from an API error (FastAPI `detail` may be a string or a validation list). */
export function errorMessage(error: unknown, fallback: string): string {
  if (!isApiError(error)) return fallback
  const detail: unknown = error.detail
  if (typeof detail === 'string' && detail) return detail
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => (typeof item === 'object' && item !== null && 'msg' in item ? String(item.msg) : null))
      .filter((msg): msg is string => !!msg)
    if (messages.length > 0) return messages.join('; ')
  }
  return fallback
}
