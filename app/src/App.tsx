import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import type { BootstrapResult, Session } from './data/contracts'
import { buildAssistantContext } from './assistant/context'
import { useAssistant } from './assistant/useAssistant'
import { isAssistantRole } from './assistant/validation'
import { AssistantDialog } from './features/assistant/AssistantDialog'
import { DetailScopeProvider } from './features/shared/detailScope'
import { IconSprite } from './icons/IconSprite'
import { AppBar } from './components/shell/AppBar'
import { ModeStrip } from './components/shell/ModeStrip'
import { InvalidViewState } from './components/shell/DataState'
import type { ModeStripState } from './components/shell/ModeStrip'
import { useCaseDetail, useWorkspace } from './hooks/useCaseData'
import { useDemoActions } from './hooks/useDemoActions'
import { useStickyOffsets } from './hooks/useStickyOffsets'
import { useView } from './hooks/useView'
import { CoordinatorView } from './features/coordinator/CoordinatorView'
import { DoctorView } from './features/doctor/DoctorView'
import { MdtView } from './features/mdt/MdtView'
import { PatientRoleView } from './features/patient/PatientView'
import { SpecimenView } from './features/specimen/SpecimenView'
import type { ViewId } from './lib/roles'
import { roleRoute, routeKey } from './lib/routes'
import { caseRowId, isPlainActivation } from './features/shared/routeActivation'

const sessionIds = new WeakMap<Session, number>()
let sessionCount = 0
/** Stable small number per session object, for local invalidation keys only. */
function sessionId(session: Session | null): number {
  if (!session) return 0
  if (!sessionIds.has(session)) sessionIds.set(session, ++sessionCount)
  return sessionIds.get(session)!
}

type Boot =
  | { readonly status: 'starting' }
  | { readonly status: 'configuration-error'; readonly message: string }
  | { readonly status: 'session'; readonly session: Session }

