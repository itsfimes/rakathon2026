import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { BackendUploads } from '../src/data/backend/uploads'
import { UploadPanel } from '../src/features/doctor/UploadPanel'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const JOB_ID = 'a'.repeat(32)
const CASE = 'synthetic-0'

function jobBody(over: Record<string, unknown> = {}) {
  return {
    id: JOB_ID,
    caseId: CASE,
    filename: 'zprava.pdf',
    sha256: 'abc',
    sourceUrn: 'urn:test:1',
    detectedType: 'pdf',
    status: 'running',
    createdAt: '2026-10-16T12:00:00Z',
    events: [{ message: 'Zkouším dekodér PDF' }],
    eventCount: 1,
    counts: {},
    recipeReuse: false,
    newFormat: false,
    plannerMode: 'none',
    model: { providerId: 'rakathon-azure', model: 'gpt-6-luna-dz-eu', mode: 'none' },
    ...over,
  }
}
const capsBody = (over: Record<string, unknown> = {}) => ({
  version: 1,
  enabled: true,
  maxFileBytes: 5242880,
  reason: null,
  aiAvailable: true,
  ...over,
})
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } })

interface Route {
  readonly url: string
  readonly init: RequestInit
}
function setup(handler: (route: Route) => Response | Promise<Response>, hooks: { onUnauthorized?: () => void } = {}) {
  const seen: Route[] = []
  const unauthorized = vi.fn()
  const fetcher = vi.fn(async (input: unknown, init?: RequestInit) => {
    const route = { url: String(input), init: (init ?? {}) as RequestInit }
    seen.push(route)
    return handler(route)
  }) as unknown as typeof fetch
  const capability = new BackendUploads(true, fetcher, {
    csrfToken: () => 'csrf-test',
    onUnauthorized: () => {
      unauthorized()
      hooks.onUnauthorized?.()
    },
  })
  return { seen, unauthorized, fetcher, capability }
}

function echoHandler(over: Record<string, unknown> = {}, caps: Record<string, unknown> = {}) {
  let accepted = false
  return (route: Route) => {
    if (route.url === '/api/v1/uploads/capabilities') return json(capsBody(caps))
    if (route.url.endsWith('/uploads') && route.init.method === 'GET') {
      return json({ version: 1, jobs: accepted ? [jobBody(over)] : [] })
    }
    if (route.init.method === 'POST') {
      accepted = true
      return json({ version: 1, job: jobBody(over) }, 202)
    }
    throw new Error(`unexpected ${route.url}`)
  }
}

const baseHandler = echoHandler()

const pdf = () => new File(['obsah'], 'zprava.pdf', { type: 'application/pdf' })

