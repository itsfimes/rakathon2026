import { useCallback, useEffect, useRef, useState } from 'react'
import { MAX_UPLOAD_BYTES } from '../data/backend/uploads'
import type { UploadCapabilities, UploadCapability, UploadJob } from '../data/backend/uploads'

export type PendingState = 'waiting' | 'uploading' | 'needs-retry' | 'blocked'
export interface PendingFile {
  readonly key: string
  readonly file: File
  readonly state: PendingState
  readonly note: string | null
}
export interface UploadsView {
  readonly caps: UploadCapabilities | null
  readonly capsPending: boolean
  readonly capsNote: string | null
  readonly jobs: readonly UploadJob[]
  readonly jobsNote: string | null
  readonly pending: readonly PendingFile[]
  readonly busy: boolean
  queueFiles(files: readonly File[]): void
  retry(key: string): void
  remove(key: string): void
}
interface Board {
  readonly capability: UploadCapability
  readonly caseId: string
  readonly caps: UploadCapabilities | null
  readonly capsPending: boolean
  readonly capsNote: string | null
  readonly jobs: readonly UploadJob[]
  readonly jobsNote: string | null
  readonly pending: readonly PendingFile[]
  readonly busy: boolean
}

const EXECUTABLE = new Set(['exe', 'com', 'scr', 'pif', 'msi', 'bat', 'cmd', 'ps1', 'vbs', 'jar', 'dll', 'so', 'dylib'])

function extensionOf(name: string): string {
  const dot = name.lastIndexOf('.')
  return dot < 0 ? '' : name.slice(dot + 1).toLowerCase()
}
function freshBoard(capability: UploadCapability, caseId: string): Board {
  return { capability, caseId, caps: null, capsPending: true, capsNote: null, jobs: [], jobsNote: null, pending: [], busy: false }
}
function mergeJobs(current: readonly UploadJob[], next: UploadJob): readonly UploadJob[] {
  const rest = current.filter(job => job.id !== next.id)
  return [next, ...rest].sort((a, b) => (a.createdAt < b.createdAt ? 1 : -1))
}
function sessionLost(message: string): boolean {
  return message.includes('Relace')
}

