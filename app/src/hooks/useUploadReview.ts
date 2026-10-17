import { useCallback, useEffect, useRef, useState } from 'react'
import type { ApprovalReason, ReviewFailure, UploadReview } from '../data/backend/uploadReview'
import type { UploadCapability } from '../data/backend/uploads'

export interface UploadReviewView {
  readonly loading: boolean
  readonly error: string | null
  readonly conflict: number | null
  readonly review: UploadReview | null
  readonly modelText: string | null
  readonly modelLoading: boolean
  readonly modelError: string | null
  readonly text: string
  readonly dirty: boolean
  readonly saving: boolean
  readonly approving: boolean
  readonly approvalEnabled: boolean
  readonly approvalReason: ApprovalReason | null
  readonly confirmed: boolean
  readonly setText: (value: string) => void
  readonly setConfirmed: (value: boolean) => void
  readonly save: () => void
  readonly approve: () => void
  readonly reload: () => void
}

const LOCKED_STATES: readonly string[] = ['importing', 'imported', 'import-uncertain']

function sessionLost(message: string): boolean {
  return message.includes('Relace')
}

export function useUploadReview(capability: UploadCapability | null, caseId: string | null, jobId: string | null): UploadReviewView {
  const [review, setReview] = useState<UploadReview | null>(null)
  const [approvalEnabled, setApprovalEnabled] = useState(false)
  const [approvalReason, setApprovalReason] = useState<ApprovalReason | null>(null)
  const [modelText, setModelText] = useState<string | null>(null)
  const [modelLoading, setModelLoading] = useState(false)
  const [modelError, setModelError] = useState<string | null>(null)
  const [text, setTextState] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [conflict, setConflict] = useState<number | null>(null)
  const [saving, setSaving] = useState(false)
  const [approving, setApproving] = useState(false)
  const [confirmed, setConfirmed] = useState(false)
  const [reloadSeq, setReloadSeq] = useState(0)
  const genRef = useRef(0)
  const loadCtl = useRef<AbortController | null>(null)
  const saveCtl = useRef<AbortController | null>(null)
  const approveCtl = useRef<AbortController | null>(null)
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      loadCtl.current?.abort()
      saveCtl.current?.abort()
    }
  }, [])

  useEffect(() => {
    genRef.current += 1
    const gen = genRef.current
    loadCtl.current?.abort()
    saveCtl.current?.abort()
    approveCtl.current?.abort()
    approveCtl.current = null
    const ctl = new AbortController()
    loadCtl.current = ctl
    setReview(null)
    setApprovalEnabled(false)
    setApprovalReason(null)
    setModelText(null)
    setModelLoading(false)
    setModelError(null)
    setTextState('')
    setError(null)
    setConflict(null)
    setSaving(false)
    setApproving(false)
    setConfirmed(false)
    if (!capability || !caseId || !jobId) {
      setLoading(false)
      return () => {
        ctl.abort()
      }
    }
    const fetchReview = capability.fetchReview?.bind(capability)
    const fetchModelText = capability.fetchModelText?.bind(capability)
    if (!fetchReview || !fetchModelText) {
      setLoading(false)
      setError('Ruční kontrola není k dispozici.')
      return () => {
        ctl.abort()
      }
    }
    const target = jobId
    setLoading(true)
    setModelLoading(true)
    setModelError(null)
    fetchReview(target, ctl.signal).then(result => {
      if (gen !== genRef.current || ctl.signal.aborted || !mountedRef.current) return
      if (!result.ok) {
        applyFailure(result.error)
        setLoading(false)
        return
      }
      setReview(result.value.review)
      setApprovalEnabled(result.value.approvalEnabled)
      setApprovalReason(result.value.approvalReason)
      setTextState(result.value.review.candidateText)
      setError(null)
      setConflict(null)
      setLoading(false)
    })
    fetchModelText(target, ctl.signal).then(result => {
      if (gen !== genRef.current || ctl.signal.aborted || !mountedRef.current) return
      if (result.ok) {
        setModelText(result.value)
        setModelError(null)
        setModelLoading(false)
        return
      }
      if (result.error.code === 'aborted') {
        setModelLoading(false)
        return
      }
      if (sessionLost(result.error.message)) {
        setModelLoading(false)
        setModelError(null)
        applyFailure(result.error)
        return
      }
      setModelError(result.error.message)
      setModelLoading(false)
    })
    return () => {
      ctl.abort()
    }

    function applyFailure(failure: ReviewFailure): void {
      if (failure.code === 'aborted') return
      if (failure.code === 'conflict') setConflict(failure.currentRevision)
      setError(failure.message)
      if (sessionLost(failure.message)) {
        setReview(null)
        setModelText(null)
        setModelLoading(false)
        setModelError(null)
        setTextState('')
        setApprovalEnabled(false)
        setApprovalReason(null)
      }
    }
  }, [capability, caseId, jobId, reloadSeq])

  const setText = useCallback((value: string) => {
    setTextState(value)
  }, [])

  const save = useCallback(() => {
    if (!capability?.saveDraft || !capability.fetchReview || !jobId || !review || saving || approving || loading) return
    if (LOCKED_STATES.includes(review.state)) {
      setError('Záznam je uzamčený a nelze ho dále upravovat.')
      return
    }
    const gen = genRef.current
    const ctl = new AbortController()
    saveCtl.current?.abort()
    saveCtl.current = ctl
    const revision = review.revision
    const candidate = text
    setSaving(true)
    setError(null)
    setConflict(null)
    capability.saveDraft(jobId, revision, candidate, ctl.signal).then(result => {
      if (gen !== genRef.current || ctl.signal.aborted || !mountedRef.current) return
      if (!result.ok) {
        if (result.error.code === 'aborted') {
          setSaving(false)
          return
        }
        if (result.error.code === 'conflict') setConflict(result.error.currentRevision)
        setError(result.error.code === 'conflict'
          ? 'Server má novější verzi. Vaše rozepsané změny zůstávají, načtěte znovu a pak uložte.'
          : result.error.message)
        if (sessionLost(result.error.message)) {
          setReview(null)
          setModelText(null)
          setModelLoading(false)
          setModelError(null)
          setTextState('')
        }
        setSaving(false)
        return
      }
      capability.fetchReview?.(jobId).then(refreshed => {
        if (gen !== genRef.current || !mountedRef.current) return
        if (refreshed.ok) {
          setReview(refreshed.value.review)
          setApprovalEnabled(refreshed.value.approvalEnabled)
          setApprovalReason(refreshed.value.approvalReason)
          setTextState(refreshed.value.review.candidateText)
          setError(null)
          setConflict(null)
        } else {
          setReview(result.value)
          setTextState(result.value.candidateText)
          setApprovalEnabled(false)
          setApprovalReason('unavailable')
          setError(refreshed.error.message)
        }
        setSaving(false)
      })
    })
  }, [capability, jobId, review, text, saving, approving, loading])

  const approve = useCallback(() => {
    if (!capability?.approveReview || !capability.fetchReview || !jobId || !review || saving || approving || loading) return
    if (!review.validation.valid) return
    if (text !== review.candidateText) return
    if (!confirmed) return
    if (!approvalEnabled) return
    if (LOCKED_STATES.includes(review.state)) {
      setError('Záznam je uzamčený a nelze ho dále upravovat.')
      return
    }
    const gen = genRef.current
    const ctl = new AbortController()
    approveCtl.current?.abort()
    approveCtl.current = ctl
    const revision = review.revision
    setApproving(true)
    setError(null)
    setConflict(null)
    capability.approveReview(jobId, revision, ctl.signal).then(result => {
      if (gen !== genRef.current || ctl.signal.aborted || !mountedRef.current) return
      if (approveCtl.current === ctl) approveCtl.current = null
      if (!result.ok) {
        if (result.error.code === 'aborted') {
          setApproving(false)
          return
        }
        if (result.error.code === 'conflict') setConflict(result.error.currentRevision)
        setError(result.error.code === 'conflict'
          ? 'Server má novější verzi. Vaše rozepsané změny zůstávají, načtěte znovu a pak uložte.'
          : result.error.message)
        setApproving(false)
        return
      }
      setConfirmed(false)
      capability.fetchReview?.(jobId).then(refreshed => {
        if (gen !== genRef.current || !mountedRef.current) return
        if (refreshed.ok) {
          setReview(refreshed.value.review)
          setApprovalEnabled(refreshed.value.approvalEnabled)
          setApprovalReason(refreshed.value.approvalReason)
          setTextState(refreshed.value.review.candidateText)
          setError(null)
          setConflict(null)
        } else {
          setReview(result.value)
          setTextState(result.value.candidateText)
          setApprovalEnabled(false)
          setApprovalReason('unavailable')
          setError(refreshed.error.message)
        }
        setApproving(false)
      })
    })
  }, [capability, jobId, review, text, confirmed, approvalEnabled, saving, approving, loading])

  const reload = useCallback(() => {
    setReloadSeq(value => value + 1)
  }, [])

  return {
    loading,
    error,
    conflict,
    review,
    modelText,
    modelLoading,
    modelError,
    text,
    dirty: review !== null && text !== review.candidateText,
    saving,
    approving,
    approvalEnabled,
    approvalReason,
    confirmed,
    setText,
    setConfirmed,
    save,
    approve,
    reload,
  }
}
