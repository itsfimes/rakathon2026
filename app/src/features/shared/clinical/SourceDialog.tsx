import { useEffect, useId, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Icon } from '../../../icons/Icon'
import { useDetailScope } from '../detailScope'

interface SourceDialogProps {
  /** Compact trigger text, same wording as the inline disclosure. */
  readonly summary: string
  readonly title: string
  readonly children: ReactNode
}

/** Source inspector for table cells: a compact trigger plus a native modal dialog rendered on <body>,
    so opening it never changes the row, the column widths or the page scroll. The browser handles
    Escape, focus containment and background inertness; focus returns to the exact trigger on close.
    A case/revision change remounts (scope key) and closes it without moving focus. */
export function SourceDialog({ summary, title, children }: SourceDialogProps) {
  const { key, live } = useDetailScope()
  if (!live) return <p className="source-trigger source-trigger--pending"><Icon name="clock" />{summary} · podrobnosti po načtení aktuálního stavu</p>
  return <ScopedSourceDialog key={key} summary={summary} title={title}>{children}</ScopedSourceDialog>
}

function ScopedSourceDialog({ summary, title, children }: SourceDialogProps) {
  const [open, setOpen] = useState(false)
  const trigger = useRef<HTMLButtonElement>(null)
  const dialog = useRef<HTMLDialogElement>(null)
  const heading = useRef<HTMLHeadingElement>(null)
  const titleId = useId()
  const mounted = useRef(true)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])

  useEffect(() => {
    const node = dialog.current
    if (!open || !node) return
    if (!node.open) node.showModal()
    heading.current?.focus()
    // Unmount (case change, navigation) closes silently: focus is not pulled back to a stale trigger.
    return () => { if (node.open) node.close() }
  }, [open])

  const onClose = () => {
    if (!mounted.current) return
    setOpen(false)
    if (trigger.current?.isConnected) trigger.current.focus()
  }

  return <>
    <button ref={trigger} type="button" className="source-trigger" aria-haspopup="dialog" onClick={() => setOpen(true)}>
      <Icon name="file" /><span>{summary}</span>
    </button>
    {open && createPortal(
      <dialog ref={dialog} className="source-dialog" aria-labelledby={titleId} onClose={onClose}
        onClick={event => { if (event.target === event.currentTarget) dialog.current?.close() }}>
        <header className="source-dialog__head">
          <h2 ref={heading} id={titleId} tabIndex={-1} className="source-dialog__title">{title}</h2>
          <button type="button" className="btn btn--secondary" onClick={() => dialog.current?.close()}>Zavřít</button>
        </header>
        <div className="source-dialog__body">{children}</div>
      </dialog>,
      document.body,
    )}
  </>
}