/** Composition root. Receives the one bootstrapped session promise (created once per page). */
export function App({ boot, authed, lockedView }: { readonly boot: Promise<BootstrapResult>; readonly authed?: boolean; readonly lockedView?: ViewId | null }) {
  const [state, setState] = useState<Boot>({ status: 'starting' })
  useEffect(() => {
    let active = true
    boot.then(
      result => {
        if (!active) return
        setState(result.status === 'session'
          ? { status: 'session', session: result.session }
          : { status: 'configuration-error', message: result.error.message })
      },
      (reason: unknown) => {
        if (active) setState({ status: 'configuration-error', message: reason instanceof Error ? reason.message : 'Zdroj dat se nepodařilo spustit.' })
      },
    )
    return () => { active = false }
  }, [boot])

  const session = state.status === 'session' ? state.session : null
  const gateway = session?.gateway ?? null
  const controls = session?.mode === 'mock' ? session.demoControls : null

  const [version, setVersion] = useState(0)
  const refresh = useCallback(() => setVersion(value => value + 1), [])
  const actions = useDemoActions(controls, refresh)

  const workspace = useWorkspace(gateway, version)
  const nav = useView()
  const { navigationId, navigated, focus, restoration, navigate, returnToList, resetNavigation } = nav
  const route = lockedView && nav.route.view !== lockedView ? roleRoute(lockedView) : nav.route
  const view = route.view
  useEffect(() => {
    if (lockedView && nav.route.view !== lockedView) navigate(roleRoute(lockedView), { replace: true })
  }, [lockedView, nav.route, navigate])
  const routeIdentity = routeKey(route)
  // Patient preview: the last case a clinician explicitly opened and that loaded fresh; else the default.
  const [previewId, setPreviewId] = useState<string | null>(null)
  const effectiveId = route.page === 'detail' ? route.caseId
    : (route.page === 'view' || route.page === 'record') && view === 'pacient'
      ? previewId ?? (workspace.status === 'ready' ? workspace.value.defaultCaseId : null)
      : null
  const detail = useCaseDetail(gateway, effectiveId, version)
  // Only clinician selections feed the patient preview; MDT has its own list and exact case pages.
  const loadedExplicitId = route.page === 'detail' && route.view !== 'mdt' && detail.status === 'ready' && detail.fresh
    && detail.value.identity.caseId === route.caseId ? route.caseId : null
  if (loadedExplicitId !== null && loadedExplicitId !== previewId) setPreviewId(loadedExplicitId)

  // Focus once per navigation (never again when data arrives): the page heading, or on a return to a
  // list the row that was opened, restored without the browser scrolling, then the saved scroll position.
  const workspaceReady = workspace.status !== 'loading' && workspace.status !== 'idle'
  const focusedNavigation = useRef(0)
  useEffect(() => {
    if (!navigated || focusedNavigation.current === navigationId) return
    if (focus === 'restore-list' && !workspaceReady) return
    // Consumed only when the frame actually runs: a dependency change that cancels the frame must not
    // swallow this navigation's focus move (it is rescheduled by the next effect run instead).
    const frame = requestAnimationFrame(() => {
      focusedNavigation.current = navigationId
      const heading = document.getElementById(`t-${view}`)
      if (focus === 'restore-list' && restoration) {
        const row = document.getElementById(caseRowId(restoration.role, restoration.caseId))
        ;(row ?? heading)?.focus({ preventScroll: true })
        window.scrollTo(0, restoration.scrollY)
      } else {
        window.scrollTo(0, 0)
        heading?.focus({ preventScroll: true })
      }
    })
    return () => cancelAnimationFrame(frame)
  }, [navigated, navigationId, focus, restoration, view, workspaceReady])

  // In-page anchor (#obsah) only moves focus/scroll; the route hash is never rewritten.
  const skipToContent = useCallback(() => {
    const content = document.getElementById('obsah')
    content?.scrollIntoView({ block: 'start' })
    content?.focus({ preventScroll: true })
  }, [])

  // Assistant: in-memory only. resetKey bumps synchronously at reset START (before the demo
  // mutation finishes) so no transcript or context from the pre-reset state survives.
  const [assistantOpen, setAssistantOpen] = useState(false)
  const [resetKey, setResetKey] = useState(0)
  const assistantTrigger = useRef<HTMLButtonElement>(null)
  const readyDetail = detail.status === 'ready' && detail.fresh && detail.value.identity.caseId === effectiveId ? detail.value : null
  // Fresh only for the current revision and while no local demo change is in flight.
  const contextFresh = readyDetail !== null && !actions.busy
  const preparationRevision = contextFresh ? readyDetail?.mdt.preparation?.revision ?? 'none' : 'unavailable'
  const assistantScopeKey = JSON.stringify([routeIdentity, preparationRevision])
  const assistantContext = useMemo(() => buildAssistantContext(view, readyDetail, contextFresh), [view, readyDetail, contextFresh])
  const assistant = useAssistant({ session, view, caseId: effectiveId, version, resetKey, scopeKey: assistantScopeKey, open: assistantOpen, contextFresh, context: assistantContext,
    binding: isAssistantRole(view) ? readyDetail?.assistantPreview?.[view]?.binding : undefined })
  const contextReason = !isAssistantRole(view) ? 'V tomto pohledu není žádný případ.'
    : session === null || detail.status === 'error' ? 'Data případu nejsou k dispozici.'
      : !contextFresh ? 'Data případu se načítají nebo mění; kontext lze připojit až po načtení.'
        : null
  function closeAssistant() {
    assistant.close()
    setAssistantOpen(false)
  }
  // Any real route change closes the assistant during render (the hook clears and aborts on the scope
  // change). The page heading then owns focus, so the dialog must not pull focus back to its trigger.
  const [routeClosed, setRouteClosed] = useState(false)
  const [assistantRoute, setAssistantRoute] = useState(routeIdentity)
  if (assistantRoute !== routeIdentity) {
    setAssistantRoute(routeIdentity)
    if (assistantOpen) {
      setRouteClosed(true)
      setAssistantOpen(false)
    }
  }
  const skipFocusRestore = useCallback(() => routeClosed, [routeClosed])

  // Case-detail disclosures: closed on any session/role/case/revision/reset change, and not
  // openable while the shown case is a retained snapshot or a local change is running.
  const detailScope = useMemo(() => ({
    key: JSON.stringify([sessionId(session), routeIdentity, effectiveId, version, resetKey, preparationRevision]),
    live: contextFresh,
  }), [session, routeIdentity, effectiveId, version, resetKey, preparationRevision, contextFresh])

  const stripRef = useRef<HTMLDivElement>(null)
  const appbarRef = useRef<HTMLElement>(null)
  useStickyOffsets(stripRef, appbarRef)

  const strip: ModeStripState = useMemo(() => {
    if (state.status === 'starting') return { kind: 'starting' }
    if (state.status === 'configuration-error') return { kind: 'configuration-error', message: state.message }
    return state.session.mode === 'mock'
      ? { kind: 'mock', busy: actions.busy, onReset: () => { setResetKey(value => value + 1); setPreviewId(null); resetNavigation(); actions.reset() } }
      : { kind: 'backend', ...(state.session.connection ? { connection: state.session.connection } : {}) }
  }, [state, actions, resetNavigation, setResetKey, setPreviewId])

  const roleProps = { workspace, detail, actions, route, onNavigate: navigate, detailFresh: contextFresh, authed }
  const clinicianNav = { route, onNavigate: navigate, onReturn: returnToList }
  const uploadCaseId = route.page === 'detail' && route.view !== 'mdt' ? route.caseId : null
  const views: Record<ViewId, ReactNode> = {
    koordinator: <CoordinatorView {...roleProps} {...clinicianNav} />,
    pacient: <PatientRoleView {...roleProps} />,
    lekar: <DoctorView {...roleProps} {...clinicianNav} uploads={gateway?.uploads ?? null} uploadCaseId={uploadCaseId} mockMode={session?.mode === 'mock'} />,
    mdt: <MdtView {...roleProps} {...clinicianNav} />,
    specimen: <SpecimenView />,
  }

  return (
    <>
      <IconSprite />
      <a className="skip-link" href="#obsah" onClick={event => { if (!isPlainActivation(event)) return; event.preventDefault(); skipToContent() }}>Přeskočit na obsah</a>
      <ModeStrip ref={stripRef} state={strip} feedback={actions.feedback} />
      <AppBar ref={appbarRef} view={view} asOf={workspace.status === 'ready' ? workspace.value.asOf : null} demo={session?.mode === 'mock'}
        assistantOpen={assistantOpen} onAssistant={() => { setRouteClosed(false); setAssistantOpen(true) }} assistantRef={assistantTrigger} />
      <main id="obsah" className="content" tabIndex={-1}>
        <section className={view === 'pacient' ? 'view view--patient' : 'view'} id={view} aria-labelledby={`t-${view}`}>
          <DetailScopeProvider value={detailScope}>{route.page === 'invalid-view'
            ? <InvalidViewState view={view} onReturn={() => navigate(roleRoute(view), { replace: true })} />
            : views[view]}</DetailScopeProvider>
        </section>
      </main>
      <AssistantDialog open={assistantOpen} onClose={closeAssistant} assistant={assistant} view={view}
        sourceLabel={session?.mode === 'backend' && session.connection ? session.connection === 'connected' ? 'Backend IRIS · vývojové připojení' : 'Backend IRIS · není dostupný' : undefined}
        mode={strip.kind} contextReason={contextReason} returnFocus={assistantTrigger} skipFocusRestore={skipFocusRestore} />
    </>
  )
}
