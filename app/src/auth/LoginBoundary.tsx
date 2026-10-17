import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { App } from '../App'
import { createBackendSession } from '../data/backend/gateway'
import type { BootstrapResult } from '../data/contracts'
import { parseDataMode } from '../data/mode'
import { bootOnce, resetBootCache } from '../session'
import { Icon } from '../icons/Icon'
import { LoginView } from '../features/auth/LoginView'
import { demoLoginRequest, fetchAuthSession, loginRequest, logoutRequest } from './client'
import type { AuthFailureKind, AuthIdentity, DemoAccount } from './contracts'
import { createRequestScope } from './requestScope'
import { routeFromLocation } from '../lib/routes'
import './auth.css'

type Stage = 'checking' | 'login' | 'ready'

function failureText(kind: AuthFailureKind): string {
  if (kind === 'limited') return 'Příliš mnoho pokusů. Zkuste to prosím za chvíli znovu.'
  return 'Služba není dostupná. Zkuste to prosím později.'
}

export function LoginBoundary() {
  const gate = useMemo(() => {
    const mode = parseDataMode(import.meta.env.VITE_DATA_MODE)
    if (!mode.ok) return { auth: false as const, boot: bootOnce() }
    if (mode.value === 'mock') return { auth: false as const, boot: bootOnce() }
    if (import.meta.env.VITE_BACKEND_API_BASE === undefined) return { auth: false as const, boot: bootOnce() }
    if (import.meta.env.VITE_BACKEND_API_BASE !== '/api/v1') return { auth: false as const, boot: bootOnce() }
    return { auth: true as const, boot: null }
  }, [])
  if (!gate.auth) return <App boot={gate.boot as Promise<BootstrapResult>} />
  return <AuthGate />
}

