/** The app's icons: inline SVG drawn in `currentColor`, hidden from assistive tech. */

/* Inlined as text; see `LogoIcon`. */
import mark from '../logo.svg?raw'

export function CopyIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none"
         stroke="currentColor" strokeWidth="2" strokeLinejoin="round"
         aria-hidden="true">
      <rect x="9" y="9" width="11" height="11" rx="2" />
      <path d="M5 15V5a2 2 0 0 1 2-2h8" />
    </svg>
  )
}

export function TickIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none"
         stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"
         strokeLinejoin="round" aria-hidden="true">
      <path d="M20 6 9 17l-5-5" />
    </svg>
  )
}

export function RetryIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none"
         stroke="currentColor" strokeWidth="2" strokeLinecap="round"
         aria-hidden="true">
      <path d="M20 11a8 8 0 1 0-2.3 5.7" />
      <path d="M20 5v6h-6" />
    </svg>
  )
}

/** A three-quarter ring; CSS spins it. */
export function SpinnerIcon() {
  return (
    <svg className="spinner" viewBox="0 0 24 24" width="14" height="14"
         fill="none" stroke="currentColor" strokeWidth="2.2"
         strokeLinecap="round" aria-hidden="true">
      <path d="M21 12a9 9 0 1 1-9-9" />
    </svg>
  )
}

export function MoreIcon() {
  return (
    <svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor"
         aria-hidden="true">
      <circle cx="5" cy="12" r="1.7" />
      <circle cx="12" cy="12" r="1.7" />
      <circle cx="19" cy="12" r="1.7" />
    </svg>
  )
}

export function PinIcon() {
  return (
    <svg className="pin" viewBox="0 0 24 24" width="13" height="13" fill="none"
         stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"
         strokeLinejoin="round" aria-hidden="true">
      <path d="M9 4h6l-1 5 3 3v2H7v-2l3-3z" />
      <path d="M12 14v6" />
    </svg>
  )
}

export function TrashIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none"
         stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"
         strokeLinejoin="round" aria-hidden="true">
      <path d="M4 7h16M10 4h4M9 7v12M15 7v12M6 7l1 13h10l1-13" />
    </svg>
  )
}

/*
 * The logo, inlined from `logo.svg` (also the favicon) so `currentColor`
 * picks up the surrounding accent and theme; an <img> or a cross-file
 * <use> would not.  The file's own width/height (24) are for the favicon,
 * since Chrome ignores an SVG icon without an intrinsic size; `--logo-size`
 * overrides them here.
 */
export function LogoIcon({ size = 22 }: { size?: number }) {
  return (
    <span className="logo" aria-hidden="true"
          style={{ '--logo-size': `${size}px` } as React.CSSProperties}
          dangerouslySetInnerHTML={{ __html: mark }} />
  )
}

export function BookIcon() {
  return (
    <svg viewBox="0 0 24 24" width="17" height="17" fill="none"
         stroke="currentColor" strokeWidth="1.7" strokeLinecap="round"
         strokeLinejoin="round" aria-hidden="true">
      <path d="M4 4.5A1.5 1.5 0 0 1 5.5 3H12v18H5.5A1.5 1.5 0 0 1 4 19.5z" />
      <path d="M20 4.5A1.5 1.5 0 0 0 18.5 3H12v18h6.5a1.5 1.5 0 0 0 1.5-1.5z" />
    </svg>
  )
}

export function PaneIcon() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none"
         stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round"
         aria-hidden="true">
      <rect x="3" y="4.5" width="18" height="15" rx="2" />
      <path d="M9.5 4.5v15" />
    </svg>
  )
}

export function PlusIcon() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none"
         stroke="currentColor" strokeWidth="2" strokeLinecap="round"
         aria-hidden="true">
      <path d="M12 5v14M5 12h14" />
    </svg>
  )
}

export function SunIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none"
         stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"
         aria-hidden="true">
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2.6v2.2M12 19.2v2.2M4.3 4.3l1.6 1.6M18.1 18.1l1.6 1.6M2.6 12h2.2M19.2 12h2.2M4.3 19.7l1.6-1.6M18.1 5.9l1.6-1.6" />
    </svg>
  )
}

export function MoonIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none"
         stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"
         strokeLinejoin="round" aria-hidden="true">
      <path d="M20 14.4A8.5 8.5 0 0 1 9.6 4a8.5 8.5 0 1 0 10.4 10.4z" />
    </svg>
  )
}

export function AutoIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none"
         stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <circle cx="12" cy="12" r="8.4" />
      <path d="M12 3.6a8.4 8.4 0 0 1 0 16.8z" fill="currentColor" stroke="none" />
    </svg>
  )
}

export function GraphIcon() {
  return (
    <svg viewBox="0 0 24 24" width="17" height="17" fill="none"
         stroke="currentColor" strokeWidth="1.7" strokeLinecap="round"
         strokeLinejoin="round" aria-hidden="true">
      <circle cx="12" cy="5" r="2.4" />
      <circle cx="5" cy="18" r="2.4" />
      <circle cx="19" cy="18" r="2.4" />
      <path d="M10.4 7 6.6 15.8M13.6 7l3.8 8.8M7.4 18h9.2" />
    </svg>
  )
}

export function DownloadIcon() {
  return (
    <svg viewBox="0 0 24 24" width="17" height="17" fill="none"
         stroke="currentColor" strokeWidth="1.7" strokeLinecap="round"
         strokeLinejoin="round" aria-hidden="true">
      <path d="M12 4v11M7 10.5l5 5 5-5M5 20h14" />
    </svg>
  )
}

export function FolderIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none"
         stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round"
         aria-hidden="true">
      <path d="M3 6.5A1.5 1.5 0 0 1 4.5 5H9l2 2h8.5A1.5 1.5 0 0 1 21 8.5v9a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 17.5z" />
    </svg>
  )
}

/** Points right; CSS turns it down when what it heads is open. */
export function ChevronIcon() {
  return (
    <svg className="chevron" viewBox="0 0 24 24" width="12" height="12"
         fill="none" stroke="currentColor" strokeWidth="2.2"
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="m9 6 6 6-6 6" />
    </svg>
  )
}