describe('upload panel', () => {
  it('sends a picked file as octet-stream with CSRF and shows progress', async () => {
    const { seen, capability } = setup(baseHandler)
    render(<UploadPanel capability={capability} caseId={CASE} mockMode={false} />)
    const input = await screen.findByLabelText('Vybrat soubory k nahrání')
    fireEvent.change(input, { target: { files: [pdf()] } })
    await waitFor(() => expect(screen.getByText('zprava.pdf')).toBeInTheDocument())
    const post = seen.find(route => route.init.method === 'POST')
    expect(post?.url).toBe(`/api/v1/cases/${CASE}/uploads`)
    const headers = post?.init.headers as Record<string, string>
    expect(headers['Content-Type']).toBe('application/octet-stream')
    expect(headers['X-CSRF-Token']).toBe('csrf-test')
    expect(headers['X-Upload-Name']).toBe('zprava.pdf')
    expect(post?.init.body).toBeInstanceOf(ArrayBuffer)
    expect(await screen.findByText('Zpracovává se')).toBeInTheDocument()
    expect(screen.getByText('Rozpoznaný formát: pdf')).toBeInTheDocument()
  })

  it('uploads an unknown dropped file to the server and warns it may take longer', async () => {
    const { capability } = setup(echoHandler({ filename: 'data.xyz', detectedType: 'neznámý', newFormat: true }))
    render(<UploadPanel capability={capability} caseId={CASE} mockMode={false} />)
    await screen.findByLabelText('Vybrat soubory k nahrání')
    const zone = screen.getByText('Vyberte soubory').closest('div') as HTMLElement
    fireEvent.drop(zone, { dataTransfer: { files: [new File(['x'], 'data.xyz')] } })
    expect(await screen.findByText('Nový formát – zpracování může trvat déle.')).toBeInTheDocument()
  })

  it('confirms recipe reuse and shows counts', async () => {
    const { capability } = setup(echoHandler({ status: 'complete', recipeReuse: true, counts: { zaznamy: 3 } }))
    render(<UploadPanel capability={capability} caseId={CASE} mockMode={false} />)
    fireEvent.change(await screen.findByLabelText('Vybrat soubory k nahrání'), { target: { files: [pdf()] } })
    expect(await screen.findByText('Opakovaný formát.')).toBeInTheDocument()
    expect(screen.getByText(/Počty: zaznamy: 3/)).toBeInTheDocument()
  })

  it('keeps the permanent original and bundle links and never writes clinical data', async () => {
    const { seen, capability } = setup(baseHandler)
    render(<UploadPanel capability={capability} caseId={CASE} mockMode={false} />)
    fireEvent.change(await screen.findByLabelText('Vybrat soubory k nahrání'), { target: { files: [pdf()] } })
    const original = await screen.findByText('Stáhnout originál')
    expect(original.getAttribute('href')).toBe(`/api/v1/uploads/${JOB_ID}/original`)
    expect(screen.getByText('Stáhnout balíček (ZIP)').getAttribute('href')).toBe(`/api/v1/uploads/${JOB_ID}/export`)
    expect(screen.getByText('Originál je trvale uložený. Balíček obsahuje přesný originál i výstupy ke kontrole.')).toBeInTheDocument()
    expect(screen.getByText(/Nic se samo nezapisuje do záznamu případu/)).toBeInTheDocument()
    for (const route of seen) {
      expect(route.url).not.toMatch(/assistant|clinical|cases\/.*\/(records|documents)/)
      expect(route.init.method ?? 'GET').not.toMatch(/PUT|PATCH|DELETE/)
    }
  })

  it('shows manual review and failure detail with the original kept', async () => {
    const { capability } = setup(route => {
      if (route.url === '/api/v1/uploads/capabilities') return json(capsBody())
      if (route.init.method === 'GET') {
        return json({ version: 1, jobs: [jobBody({ status: 'manual-review', detectedType: 'nepodporovaný', events: [{ message: 'Dekodér si nevěděl rady' }] })] })
      }
      return json({ version: 1, job: jobBody() }, 202)
    })
    render(<UploadPanel capability={capability} caseId={CASE} mockMode={false} />)
    expect(await screen.findByText('Ke kontrole člověkem')).toBeInTheDocument()
    expect(screen.getByText(/Potřebuje kontrolu člověkem/)).toBeInTheDocument()
  })

  it('states storage-only honestly when AI is unavailable', async () => {
    const { capability } = setup(echoHandler({ status: 'manual-review' }, { aiAvailable: false }))
    render(<UploadPanel capability={capability} caseId={CASE} mockMode={false} />)
    expect(await screen.findByText(/Server nemá klíč k umělé inteligenci/)).toBeInTheDocument()
    fireEvent.change(await screen.findByLabelText('Vybrat soubory k nahrání'), { target: { files: [pdf()] } })
    expect(await screen.findByText('Ke kontrole člověkem')).toBeInTheDocument()
  })

  it('disables upload clearly in mock mode', async () => {
    render(<UploadPanel capability={null} caseId={CASE} mockMode />)
    expect(await screen.findByText(/Ukázkový režim bez serveru/)).toBeInTheDocument()
    expect(screen.queryByLabelText('Vybrat soubory k nahrání')).toBeNull()
  })

  it('ends the session on 401 and purges cached names and jobs', async () => {
    let expired = false
    const { unauthorized, capability } = setup(route => {
      if (route.url === '/api/v1/uploads/capabilities') return json(capsBody())
      if (route.init.method === 'GET') return expired ? json({ error: 'expired' }, 401) : json({ version: 1, jobs: [jobBody()] })
      expired = true
      return json({ error: 'expired' }, 401)
    })
    render(<UploadPanel capability={capability} caseId={CASE} mockMode={false} />)
    expect(await screen.findByText('zprava.pdf')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Vybrat soubory k nahrání'), { target: { files: [pdf()] } })
    await waitFor(() => expect(unauthorized).toHaveBeenCalled())
    await waitFor(() => expect(screen.queryByText('zprava.pdf')).toBeNull())
  })

  it('explains a too-large file and keeps a full queue for manual retry', async () => {
    const posted: string[] = []
    const { capability } = setup(route => {
      if (route.url === '/api/v1/uploads/capabilities') return json(capsBody())
      if (route.init.method === 'GET') return json({ version: 1, jobs: [] })
      posted.push(route.url)
      return json({ version: 1, error: { code: 'busy', message: 'queue full' } }, 429)
    })
    render(<UploadPanel capability={capability} caseId={CASE} mockMode={false} />)
    await screen.findByLabelText('Vybrat soubory k nahrání')
    fireEvent.change(screen.getByLabelText('Vybrat soubory k nahrání'), { target: { files: [pdf()] } })
    expect(await screen.findByText(/Fronta je plná/)).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: 'Zkusit znovu' })).toBeInTheDocument()
    expect(posted).toHaveLength(1)
  })

  it('prechecks oversize and executable files without contacting the server', async () => {
    const { seen, capability } = setup(baseHandler)
    render(<UploadPanel capability={capability} caseId={CASE} mockMode={false} />)
    await screen.findByLabelText('Vybrat soubory k nahrání')
    const big = new File([new Uint8Array(6 * 1024 * 1024)], 'velky.pdf')
    fireEvent.change(screen.getByLabelText('Vybrat soubory k nahrání'), { target: { files: [big] } })
    expect(await screen.findByText(/větší než 5 MiB/)).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Vybrat soubory k nahrání'), { target: { files: [new File(['x'], 'run.exe')] } })
    expect(await screen.findByText(/Spustitelné soubory server nepřijímá/)).toBeInTheDocument()
    expect(seen.filter(route => route.init.method === 'POST')).toHaveLength(0)
  })

  it('drops cached names and jobs when the case or account changes', async () => {
    const { capability } = setup(route => {
      if (route.url === '/api/v1/uploads/capabilities') return json(capsBody())
      if (route.url.includes('synthetic-9')) return json({ version: 1, jobs: [] })
      return json({ version: 1, jobs: [jobBody()] })
    })
    const view = render(<UploadPanel capability={capability} caseId={CASE} mockMode={false} />)
    expect(await screen.findByText('zprava.pdf')).toBeInTheDocument()
    view.rerender(<UploadPanel capability={capability} caseId="synthetic-9" mockMode={false} />)
    await waitFor(() => expect(screen.queryByText('zprava.pdf')).toBeNull())
    view.rerender(<UploadPanel capability={null} caseId="synthetic-9" mockMode={false} />)
    expect(screen.getByText('Nahrávání není v tomto pohledu k dispozici.')).toBeInTheDocument()
  })

  it('sends several files one by one without doubling', async () => {
    const posted: string[] = []
    let inFlight = 0
    let maxFlight = 0
    const { capability } = setup(route => {
      if (route.url === '/api/v1/uploads/capabilities') return json(capsBody())
      if (route.init.method === 'GET') return json({ version: 1, jobs: [] })
      const headers = route.init.headers as Record<string, string>
      const uploadName = headers['X-Upload-Name']
      if (uploadName === undefined) throw new Error('Missing upload filename header')
      posted.push(uploadName)
      inFlight += 1
      maxFlight = Math.max(maxFlight, inFlight)
      const id = posted.length === 1 ? 'a'.repeat(32) : 'b'.repeat(32)
      return new Promise<Response>(resolve => {
        setTimeout(() => {
          inFlight -= 1
          resolve(json({ version: 1, job: jobBody({ id, filename: decodeURIComponent(uploadName) }) }, 202))
        }, 20)
      })
    })
    render(<UploadPanel capability={capability} caseId={CASE} mockMode={false} />)
    fireEvent.change(await screen.findByLabelText('Vybrat soubory k nahrání'), {
      target: { files: [new File(['jedna'], 'prvni.pdf'), new File(['dva'], 'druhy.pdf')] },
    })
    await waitFor(() => expect(posted).toEqual(['prvni.pdf', 'druhy.pdf']))
    await waitFor(() => expect(screen.getByText('druhy.pdf')).toBeInTheDocument())
    expect(maxFlight).toBe(1)
  })

  it('rejects a malformed server envelope instead of showing it', async () => {
    const { capability } = setup(route => {
      if (route.url === '/api/v1/uploads/capabilities') return json({ version: 2, enabled: true })
      return json({ version: 1, jobs: [] })
    })
    render(<UploadPanel capability={capability} caseId={CASE} mockMode={false} />)
    expect(await screen.findByText('Odpověď serveru nemá očekávaný tvar.')).toBeInTheDocument()
    expect(screen.queryByLabelText('Vybrat soubory k nahrání')).toBeNull()
  })
})
