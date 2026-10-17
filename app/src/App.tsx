import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import type { BootstrapResult, Session } from './data/contracts'
import { buildAssistantContext } from './assistant/context'
import { useAssistant } from './assistant/useAssistant'
import { isAssistantRole } from './assistant/validation'
import { AssistantPanel } from './features/assistant/AssistantPanel'
import { DetailScopeProvider } from './features/shared/detailScope'
import { IconSprite } from './icons/IconSprite'
import { AppBar } from './components/shell/AppBar'
import { InvalidViewState } from './components/shell/DataState'
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

interface AppProps {
  readonly boot: Promise<BootstrapResult>
  readonly authed?: boolean
  readonly onLogout?: (() => void) | undefined
  readonly loggingOut?: boolean
  /** Demo entry only: show just this role's view and hide the role picker. Presentation, not authorization. */
  readonly lockedRole?: ViewId
  readonly onExitDemo?: () => void
}

/** Composition root. Receives the one bootstrapped session promise (created once per page). */
export function App({ boot, authed, onLogout, loggingOut, lockedRole, onExitDemo }: AppProps) {
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
  const { route, view, navigationId, navigated, focus, restoration, navigate, returnToList, resetNavigation } = nav
  const routeIdentity = routeKey(route)
  // Demo role lock: a typed or stale hash for another role goes back to the chosen role's own start.
  const foreignView = lockedRole !== undefined && view !== lockedRole
  useEffect(() => { if (foreignView) navigate(roleRoute(lockedRole), { replace: true }) }, [foreignView, lockedRole, navigate])
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

  const skipToContent = useCallback(() => {
    const content = document.getElementById('obsah')
    content?.scrollIntoView({ block: 'start' })
    content?.focus({ preventScroll: true })
  }, [])

  // Assistant: in-memory only. resetKey bumps synchronously at reset START (before the demo
  // mutation finishes) so no transcript or context from the pre-reset state survives.
  const [assistantOpen, setAssistantOpen] = useState(false)
  const [resetKey, setResetKey] = useState(0)
  const resetDemo = useCallback(() => {
    setResetKey(value => value + 1)
    setPreviewId(null)
    resetNavigation()
    actions.reset()
  }, [actions, resetNavigation, setPreviewId])
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

  // Case-detail disclosures: closed on any session/role/case/revision/reset change, and not
  // openable while the shown case is a retained snapshot or a local change is running.
  const detailScope = useMemo(() => ({
    key: JSON.stringify([sessionId(session), routeIdentity, effectiveId, version, resetKey, preparationRevision]),
    live: contextFresh,
  }), [session, routeIdentity, effectiveId, version, resetKey, preparationRevision, contextFresh])

  const appbarRef = useRef<HTMLElement>(null)
  useStickyOffsets(appbarRef)

  const roleProps = { workspace, detail, actions, route, onNavigate: navigate, detailFresh: contextFresh, authed }
  const clinicianNav = { route, onNavigate: navigate, onReturn: returnToList }
  const views: Record<ViewId, ReactNode> = {
    koordinator: <CoordinatorView {...roleProps} {...clinicianNav} />,
    pacient: <PatientRoleView {...roleProps} />,
    lekar: <DoctorView {...roleProps} {...clinicianNav} />,
    mdt: <MdtView {...roleProps} {...clinicianNav} />,
    specimen: <SpecimenView />,
  }

  return (
    <>
      <IconSprite />
      <a className="skip-link" href="#obsah" onClick={event => { if (!isPlainActivation(event)) return; event.preventDefault(); skipToContent() }}>Přeskočit na obsah</a>
      <AppBar ref={appbarRef} onLogout={onLogout} loggingOut={loggingOut} onExitDemo={onExitDemo} onResetDemo={actions.available ? resetDemo : undefined} demo={session?.mode === 'mock'} />
      <main id="obsah" className="content" tabIndex={-1}>
        {actions.feedback && (
          <p className={actions.feedback.tone === 'error' ? 'demo-feedback is-error' : 'demo-feedback'} role="status">{actions.feedback.text}</p>
        )}
        {isAssistantRole(view) && (
          <AssistantPanel
            assistant={assistant}
            view={view}
            expanded={assistantOpen}
            onToggle={() => setAssistantOpen(open => !open)}
            contextReason={contextReason}
          />
        )}
        <section className={view === 'pacient' ? 'view view--patient' : 'view'} id={view} aria-labelledby={`t-${view}`}>
          <DetailScopeProvider value={detailScope}>{foreignView ? null : route.page === 'invalid-view'
            ? <InvalidViewState view={view} onReturn={() => navigate(roleRoute(view), { replace: true })} />
            : views[view]}</DetailScopeProvider>
        </section>
      </main>
    </>
  )
}
