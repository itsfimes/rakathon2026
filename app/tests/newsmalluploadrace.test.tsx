import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { useUploads } from '../src/hooks/useUploads'
import type { UploadCapability, UploadJob, UploadResult } from '../src/data/backend/uploads'

afterEach(() => {
  cleanup()
})

type UploadFn = (caseId: string, filename: string, data: ArrayBuffer, signal?: AbortSignal) => Promise<UploadResult<UploadJob>>

interface Call {
  readonly caseId: string
  readonly name: string
  readonly signal?: AbortSignal | undefined
}

interface MockCap {
  readonly cap: UploadCapability
  readonly calls: Call[]
  readonly jobs: UploadJob[]
  handler: UploadFn
  listHandler: () => Promise<UploadResult<readonly UploadJob[]>>
}

let jobSeq = 0

function makeJob(caseId: string, filename: string): UploadJob {
  jobSeq += 1
  return {
    id: `${jobSeq}`.padStart(32, 'c'),
    caseId,
    filename,
    sha256: 'abc',
    sourceUrn: 'urn:test:1',
    detectedType: 'pdf',
    status: 'running',
    createdAt: '2026-10-16T12:00:00Z',
    events: [],
    eventCount: 0,
    counts: {},
    recipeReuse: false,
    newFormat: false,
    plannerMode: 'none',
    model: { providerId: 'rakathon-azure', model: 'gpt-6-luna-dz-eu', mode: 'offline' },
  }
}

function okJob(caseId: string, filename: string): { readonly ok: true; readonly value: UploadJob } {
  return { ok: true, value: makeJob(caseId, filename) }
}

function mockCap(): MockCap {
  const calls: Call[] = []
  const jobs: UploadJob[] = []
  const mock: MockCap = {
    calls,
    jobs,
    handler: async (caseId, filename) => {
      const out = okJob(caseId, filename)
      jobs.push(out.value)
      return out
    },
    listHandler: async () => ({ ok: true, value: [...jobs] }),
    cap: {
      capabilities: async () => ({ ok: true, value: { enabled: true, maxFileBytes: 5242880, reason: null, aiAvailable: false } }),
      listCase: () => mock.listHandler(),
      fetchJob: async jobId => okJob('case-a', jobId),
      upload: (caseId, filename, data, signal) => {
        calls.push({ caseId, name: filename, signal })
        return mock.handler(caseId, filename, data, signal)
      },
      originalUrl: jobId => `/api/v1/uploads/${jobId}/original`,
      exportUrl: jobId => `/api/v1/uploads/${jobId}/export`,
    },
  }
  return mock
}

function bufferedFile(name: string): File {
  const file = new File(['obsah'], name, { type: 'application/pdf' })
  file.arrayBuffer = async () => new Uint8Array([1, 2, 3]).buffer
  return file
}

function gatedFile(name: string): { file: File; open: () => void } {
  const file = new File(['obsah'], name, { type: 'application/pdf' })
  let open!: (value: ArrayBuffer) => void
  const gate = new Promise<ArrayBuffer>(resolve => {
    open = resolve
  })
  file.arrayBuffer = () => gate
  return { file, open: () => open(new Uint8Array([1, 2, 3]).buffer) }
}

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(inner => {
    resolve = inner
  })
  return { promise, resolve }
}

async function settle(): Promise<void> {
  await act(async () => {})
}

