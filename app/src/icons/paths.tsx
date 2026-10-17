/* Authored line icons (24-unit viewBox), drawn with one stroke family via the .icon class. */
export const ICON_PATHS = {
  case: <><rect x="5" y="4" width="14" height="17" rx="1.5" /><path d="M9 4V3h6v1M9 11h6M12 8v6" /></>,
  queue: <path d="M9 6h11M9 12h11M9 18h11M4.5 6h.01M4.5 12h.01M4.5 18h.01" />,
  person: <><circle cx="12" cy="8" r="4" /><path d="M4 21c1-4 4-6 8-6s7 2 8 6" /></>,
  steth: <><path d="M5 3v5a4 4 0 0 0 8 0V3M9 12v3a5 5 0 0 0 10 0v-2" /><circle cx="19" cy="11" r="2" /></>,
  team: <><circle cx="9" cy="8" r="3" /><circle cx="17" cy="9" r="2.5" /><path d="M3 20c.5-3.5 3-5 6-5s5.5 1.5 6 5M15.5 14.5c2.5 0 4.5 1.5 5 4.5" /></>,
  layers: <path d="M12 3l9 5-9 5-9-5zM3 13l9 5 9-5" />,
  check: <path d="M5 12.5l4.5 4.5L19 7" />,
  alert: <path d="M12 3.5l9.5 16.5h-19zM12 10v4.5M12 17.5h.01" />,
  missing: <><circle cx="12" cy="12" r="9" /><path d="M9 9l6 6M15 9l-6 6" /></>,
  clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3.5 2" /></>,
  calendar: <><rect x="3" y="5" width="18" height="16" rx="1.5" /><path d="M3 10h18M8 3v4M16 3v4" /></>,
  file: <path d="M6 3h8l4 4v14H6zM14 3v4h4M9 13h6M9 17h6" />,
  building: <path d="M4 21V5h10v16M14 9h6v12M8 9h2M8 13h2M8 17h2M2 21h20" />,
  help: <><circle cx="12" cy="12" r="9" /><path d="M9.5 9.5a2.5 2.5 0 0 1 5 0c0 2-2.5 2-2.5 4M12 17h.01" /></>,
  robot: <><rect x="4" y="8" width="16" height="12" rx="2.5" /><path d="M12 8V4.5M2 13v3M22 13v3M9 13.5h.01M15 13.5h.01M9.5 17h5" /><circle cx="12" cy="3.5" r="1" /></>,
  info: <><circle cx="12" cy="12" r="9" /><path d="M12 11v5M12 8h.01" /></>,
  lock: <><rect x="5" y="11" width="14" height="10" rx="1.5" /><path d="M8 11V8a4 4 0 0 1 8 0v3" /></>,
  eye: <><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z" /><circle cx="12" cy="12" r="3" /></>,
  later: <path d="M6 12h.01M12 12h.01M18 12h.01" />,
  arrow: <path d="M5 12h14M13 6l6 6-6 6" />,
  chevron: <path d="M9 6l6 6-6 6" />,
  flag: <path d="M5 21V4M5 4h12l-2 4 2 4H5" />,
  reset: <path d="M4 12a8 8 0 1 0 2.5-5.8M4 4v4h4" />,
  database: <><ellipse cx="12" cy="6" rx="7" ry="3" /><path d="M5 6v12c0 1.7 3.1 3 7 3s7-1.3 7-3V6M5 12c0 1.7 3.1 3 7 3s7-1.3 7-3" /></>,
} as const

export type IconName = keyof typeof ICON_PATHS
