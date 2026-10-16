import '@testing-library/jest-dom/vitest'

// jsdom has no <dialog> modal API. Minimal bounded stand-in: open attribute + native-like close event.
// Focus containment/inertness are browser features and are verified in a real browser, not here.
if (typeof HTMLDialogElement !== 'undefined' && !HTMLDialogElement.prototype.showModal) {
  HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) { this.setAttribute('open', '') }
  HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
    if (!this.hasAttribute('open')) return
    this.removeAttribute('open')
    this.dispatchEvent(new Event('close'))
  }
}

// jsdom has no layout scrolling; the app calls these for in-page anchors and route focus.
if (typeof Element !== 'undefined' && !Element.prototype.scrollIntoView) Element.prototype.scrollIntoView = function scrollIntoView() {}
if (typeof window !== 'undefined') window.scrollTo = (() => {}) as typeof window.scrollTo