describe('upload queue ownership across case switches', () => {
  it('pending arrayBuffer then switch starts no A request and the new B upload works', async () => {
    const a = mockCap()
    const b = mockCap()
    const { result, rerender } = renderHook(({ cap, caseId }) => useUploads(cap, caseId), {
      initialProps: { cap: a.cap as UploadCapability | null, caseId: 'case-a' as string | null },
    })
    await settle()
    const gated = gatedFile('a.pdf')
    act(() => {
      result.current.queueFiles([gated.file])
    })
    rerender({ cap: b.cap, caseId: 'case-b' })
    await settle()
    await act(async () => {
      gated.open()
    })
    await settle()
    expect(a.calls).toHaveLength(0)
    act(() => {
      result.current.queueFiles([bufferedFile('b.pdf')])
    })
    await waitFor(() => expect(b.calls).toHaveLength(1))
    expect(b.calls[0]?.caseId).toBe('case-b')
    await waitFor(() => expect(result.current.busy).toBe(false))
    expect(result.current.jobs.map(job => job.filename)).toContain('b.pdf')
  })

  it('late A completion cannot clear B busy nor start a waiting third upload early', async () => {
    const a = mockCap()
    const b = mockCap()
    const upA = deferred<UploadResult<UploadJob>>()
    const upB = deferred<UploadResult<UploadJob>>()
    a.handler = () => upA.promise
    b.handler = () => upB.promise
    const { result, rerender } = renderHook(({ cap, caseId }) => useUploads(cap, caseId), {
      initialProps: { cap: a.cap as UploadCapability | null, caseId: 'case-a' as string | null },
    })
    await settle()
    act(() => {
      result.current.queueFiles([bufferedFile('a.pdf')])
    })
    await waitFor(() => expect(a.calls).toHaveLength(1))
    rerender({ cap: b.cap, caseId: 'case-b' })
    await settle()
    act(() => {
      result.current.queueFiles([bufferedFile('b.pdf')])
    })
    await waitFor(() => expect(b.calls).toHaveLength(1))
    act(() => {
      result.current.queueFiles([bufferedFile('c.pdf')])
    })
    await act(async () => {
      upA.resolve(okJob('case-a', 'a.pdf'))
    })
    await settle()
    expect(result.current.busy).toBe(true)
    expect(result.current.pending.map(item => `${item.file.name}:${item.state}`)).toEqual(['b.pdf:uploading', 'c.pdf:waiting'])
    expect(a.calls).toHaveLength(1)
    expect(b.calls).toHaveLength(1)
    expect(result.current.jobs.map(job => job.filename)).not.toContain('a.pdf')
    await act(async () => {
      const done = okJob('case-b', 'b.pdf')
      b.jobs.push(done.value)
      upB.resolve(done)
    })
    await waitFor(() => expect(result.current.busy).toBe(false))
    expect(result.current.jobs.map(job => job.filename)).toContain('b.pdf')
  })

  it('switching case aborts the in-flight upload request', async () => {
    const a = mockCap()
    const b = mockCap()
    const upA = deferred<UploadResult<UploadJob>>()
    a.handler = () => upA.promise
    const { result, rerender } = renderHook(({ cap, caseId }) => useUploads(cap, caseId), {
      initialProps: { cap: a.cap as UploadCapability | null, caseId: 'case-a' as string | null },
    })
    await settle()
    act(() => {
      result.current.queueFiles([bufferedFile('a.pdf')])
    })
    await waitFor(() => expect(a.calls).toHaveLength(1))
    const signal = a.calls[0]?.signal
    expect(signal).toBeDefined()
    expect(signal?.aborted).toBe(false)
    rerender({ cap: b.cap, caseId: 'case-b' })
    await settle()
    expect(signal?.aborted).toBe(true)
    await act(async () => {
      upA.resolve(okJob('case-a', 'a.pdf'))
    })
    await settle()
    expect(result.current.jobs).toHaveLength(0)
    expect(result.current.busy).toBe(false)
  })

  it('older async results do not reintroduce jobs after logout', async () => {
    const a = mockCap()
    const upA = deferred<UploadResult<UploadJob>>()
    const listA = deferred<UploadResult<readonly UploadJob[]>>()
    a.handler = () => upA.promise
    let listCalls = 0
    a.listHandler = () => {
      listCalls += 1
      return listCalls === 1 ? Promise.resolve({ ok: true, value: [] }) : listA.promise
    }
    const { result, rerender, unmount } = renderHook(({ cap, caseId }) => useUploads(cap, caseId), {
      initialProps: { cap: a.cap as UploadCapability | null, caseId: 'case-a' as string | null },
    })
    await settle()
    act(() => {
      result.current.queueFiles([bufferedFile('a.pdf')])
    })
    await waitFor(() => expect(a.calls).toHaveLength(1))
    rerender({ cap: null, caseId: null })
    await settle()
    await act(async () => {
      upA.resolve(okJob('case-a', 'a.pdf'))
      listA.resolve({ ok: true, value: [makeJob('case-a', 'a.pdf')] })
    })
    await settle()
    expect(result.current.jobs).toHaveLength(0)
    expect(result.current.pending).toHaveLength(0)
    expect(result.current.busy).toBe(false)
    unmount()
  })
})
