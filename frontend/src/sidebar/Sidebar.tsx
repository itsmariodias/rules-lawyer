/**
 * The thread list: brand, new conversation, pinned and other threads with a
 * row menu (pin, delete with confirmation), graph status and theme.
 * Collapsed, it is a rail of expand and new-conversation only.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import type { Thread } from '../api'
import { useGraphStatus } from './useGraphStatus'
import { useTheme, type Theme } from '../shared/useStored'
import {
  AutoIcon, LogoIcon, MoonIcon, MoreIcon, PaneIcon, PinIcon, PlusIcon,
  SunIcon, TrashIcon,
} from '../shared/icons'

type Props = {
  threads: Thread[]
  /** The thread on screen, highlighted in the list. */
  activeId: string | null
  /** The full list when true, the rail when false. */
  expanded: boolean
  onExpand: (expanded: boolean) => void
  onOpen: (threadId: string) => void
  onNew: () => void
  onPin: (threadId: string, pinned: boolean) => void
  /** Rejects to keep the confirmation open with the reason. */
  onForget: (threadId: string) => Promise<void>
}

export function Sidebar({ threads, activeId, expanded, onExpand, onOpen, onNew,
                          onPin, onForget }: Props) {
  const graph = useGraphStatus()
  const [theme, setTheme] = useTheme()
  // Thread awaiting delete confirmation, and the last delete error.
  const [arming, setArming] = useState<string | null>(null)
  const [failed, setFailed] = useState<string | null>(null)
  // The open row menu and its screen position.
  const [menu, setMenu] = useState<{ id: string; x: number; y: number } | null>(null)
  // Stable: the menu's listeners depend on it, and every token re-renders.
  const closeMenu = useCallback(() => setMenu(null), [])

  const pinned = threads.filter((thread) => thread.pinned)
  const rest = threads.filter((thread) => !thread.pinned)

  const threadList = (group: Thread[]) => (
    <ul className="thread-list">
      {group.map((thread) => (
        <ThreadRow key={thread.thread_id} thread={thread}
                   active={thread.thread_id === activeId}
                   menuOpen={menu?.id === thread.thread_id}
                   onOpen={() => onOpen(thread.thread_id)}
                   onMenu={(at) => setMenu(
                     menu?.id === thread.thread_id
                       ? null
                       : { id: thread.thread_id, ...at })} />
      ))}
    </ul>
  )

  if (!expanded) {
    return (
      <nav className="rail">
        {/* One button showing the logo, swapped for the pane icon on hover;
            both keep their open-sidebar sizes. */}
        <button className="collapse rail-mark" title="Show the thread list"
                aria-label="Show the thread list" aria-expanded={false}
                onClick={() => onExpand(true)}>
          <LogoIcon />
          <PaneIcon />
        </button>
        <button className="collapse rail-new" title="New conversation"
                aria-label="New conversation" onClick={onNew}>
          <PlusIcon />
        </button>
      </nav>
    )
  }

  return (
    <>
      <nav className="sidebar">
        <div className="brand">
          <LogoIcon />Rules Lawyer
          <button className="collapse" title="Hide the thread list"
                  aria-label="Hide the thread list" aria-expanded={true}
                  onClick={() => onExpand(false)}>
            <PaneIcon />
          </button>
        </div>
        <button className="new" onClick={onNew}><PlusIcon />New conversation</button>
        {/* "Pinned" only when non-empty; "Conversations" whenever any. */}
        <div className="threads">
          {pinned.length > 0 && (
            <>
              <h2 className="thread-group">Pinned</h2>
              {threadList(pinned)}
            </>
          )}
          {rest.length > 0 && <h2 className="thread-group">Conversations</h2>}
          {threadList(rest)}
        </div>
        {menu && (
          <ThreadMenu
            at={menu}
            pinned={threads.find((t) => t.thread_id === menu.id)?.pinned ?? false}
            onClose={closeMenu}
            onPin={(pinned) => {
              setMenu(null)
              onPin(menu.id, pinned)
            }}
            onDelete={() => {
              setMenu(null)
              setFailed(null)
              setArming(menu.id)
            }} />
        )}
        {/* Graph status: hidden while checking; the word carries the meaning
            so colour is not required. */}
        <footer className="sidebar-foot">
          <span className={`graph-status ${graph}`}>
            {graph !== 'checking' && (<>
              <i className="dot" aria-hidden="true" />
              <span>graph {graph}</span>
            </>)}
          </span>
          <ThemeSwitch theme={theme} onPick={setTheme} />
        </footer>
      </nav>
      {/* Outside the nav, which narrow windows hide with display: none. */}
      {arming && (
        <ConfirmDelete
          title={threads.find((t) => t.thread_id === arming)?.title ?? ''}
          failed={failed}
          onCancel={() => { setArming(null); setFailed(null) }}
          onDelete={() => {
            // Stays open on failure so the error is seen.
            onForget(arming)
              .then(() => { setArming(null); setFailed(null) })
              .catch((problem) => setFailed(String(problem)))
          }} />
      )}
    </>
  )
}

