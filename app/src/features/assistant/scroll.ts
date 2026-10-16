interface RevealInput {
  /** Top of the newest turn inside the scroll container. */
  readonly turnTop: number
  readonly turnHeight: number
  /** Visible height of the scroll container. */
  readonly viewport: number
  readonly scrollHeight: number
}

/** Where to scroll for a newly added turn: a turn that fits is shown whole at the bottom;
    a taller one is shown from its start (sender line and first line), never its tail. */
export function revealScrollTop({ turnTop, turnHeight, viewport, scrollHeight }: RevealInput): number {
  const bottom = Math.max(0, scrollHeight - viewport)
  if (turnHeight <= viewport) return bottom
  return Math.min(bottom, Math.max(0, turnTop - 8))
}