function AuthGate() {
  const [stage, setStage] = useState<Stage>('checking')
  const [identity, setIdentity] = useState<AuthIdentity | null>(null)
  const [boot, setBoot] = useState<Promise<BootstrapResult> | null>(null)
  const [generation, setGeneration] = useState(0)
  const [notice, setNotice] = useState<string | null>(null)
  const [problem, setProblem] = useState<AuthFailureKind | null>(null)
  const [checkProblem, setCheckProblem] = useState<AuthFailureKind | null>(null)
  const [loginPending, setLoginPending] = useState(false)
  const [loggingOut, setLoggingOut] = useState(false)
  const [logoutWarning, setLogoutWarning] = useState<string | null>(null)
  const [lastUsername, setLastUsername] = useState('')
  const [checkRound, setCheckRound] = useState(0)
  const [demoAccounts, setDemoAccounts] = useState<readonly DemoAccount[] | null>(null)
  const [demoView, setDemoView] = useState<DemoAccount | null>(null)
  const [demoPending, setDemoPending] = useState<DemoAccount | null>(null)
  const [demoProblem, setDemoProblem] = useState<AuthFailureKind | null>(null)
  const scopeRef = useRef(createRequestScope())
  const genRef = useRef(0)
  const abortRef = useRef<AbortController | null>(null)
  const csrfRef = useRef<string | null>(null)
  const loginBusyRef = useRef(false)

  const clearClinical = useCallback(() => {
    genRef.current += 1
    abortRef.current?.abort()
    abortRef.current = null
    loginBusyRef.current = false
    resetBootCache()
    setBoot(null)
    setIdentity(null)
    setDemoView(null)
    setDemoPending(null)
    setDemoProblem(null)
    window.history.replaceState(window.history.state, '', `${window.location.pathname}${window.location.search}`)
  }, [])

  const enterReady = useCallback((next: AuthIdentity) => {
    const gen = genRef.current + 1
    genRef.current = gen
    setGeneration(gen)
    csrfRef.current = next.csrfToken
    setIdentity(next)
    setNotice(null)
    setProblem(null)
    setDemoProblem(null)
    setDemoPending(null)
    setLogoutWarning(null)
    const locked = next.demoView ?? null
    setDemoView(locked)
    if (locked) {
      const current = routeFromLocation(window.location)
      const validSameView = current.view === locked && current.page !== 'invalid-view' && current.page !== 'invalid-detail'
      if (!validSameView) window.history.replaceState(window.history.state, '', `${window.location.pathname}${window.location.search}#${locked}`)
    }
    const controller = new AbortController()
    abortRef.current = controller
    setBoot(createBackendSession(controller.signal, undefined, {
      csrfToken: () => csrfRef.current,
      onUnauthorized: () => {
        if (genRef.current !== gen) return
        clearClinical()
        csrfRef.current = null
        setNotice('Relace vypršela. Přihlaste se prosím znovu.')
        setProblem(null)
        setStage('login')
      },
    }).then(session => ({ status: 'session' as const, session })))
    setStage('ready')
  }, [clearClinical])

  useEffect(() => {
    const apply = scopeRef.current.begin()
    const controller = new AbortController()
    fetchAuthSession(controller.signal).then(result => {
      apply(() => {
        if (result.ok && result.value.authenticated) {
          if (result.value.demoAccounts) setDemoAccounts(result.value.demoAccounts)
          enterReady({ ...result.value.user, csrfToken: result.value.csrfToken, ...(result.value.demoView ? { demoView: result.value.demoView } : {}) })
          return
        }
        if (result.ok) {
          setDemoAccounts(result.value.demoAccounts ?? null)
          setStage('login')
          return
        }
        if (result.error.kind !== 'aborted') setCheckProblem(result.error.kind)
      })
    })
    return () => controller.abort()
  }, [enterReady, checkRound])

  const retryCheck = useCallback(() => {
    setCheckProblem(null)
    setCheckRound(round => round + 1)
  }, [])

  const handleLogin = useCallback((username: string, password: string) => {
    if (loginBusyRef.current) return
    loginBusyRef.current = true
    const apply = scopeRef.current.begin()
    setLoginPending(true)
    setProblem(null)
    setNotice(null)
    const controller = new AbortController()
    loginRequest(username, password, controller.signal).then(result => {
      apply(() => {
        loginBusyRef.current = false
        setLoginPending(false)
        if (result.ok) {
          setLastUsername(result.value.username)
          enterReady(result.value)
          return
        }
        if (result.error.kind !== 'aborted') setProblem(result.error.kind)
      })
    })
  }, [enterReady])

  const handleDemoLogin = useCallback((account: DemoAccount) => {
    if (loginBusyRef.current) return
    loginBusyRef.current = true
    const apply = scopeRef.current.begin()
    setDemoPending(account)
    setDemoProblem(null)
    setNotice(null)
    const controller = new AbortController()
    demoLoginRequest(account, controller.signal).then(result => {
      apply(() => {
        loginBusyRef.current = false
        setDemoPending(null)
        if (result.ok) {
          setLastUsername(result.value.username)
          enterReady(result.value)
          return
        }
        if (result.error.kind !== 'aborted') setDemoProblem(result.error.kind)
      })
    })
  }, [enterReady])

  const handleLogout = useCallback(() => {
    const apply = scopeRef.current.begin()
    const csrf = csrfRef.current
    clearClinical()
    setStage('login')
    setNotice(null)
    setProblem(null)
    setLogoutWarning(null)
    if (!csrf) return
    setLoggingOut(true)
    const controller = new AbortController()
    logoutRequest(csrf, controller.signal).then(result => {
      apply(() => {
        setLoggingOut(false)
        if (result.ok) {
          csrfRef.current = null
          return
        }
        if (result.error.kind !== 'aborted') {
          setLogoutWarning('Odhlášení se na serveru nepodařilo potvrdit. Vaše data jsou skryta. Zkuste to prosím znovu.')
        }
      })
    })
  }, [clearClinical])

  if (stage === 'checking') {
    return (
      <main className="authstate" aria-labelledby="auth-check">
        <h1 id="auth-check" tabIndex={-1}>Ověřování přihlášení</h1>
        {!checkProblem && <p>Chvíli prosím počkejte.</p>}
        {checkProblem && (
          <>
            <p role="alert">{failureText(checkProblem)}</p>
            <div className="btn-row">
              <button type="button" className="btn" onClick={retryCheck}>Zkusit znovu</button>
            </div>
          </>
        )}
      </main>
    )
  }

  if (stage === 'login' || !identity || !boot) {
    return (
      <>
        {logoutWarning && (
          <div className="authbar" role="alert">
            <span className="authbar__label"><Icon name="alert" />Odhlášení nebylo potvrzeno</span>
            <span className="authbar__detail">{logoutWarning}</span>
            <span className="authbar__actions">
              <button type="button" className="btn btn--secondary" onClick={handleLogout} disabled={loggingOut}>
                {loggingOut ? 'Odhlašování…' : 'Zkusit znovu'}
              </button>
            </span>
          </div>
        )}
        <LoginView
          initialUsername={lastUsername}
          notice={notice}
          problem={problem}
          pending={loginPending}
          disabled={loggingOut || loginPending || demoPending !== null}
          onLogin={handleLogin}
          demoAccounts={demoAccounts}
          demoPending={demoPending}
          demoProblem={demoProblem}
          onDemoLogin={handleDemoLogin}
        />
      </>
    )
  }

  return (
    <>
      <div className="authbar" role="region" aria-label="Přihlášení">
        <span className="authbar__label"><Icon name="person" />Přihlášeno: {identity.username}</span>
        <span className="authbar__detail">Přihlášení ověřuje server. Zobrazení určuje vaše role.</span>
        <span className="authbar__actions">
          <button type="button" className="btn btn--secondary" onClick={handleLogout} disabled={loggingOut}>
            {loggingOut ? 'Odhlašování…' : 'Odhlásit'}
          </button>
        </span>
      </div>
      <App key={generation} boot={boot} authed lockedView={demoView} />
    </>
  )
}
