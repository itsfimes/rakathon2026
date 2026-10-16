export interface RequestScope {
  begin: () => (apply: () => void) => void
}

export function createRequestScope(): RequestScope {
  let current = 0
  return {
    begin: () => {
      current += 1
      const id = current
      return apply => {
        if (current === id) apply()
      }
    },
  }
}
