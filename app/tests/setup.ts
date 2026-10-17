import '@testing-library/jest-dom/vitest'

// jsdom has no <dialog> modal API. Minimal bounded stand-in: open attribute + native-like close event.
// Focus containment/inertness are browser features and are verified in a real browser, not here.
if (typeof HTMLDialogElement !== 'undefined' && !HTMLDialogElement.prototype.showModal) {
  HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) { this.setAttribute('open', '') }
  HTMLDialogElement.prototype.show = function show(this: HTMLDialogElement) { this.setAttribute('open', '') }
  HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
    if (!this.hasAttribute('open')) return
    this.removeAttribute('open')
    this.dispatchEvent(new Event('close'))
  }
}

if (typeof HTMLDialogElement !== 'undefined' && typeof document !== 'undefined') {
  document.addEventListener('click', event => {
    const button = (event.target as Element | null)?.closest?.('button') as HTMLButtonElement | null
    if (!button || button.type === 'button' || button.disabled || !button.form) return
    if (button.form.getAttribute('method') !== 'dialog') return
    const dialog = button.form.closest('dialog')
    if (!(dialog instanceof HTMLDialogElement) || !dialog.open) return
    event.preventDefault()
    dialog.returnValue = button.value
    dialog.close()
  })
}
// jsdom has no layout scrolling; the app calls these for in-page anchors and route focus.
if (typeof Element !== 'undefined' && !Element.prototype.scrollIntoView) Element.prototype.scrollIntoView = function scrollIntoView() {}
if (typeof window !== 'undefined') window.scrollTo = (() => {}) as typeof window.scrollTo
