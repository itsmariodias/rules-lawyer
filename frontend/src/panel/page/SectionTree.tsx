/**
 * Where the open section sits in the book: a breadcrumb from the book down
 * to the section (SRD › Classes › Rogue), ending in a dropdown of its
 * subsections.  With nothing open, the dropdown lists the book's top-level
 * sections.  Every crumb and entry but the open section navigates to it.
 */

import { useEffect, useRef, useState } from 'react'
import type { SourceExcerpt } from '../../api'
import { BookIcon, ChevronIcon, FolderIcon } from '../../shared/icons'

type Entry = { id: string; heading: string }

type Props = {
  /** The open section's id; null for the whole book. */
  sectionId: string | null
  /** The open section, once loaded. */
  excerpt: SourceExcerpt | null
  /** The top-level sections, listed when nothing is open. */
  roots: Entry[]
  loading: boolean
  error: string | null
  /** A section id, or null for the whole book. */
  onNavigate: (sectionId: string | null) => void
}

export function SectionTree({ sectionId, excerpt, roots, loading, error, onNavigate }: Props) {
  const isBookOpen = sectionId === null
  const below = isBookOpen ? roots : excerpt?.children ?? []
  const belowName = isBookOpen ? 'Sections' : 'Subsections'

  return (
    <nav className="section-tree" aria-label="Location in the book">
      <ol className="crumbs">
        <li>
          {isBookOpen ? (
            <span className="crumb" aria-current="location">
              <BookIcon /><span>SRD</span>
            </span>
          ) : (
            <button className="crumb" onClick={() => onNavigate(null)}>
              <BookIcon /><span>SRD</span>
            </button>
          )}
          {isBookOpen && below.length > 0 && (
            <Dropdown name={belowName} entries={below} onNavigate={onNavigate} />
          )}
        </li>
        {excerpt?.ancestors.map((ancestor) => (
          <li key={ancestor.id}>
            <button className="crumb" title={ancestor.id}
                    onClick={() => onNavigate(ancestor.id)}>
              <span>{ancestor.heading}</span>
            </button>
          </li>
        ))}
        {excerpt && (
          <li>
            <span className="crumb" aria-current="location" title={excerpt.section_id}>
              <span>{excerpt.heading ?? excerpt.section_id}</span>
            </span>
            {below.length > 0 && (
              <Dropdown name={belowName} entries={below} onNavigate={onNavigate} />
            )}
          </li>
        )}
      </ol>
      {excerpt?.entity_type && (
        <span className="tree-type">{excerpt.entity_type.replaceAll('_', ' ')}</span>
      )}
      {loading && <span className="tree-note muted">Loading…</span>}
      {error && <span className="tree-note error">{error}</span>}
    </nav>
  )
}

/**
 * A button opening a menu of sections under it.  Closes on a choice, an
 * outside press or Escape (which hands focus back to the button).
 */
function Dropdown({ name, entries, onNavigate }: {
  name: string
  entries: Entry[]
  onNavigate: (sectionId: string) => void
}) {
  const [open, setOpen] = useState(false)
  const button = useRef<HTMLButtonElement>(null)
  const menu = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    menu.current?.querySelector('button')?.focus()
    // A press on the button is not outside: closing on `pointerdown` would
    // let the `click` after it open the menu again.
    const away = (event: PointerEvent) => {
      const target = event.target as Node
      if (!menu.current?.contains(target) && !button.current?.contains(target)) {
        setOpen(false)
      }
    }
    const key = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      setOpen(false)
      button.current?.focus()
    }
    document.addEventListener('pointerdown', away)
    document.addEventListener('keydown', key)
    return () => {
      document.removeEventListener('pointerdown', away)
      document.removeEventListener('keydown', key)
    }
  }, [open])

  return (
    <>
      <button ref={button} className={open ? 'crumb-more open' : 'crumb-more'}
              aria-haspopup="menu" aria-expanded={open}
              aria-label={`${name} (${entries.length})`}
              title={`${name} (${entries.length})`}
              onClick={() => setOpen(!open)}>
        <ChevronIcon /><span>{entries.length}</span>
      </button>
      {open && (
        <div className="tree-menu" role="menu" aria-label={name} ref={menu}>
          {entries.map((entry) => (
            <button key={entry.id} role="menuitem" title={entry.id}
                    onClick={() => { setOpen(false); onNavigate(entry.id) }}>
              <FolderIcon /><span>{entry.heading}</span>
            </button>
          ))}
        </div>
      )}
    </>
  )
}
