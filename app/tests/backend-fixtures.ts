export const fetched = '2026-10-16T12:30:00+00:00'
export const sessionResponse = { version: 1, access: 'single-user-development', storage: 'iris-fhir',
  capabilities: { workspaceRead: true, caseRead: true, tasks: false, vectors: false, ingestion: false, screening: false, assistant: false },
  health: { ipc: 'up', database: 'up' },
}
export const complete = (items: unknown[] = []) => ({ status: 'complete', items, serverTotal: items.length as number | null, reason: null as string | null })
export const unavailableSection = () => ({ status: 'unavailable', items: [] as unknown[], serverTotal: null, reason: 'upstream_unavailable_or_incomplete' })
export const workspaceResponse = () => ({ version: 1, fetchedAt: fetched,
  patients: Array.from({ length: 6 }, (_, i) => ({ patientId: `synthetic-${i}`, label: i ? `Synthetic Example ${i}` : null, birthDate: null as string | null })),
  coverage: { status: 'complete', serverTotal: 6, reason: null as string | null },
})
export const caseResponse = (patientId = 'synthetic-0') => ({ version: 1, fetchedAt: fetched,
  patient: { resourceType: 'Patient', id: patientId } as Record<string, unknown>,
  sections: { conditions: complete(), observations: complete(), diagnosticReports: complete(), documents: complete() },
})
export const resource = (resourceType: string, id = 'synthetic-fact') => ({ resourceType, id, subject: { reference: 'Patient/synthetic-0' },
  meta: { versionId: 'full-source-version-123456789', lastUpdated: '2026-10-15T10:00:00Z' },
})
export const jsonResponse = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } })
