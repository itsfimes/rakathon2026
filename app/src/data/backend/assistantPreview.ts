import type { AssistantContext, AssistantField, AssistantPreview, AssistantRole } from '../../assistant/contracts'
import { isAssistantRole, validContext } from '../../assistant/validation'
import { invalid, object } from './schema'

export function assistantPreviews(value: unknown, caseId: string): Readonly<Partial<Record<AssistantRole, AssistantPreview>>> {
  if (value === undefined) return {}
  const raw = object(value)
  const result: Partial<Record<AssistantRole, AssistantPreview>> = {}
  for (const [role, preview] of Object.entries(raw)) {
    if (!isAssistantRole(role)) invalid()
    const p = object(preview), c = object(p.context), b = object(p.binding)
    if (Object.keys(p).some(key => !['context', 'binding'].includes(key)) || Object.keys(c).some(key => !['role', 'fields'].includes(key)) || c.role !== role || !Array.isArray(c.fields)) invalid()
    const fields: AssistantField[] = c.fields.map((value: unknown) => {
      const field = object(value)
      if (Object.keys(field).some(key => !['key', 'source', 'value'].includes(key)) || typeof field.value !== 'string') return invalid()
      if (field.key === 'record.coverage' && field.source === 'record-coverage') return { key: field.key, source: field.source, value: field.value }
      if (role !== 'koordinator' && field.key === 'record.reportsSummary' && field.source === 'record-report-metadata') return { key: field.key, source: field.source, value: field.value }
      return invalid()
    })
    const context: AssistantContext = { role, fields }
    if (!validContext(context) || b.caseId !== caseId || typeof b.token !== 'string' || !/^[0-9]{1,12}\.[a-f0-9]{64}$/.test(b.token) || Object.keys(b).some(key => !['caseId', 'token'].includes(key))) invalid()
    result[role] = { context, binding: { caseId, token: b.token } }
  }
  return result
}