export function useUploads(capability: UploadCapability | null, caseId: string | null): UploadsView {
  const [board, setBoard] = useState<Board | null>(null)
  const liveRef = useRef({ capability, caseId })
  const idRef = useRef({ capability, caseId })
  const genRef = useRef(0)
  const uploadRef = useRef<{ gen: number; ctl: AbortController } | null>(null)
  const queueRef = useRef<readonly PendingFile[]>([])
  const capsRef = useRef<UploadCapabilities | null>(null)
  const busyRef = useRef(false)
  const lostRef = useRef(false)
  const kickRef = useRef(() => {})
  const seqRef = useRef(0)

  if (board !== null && (board.capability !== capability || board.caseId !== caseId)) {
    setBoard(null)
  }
  const shown = board !== null && board.capability === capability && board.caseId === caseId ? board : null
  const needsBoard = capability !== null && caseId !== null && board === null

  const patch = useCallback((active: { capability: UploadCapability; caseId: string }, fn: (prev: Board) => Board) => {
    setBoard(prev => (prev !== null && prev.capability === active.capability && prev.caseId === active.caseId ? fn(prev) : prev))
  }, [])

  const kick = useCallback(() => {
    const live = liveRef.current
    if (live.capability === null || live.caseId === null || busyRef.current || lostRef.current) return
    const next = queueRef.current.find(item => item.state === 'waiting')
    if (!next) return
    busyRef.current = true
    const active = { capability: live.capability, caseId: live.caseId }
    const gen = genRef.current
    const ctl = new AbortController()
    uploadRef.current = { gen, ctl }
    const setQueue = (items: readonly PendingFile[], busy: boolean) => {
      queueRef.current = items
      patch(active, prev => ({ ...prev, pending: items, busy }))
    }
    setQueue(queueRef.current.map(item => (item.key === next.key ? { ...item, state: 'uploading' as const, note: null } : item)), true)
    next.file.arrayBuffer().then(
      buffer => {
        if (gen !== genRef.current || ctl.signal.aborted) return
        if (liveRef.current.capability !== active.capability || liveRef.current.caseId !== active.caseId) return
        return live.capability?.upload(live.caseId ?? '', next.file.name, buffer, ctl.signal).then(result => {
          if (gen !== genRef.current || ctl.signal.aborted) return
          if (liveRef.current.capability !== active.capability || liveRef.current.caseId !== active.caseId) return
          if (result.ok) {
            const rest = queueRef.current.filter(item => item.key !== next.key)
            queueRef.current = rest
            patch(active, prev => ({ ...prev, pending: rest, busy: false, jobs: mergeJobs(prev.jobs, result.value) }))
            active.capability.listCase(active.caseId).then(listed => {
              if (gen !== genRef.current) return
              if (listed.ok && liveRef.current.capability === active.capability && liveRef.current.caseId === active.caseId) {
                patch(active, prev => ({ ...prev, jobs: listed.value }))
              }
            })
          } else if (result.error.code === 'aborted') {
            const rest = queueRef.current.filter(item => item.key !== next.key)
            queueRef.current = rest
            patch(active, prev => ({ ...prev, pending: rest, busy: false }))
          } else if (sessionLost(result.error.message)) {
            lostRef.current = true
            queueRef.current = []
            patch(active, prev => ({ ...prev, pending: [], jobs: [], jobsNote: result.error.message, busy: false }))
          } else if (result.error.code === 'busy') {
            setQueue(queueRef.current.map(item => (item.key === next.key ? { ...item, state: 'needs-retry' as const, note: result.error.message } : item)), false)
          } else {
            setQueue(queueRef.current.map(item => (item.key === next.key ? { ...item, state: 'blocked' as const, note: result.error.message } : item)), false)
          }
        })
      },
      () => {
        if (gen !== genRef.current || ctl.signal.aborted) return
        if (liveRef.current.capability !== active.capability || liveRef.current.caseId !== active.caseId) return
        setQueue(queueRef.current.map(item => (item.key === next.key ? { ...item, state: 'blocked' as const, note: 'Soubor se nepodařilo přečíst v prohlížeči.' } : item)), false)
      },
    ).finally(() => {
      if (gen !== genRef.current) return
      if (uploadRef.current !== null && uploadRef.current.gen === gen) uploadRef.current = null
      busyRef.current = false
      kickRef.current()
    })
  }, [patch])

  useEffect(() => {
    kickRef.current = kick
  }, [kick])

  useEffect(() => {
    if (idRef.current.capability !== capability || idRef.current.caseId !== caseId) {
      genRef.current += 1
      idRef.current = { capability, caseId }
      uploadRef.current?.ctl.abort()
      uploadRef.current = null
    }
    liveRef.current = { capability, caseId }
    queueRef.current = []
    capsRef.current = null
    busyRef.current = false
    lostRef.current = false
    if (!capability || !caseId) return
    const active = { capability, caseId }
    const gen = genRef.current
    const controller = new AbortController()
    if (needsBoard) {
      capability.capabilities(controller.signal).then(result => {
        if (gen !== genRef.current) return
        if (controller.signal.aborted || liveRef.current.capability !== active.capability || liveRef.current.caseId !== active.caseId) return
        if (!result.ok && result.error.code === 'aborted') return
        if (result.ok) capsRef.current = result.value
        setBoard(prev => {
          if (prev !== null && (prev.capability !== active.capability || prev.caseId !== active.caseId)) return prev
          const base = prev ?? freshBoard(active.capability, active.caseId)
          return result.ok
            ? { ...base, caps: result.value, capsPending: false, capsNote: null }
            : { ...base, caps: null, capsPending: false, capsNote: result.error.message }
        })
      })
      capability.listCase(caseId, controller.signal).then(result => {
        if (gen !== genRef.current) return
        if (controller.signal.aborted || liveRef.current.capability !== active.capability || liveRef.current.caseId !== active.caseId) return
        if (!result.ok && result.error.code === 'aborted') return
        if (!result.ok && sessionLost(result.error.message)) {
          lostRef.current = true
          queueRef.current = []
        }
        setBoard(prev => {
          if (prev !== null && (prev.capability !== active.capability || prev.caseId !== active.caseId)) return prev
          const base = prev ?? freshBoard(active.capability, active.caseId)
          return result.ok
            ? { ...base, jobs: result.value, jobsNote: null }
            : { ...base, jobs: [], jobsNote: result.error.message }
        })
      })
    }
    const timer = window.setInterval(() => {
      if (document.hidden || lostRef.current) return
      active.capability.listCase(active.caseId).then(result => {
        if (gen !== genRef.current) return
        if (liveRef.current.capability !== active.capability || liveRef.current.caseId !== active.caseId) return
        if (!result.ok) {
          if (sessionLost(result.error.message)) {
            lostRef.current = true
            queueRef.current = []
            patch(active, prev => ({ ...prev, pending: [], jobs: [], jobsNote: result.error.message }))
          }
          return
        }
        patch(active, prev => ({ ...prev, jobs: result.value }))
      })
    }, 4000)
    return () => {
      controller.abort()
      window.clearInterval(timer)
    }
  }, [capability, caseId, needsBoard, patch])

  useEffect(() => () => {
    uploadRef.current?.ctl.abort()
  }, [])

  const queueFiles = useCallback((files: readonly File[]) => {
    const live = liveRef.current
    if (live.capability === null || live.caseId === null || lostRef.current) return
    const limit = capsRef.current?.maxFileBytes ?? MAX_UPLOAD_BYTES
    const fresh: PendingFile[] = files.map(file => {
      seqRef.current += 1
      const key = `${seqRef.current}-${file.name}-${file.size}`
      if (EXECUTABLE.has(extensionOf(file.name))) {
        return { key, file, state: 'blocked' as const, note: 'Spustitelné soubory server nepřijímá. Vyberte prosím jiný soubor.' }
      }
      if (file.size > limit || file.size <= 0) {
        return { key, file, state: 'blocked' as const, note: 'Soubor je větší než 5 MiB. Zmenšete ho a zkuste to znovu.' }
      }
      return { key, file, state: 'waiting' as const, note: null }
    })
    const active = { capability: live.capability, caseId: live.caseId }
    queueRef.current = [...queueRef.current, ...fresh]
    patch(active, prev => ({ ...prev, pending: queueRef.current }))
    kick()
  }, [kick, patch])

  const retry = useCallback((key: string) => {
    const live = liveRef.current
    if (live.capability === null || live.caseId === null || lostRef.current) return
    const active = { capability: live.capability, caseId: live.caseId }
    queueRef.current = queueRef.current.map(item => (item.key === key && item.state !== 'uploading' ? { ...item, state: 'waiting' as const, note: null } : item))
    patch(active, prev => ({ ...prev, pending: queueRef.current }))
    kick()
  }, [kick, patch])

  const remove = useCallback((key: string) => {
    const live = liveRef.current
    if (live.capability === null || live.caseId === null) return
    const active = { capability: live.capability, caseId: live.caseId }
    queueRef.current = queueRef.current.filter(item => item.key !== key || item.state === 'uploading')
    patch(active, prev => ({ ...prev, pending: queueRef.current }))
  }, [patch])

  return {
    caps: shown?.caps ?? null,
    capsPending: shown ? shown.capsPending : capability !== null && caseId !== null,
    capsNote: shown?.capsNote ?? null,
    jobs: shown?.jobs ?? [],
    jobsNote: shown?.jobsNote ?? null,
    pending: shown?.pending ?? [],
    busy: shown?.busy ?? false,
    queueFiles,
    retry,
    remove,
  }
}