/** A thread row.  Its menu button shows on hover, focus, or while its menu is open. */
function ThreadRow({ thread, active, menuOpen, onOpen, onMenu }: {
  thread: Thread
  active: boolean
  menuOpen: boolean
  onOpen: () => void
  onMenu: (at: { x: number; y: number }) => void
}) {
  return (
    <li className={`thread ${active ? 'on' : ''} ${menuOpen ? 'menu-open' : ''}`}>
      <button className="thread-open" onClick={onOpen}>
        {thread.pinned && <PinIcon />}
        {thread.title}
      </button>
      <button className="more" aria-haspopup="menu" aria-expanded={menuOpen}
              title={`Options for “${thread.title}”`}
              aria-label={`Options for conversation: ${thread.title}`}
              onClick={(event) => {
                const box = event.currentTarget.getBoundingClientRect()
                onMenu({ x: box.right, y: box.bottom + 4 })
              }}>
        <MoreIcon />
      </button>
    </li>
  )
}

/**
 * Delete confirmation in a native modal `<dialog>` (top layer, focus trap,
 * Escape, backdrop).  Cancel is focused by default: there is no undo.
 */
function ConfirmDelete({ title, failed, onCancel, onDelete }: {
  title: string
  /** Error from the last failed attempt. */
  failed: string | null
  onCancel: () => void
  onDelete: () => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)

  useEffect(() => { dialog.current?.showModal() }, [])

  return (
    <dialog className="modal" ref={dialog}
            aria-labelledby="confirm-delete-title"
            // Escape fires `cancel`; route it through the parent's state
            // rather than letting the dialog close itself.
            onCancel={(event) => { event.preventDefault(); onCancel() }}
            onClick={(event) => {
              if (event.target === dialog.current) onCancel()
            }}>
      <div className="modal-body">
        <h2 id="confirm-delete-title">Delete this conversation?</h2>
        <p className="muted">
          <strong>{title}</strong> and every turn in it. This cannot be undone.
        </p>
        {failed && <p className="error">{failed}</p>}
        <div className="modal-actions">
          <button className="no" onClick={onCancel} autoFocus>Cancel</button>
          <button className="yes" onClick={onDelete}>Delete</button>
        </div>
      </div>
    </dialog>
  )
}

/**
 * Row menu, `position: fixed` at the opening button so the scrolling list
 * cannot clip it.  Closes on outside click, Escape, resize or scroll.
 */
function ThreadMenu({ at, pinned, onClose, onPin, onDelete }: {
  at: { x: number; y: number }
  pinned: boolean
  onClose: () => void
  onPin: (pinned: boolean) => void
  onDelete: () => void
}) {
  const menu = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const away = (event: PointerEvent) => {
      if (!menu.current?.contains(event.target as Node)) onClose()
    }
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    // Deferred so the opening click does not immediately close it.
    const timer = setTimeout(() =>
      document.addEventListener('pointerdown', away), 0)
    document.addEventListener('keydown', key)
    window.addEventListener('resize', onClose)
    window.addEventListener('scroll', onClose, true)
    return () => {
      clearTimeout(timer)
      document.removeEventListener('pointerdown', away)
      document.removeEventListener('keydown', key)
      window.removeEventListener('resize', onClose)
      window.removeEventListener('scroll', onClose, true)
    }
  }, [onClose])

  return (
    <div className="thread-menu" role="menu" ref={menu}
         style={{ left: at.x, top: at.y }}>
      <button role="menuitem" onClick={() => onPin(!pinned)}>
        <PinIcon />{pinned ? 'Unpin' : 'Pin'}
      </button>
      <button role="menuitem" className="danger" onClick={onDelete}>
        <TrashIcon />Delete
      </button>
    </div>
  )
}

/* Three explicit buttons rather than one cycling toggle. */
const THEMES: { value: Theme; label: string; Icon: () => React.JSX.Element }[] = [
  { value: 'light', label: 'Light', Icon: SunIcon },
  { value: 'dark', label: 'Dark', Icon: MoonIcon },
  { value: 'system', label: 'Match the system', Icon: AutoIcon },
]

function ThemeSwitch({ theme, onPick }: {
  theme: Theme
  onPick: (theme: Theme) => void
}) {
  return (
    <div className="theme-switch" role="group" aria-label="Theme">
      {THEMES.map(({ value, label, Icon }) => (
        <button key={value} className={theme === value ? 'on' : ''}
                aria-pressed={theme === value} title={label} aria-label={label}
                onClick={() => onPick(value)}>
          <Icon />
        </button>
      ))}
    </div>
  )
}
