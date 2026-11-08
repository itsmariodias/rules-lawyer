/**
 * The app shell: thread list, conversation, and side panel.  The panel's
 * tab is held here because both the toolbar and citations set it.
 */

import { useEffect, useRef, useState } from 'react'
import { useChat } from './useChat'
import { useGraphStatus } from './useGraphStatus'
import { useStored, useTheme, type Theme } from './useStored'
import { clampWidth, defaultPanel, Resizer, SIDEBAR } from './components/Resizer'
import { Markdown } from './components/Markdown'
import { ToolTrace } from './components/ToolTrace'
import { Clock, Elapsed, formatDuration } from './components/Timing'
import { Usage } from './components/Usage'
import { SidePanel, type Tab } from './components/SidePanel'
import type { Citation, Thread } from './api'
/* Inlined as text; see `LogoIcon`. */
import mark from './logo.svg?raw'

const EXAMPLES = [
  'What exactly does the Prone condition do?',
  'How does a Rogue’s Sneak Attack scale by level?',
  'Which creatures can inflict the Frightened condition, and how?',
  'What are the components and damage of Fireball?',
]

/** Animated ellipsis.  Three elements, since animating `content` is not portable. */
function Dots() {
  return (
    <span className="dots" aria-hidden="true">
      <i />
      <i />
      <i />
    </span>
  )
}

/** Retry button: an icon, or "Try again" text with `plain` (beside an error). */
function Retry({ plain, onRetry }: { plain?: boolean; onRetry: () => void }) {
  return (
    <button className={plain ? 'retry plain' : 'retry'}
            onClick={onRetry}
            title="Ask this question again"
            aria-label="Ask this question again">
      <RetryIcon />
      {plain && 'Try again'}
    </button>
  )
}

/**
 * Copy the raw markdown, dotted section ids included.  Shows a tick for
 * 1.6s once the write resolves.
 */
function Copy({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!copied) return
    const clear = setTimeout(() => setCopied(false), 1600)
    return () => clearTimeout(clear)
  }, [copied])

  const label = copied ? 'Copied' : 'Copy this answer'
  return (
    <button className={copied ? 'copy copied' : 'copy'}
            onClick={() => {
              // Absent outside a secure context, or may be denied.
              navigator.clipboard?.writeText(text)
                .then(() => setCopied(true))
                .catch(() => setCopied(false))
            }}
            title={label}
            aria-label={label}>
      {copied ? <TickIcon /> : <CopyIcon />}
    </button>
  )
}

function CopyIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none"
         stroke="currentColor" strokeWidth="2" strokeLinejoin="round"
         aria-hidden="true">
      <rect x="9" y="9" width="11" height="11" rx="2" />
      <path d="M5 15V5a2 2 0 0 1 2-2h8" />
    </svg>
  )
}

function TickIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none"
         stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"
         strokeLinejoin="round" aria-hidden="true">
      <path d="M20 6 9 17l-5-5" />
    </svg>
  )
}

function RetryIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none"
         stroke="currentColor" strokeWidth="2" strokeLinecap="round"
         aria-hidden="true">
      <path d="M20 11a8 8 0 1 0-2.3 5.7" />
      <path d="M20 5v6h-6" />
    </svg>
  )
}

export default function App() {
  const { messages, threads, threadId, streaming, send, retry,
          stop, open, reset, forget, pin } = useChat()
  const graph = useGraphStatus()
  const [draft, setDraft] = useState('')
  const [theme, setTheme] = useTheme()
  // Separate from `panelOpen`: the panel can open with nothing cited.
  // Closing it clears the citation, so the toolbar reopens the whole book.
  const [cited, setCited] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('page')
  const [panelOpen, setPanelOpen] = useState(false)
  // Thread awaiting delete confirmation, and the last delete error.
  const [arming, setArming] = useState<string | null>(null)
  const [failed, setFailed] = useState<string | null>(null)
  // The open row menu and its screen position.
  const [menu, setMenu] = useState<{ id: string; x: number; y: number } | null>(null)
  const [panel, setPanel] = useStored('panel-width', defaultPanel())
  // Width the panel clamp should reserve; 0 when the sidebar is hidden.
  const [sidebarOpen, setSidebarOpen] = useStored('sidebar-open', true)
  const sidebarRoom = sidebarOpen ? SIDEBAR : 0
  const end = useRef<HTMLDivElement>(null)

  // Re-clamp on load as well as resize: a width stored on a large display
  // would otherwise squeeze the conversation on a laptop.
  useEffect(() => {
    const fit = () => setPanel(clampWidth(panel, sidebarRoom))
    fit()
    window.addEventListener('resize', fit)
    return () => window.removeEventListener('resize', fit)
  }, [panel, sidebarRoom, setPanel])

  useEffect(() => {
    end.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const submit = (text: string) => {
    setDraft('')
    void send(text)
  }

  // Re-seed the open tab; open on Page if the panel was closed.
  const cite = (sectionId: string) => {
    setCited(sectionId)
    if (!panelOpen) setTab('page')
    setPanelOpen(true)
  }

  const lastAsked = messages.map((message) => message.role).lastIndexOf('user')

  const pinned = threads.filter((thread) => thread.pinned)
  const rest = threads.filter((thread) => !thread.pinned)

  const threadList = (group: Thread[]) => (
    <ul className="thread-list">
      {group.map((thread) => (
        <ThreadRow key={thread.thread_id} thread={thread}
                   active={thread.thread_id === threadId}
                   menuOpen={menu?.id === thread.thread_id}
                   onOpen={() => void open(thread.thread_id)}
                   onMenu={(at) => setMenu(
                     menu?.id === thread.thread_id
                       ? null
                       : { id: thread.thread_id, ...at })} />
      ))}
    </ul>
  )

  const closePanel = () => {
    setPanelOpen(false)
    setCited(null)
  }

  // Clicking the active tab closes the panel; another tab switches to it.
  const toggle = (next: Tab) => {
    if (panelOpen && tab === next) closePanel()
    else { setTab(next); setPanelOpen(true) }
  }

  return (
    <div className={`app ${panelOpen ? 'with-panel' : ''} ${sidebarOpen ? '' : 'no-sidebar'}`}
         style={{
           '--panel': `${panel}px`,
           '--sidebar': `${SIDEBAR}px`,
         } as React.CSSProperties}>
      {sidebarOpen && (
      <nav className="sidebar">
        <div className="brand">
          <LogoIcon />Rules Lawyer
          <button className="collapse" title="Hide the thread list"
                  aria-label="Hide the thread list" aria-expanded={true}
                  onClick={() => setSidebarOpen(false)}>
            <PaneIcon />
          </button>
        </div>
        <button className="new" onClick={reset}><PlusIcon />New conversation</button>
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
            onClose={() => setMenu(null)}
            onPin={(pinned) => {
              setMenu(null)
              void pin(menu.id, pinned)
            }}
            onDelete={() => {
              setMenu(null)
              setFailed(null)
              setArming(menu.id)
            }} />
        )}
        {/* Graph status: hidden while checking; the word carries the
            meaning so colour is not required. */}
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
      )}

      {/* Collapsed sidebar: expand and new-conversation only. */}
      {!sidebarOpen && (
        <nav className="rail">
          {/* One button showing the logo, swapped for the pane icon on
              hover; both keep their open-sidebar sizes. */}
          <button className="collapse rail-mark" title="Show the thread list"
                  aria-label="Show the thread list" aria-expanded={false}
                  onClick={() => setSidebarOpen(true)}>
            <LogoIcon />
            <PaneIcon />
          </button>
          <button className="collapse rail-new" title="New conversation"
                  aria-label="New conversation" onClick={reset}>
            <PlusIcon />
          </button>
        </nav>
      )}

      <main className={`chat ${messages.length === 0 ? 'empty' : ''}`}>
        <header className="chat-head">
          <PanelToggle tab="page" active={panelOpen && tab === 'page'}
                       label="Book page" onClick={toggle} />
          <PanelToggle tab="graph" active={panelOpen && tab === 'graph'}
                       label="Graph" onClick={toggle} />
        </header>

        <div className="messages">
          {messages.length === 0 && (
            <div className="welcome">
              <h1><LogoIcon size={40} />Rules Lawyer</h1>
              <p className="muted">
                Ask anything about the D&amp;D 5e SRD. Answers come from a
                knowledge graph of the book, and every rules claim links to
                the passage it came from.
              </p>
            </div>
          )}

          {messages.map((message, index) => {
            const running = streaming && index === messages.length - 1
            const since = running && message.at
              ? new Date(message.at).getTime() : null
            // Retry is offered on the last question and the last answer,
            // once the turn is over and the server has a thread to rewind.
            const retryable = !streaming && threadId !== null
              && (index === messages.length - 1 || index === lastAsked)
            return (
            <article key={index} className={`message ${message.role}`}>
              {message.role === 'user' ? (
                <>
                  <p>{message.content}</p>
                  {/* Not a <p>: every <p> in a user message is styled as
                      the bubble.  Retry here covers reopened failed turns,
                      which have no answer to hang it on. */}
                  <div className="timing">
                    <Clock at={message.at} />
                    {retryable && <Retry onRetry={retry} />}
                  </div>
                </>
              ) : (
                <>
                  <ToolTrace tools={message.tools ?? []}
                             threadId={threadId}
                             replayed={message.replayed} />
                  {message.content
                    ? <Markdown text={message.content}
                                citations={message.citations}
                                onCite={cite} />
                    : !message.error && (
                      <p className="thinking">
                        Thinking<Dots />
                        {since !== null && <Elapsed since={since} />}
                      </p>
                    )}
                  {message.error && (
                    <div className="failed">
                      <p className="error">{message.error}</p>
                      {retryable && <Retry plain onRetry={retry} />}
                    </div>
                  )}
                  <Citations citations={message.citations ?? []} onCite={cite} />
                  {/* Hidden while thinking; the elapsed counter shows instead. */}
                  {(message.content || message.error) && (
                  <p className="timing">
                    <Clock at={message.at} />
                    {message.ms !== undefined && (
                      <span className="took">{formatDuration(message.ms)}</span>
                    )}
                    {since !== null && <Elapsed since={since} />}
                    {message.usage && <Usage usage={message.usage} />}
                    {/* Copy on every answer; retry icon only when the
                        error block isn't already showing "Try again". */}
                    {message.content && <Copy text={message.content} />}
                    {retryable && !message.error && <Retry onRetry={retry} />}
                  </p>
                  )}
                </>
              )}
            </article>
            )
          })}
          <div ref={end} />
        </div>

        {/* Keep the form at a fixed DOM position so sending does not
            remount the textarea. */}
        <form className="composer"
              onSubmit={(event) => { event.preventDefault(); submit(draft) }}>
          <textarea
            value={draft}
            placeholder="Ask a rules question…"
            rows={1}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              // Enter sends; Shift+Enter inserts a newline.
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                submit(draft)
              }
            }}
          />
          {streaming
            ? <button type="button" className="stop" onClick={stop}>Stop</button>
            : <button type="submit" disabled={!draft.trim()}>Send</button>}
        </form>

        {messages.length === 0 && (
          <ul className="examples">
            {EXAMPLES.map((example) => (
              <li key={example}>
                <button onClick={() => submit(example)}>{example}</button>
              </li>
            ))}
          </ul>
        )}

        {/* Verbatim attribution required by the SRD's CC BY 4.0 licence,
            which also forbids any other attribution to Wizards of the
            Coast in the UI. */}
        <footer className="attribution">
          This work includes material from the System Reference Document
          5.2.1 (“SRD 5.2.1”) by Wizards of the Coast LLC, available at{' '}
          <a href="https://www.dndbeyond.com/srd"
             target="_blank" rel="noreferrer">https://www.dndbeyond.com/srd</a>.
          The SRD 5.2.1 is licensed under the Creative Commons Attribution
          4.0 International License, available at{' '}
          <a href="https://creativecommons.org/licenses/by/4.0/legalcode"
             target="_blank" rel="noreferrer">
            https://creativecommons.org/licenses/by/4.0/legalcode
          </a>.
        </footer>
      </main>

      {panelOpen && <Resizer width={panel} sidebar={sidebarRoom}
                             onResize={setPanel} />}
      {panelOpen && (
        <SidePanel sectionId={cited} tab={tab} onTab={setTab}
                   onClose={closePanel} onNavigate={setCited} />
      )}
      {arming && (
        <ConfirmDelete
          title={threads.find((t) => t.thread_id === arming)?.title ?? ''}
          failed={failed}
          onCancel={() => { setArming(null); setFailed(null) }}
          onDelete={() => {
            // Stays open on failure so the error is seen.
            forget(arming)
              .then(() => { setArming(null); setFailed(null) })
              .catch((problem) => setFailed(String(problem)))
          }} />
      )}
    </div>
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

function MoreIcon() {
  return (
    <svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor"
         aria-hidden="true">
      <circle cx="5" cy="12" r="1.7" />
      <circle cx="12" cy="12" r="1.7" />
      <circle cx="19" cy="12" r="1.7" />
    </svg>
  )
}

function PinIcon() {
  return (
    <svg className="pin" viewBox="0 0 24 24" width="13" height="13" fill="none"
         stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"
         strokeLinejoin="round" aria-hidden="true">
      <path d="M9 4h6l-1 5 3 3v2H7v-2l3-3z" />
      <path d="M12 14v6" />
    </svg>
  )
}

function TrashIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none"
         stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"
         strokeLinejoin="round" aria-hidden="true">
      <path d="M4 7h16M10 4h4M9 7v12M15 7v12M6 7l1 13h10l1-13" />
    </svg>
  )
}

function Citations({ citations, onCite }: {
  citations: Citation[]
  onCite: (id: string) => void
}) {
  if (citations.length === 0) return null
  return (
    <div className="citations">
      {/* Numbered to match the prose; the section id is in the title. */}
      {citations.map((citation, index) => (
        <button key={citation.section_id} className="chip"
                title={`SRD section ${citation.section_id}`}
                onClick={() => onCite(citation.section_id)}>
          <span className="chip-id">{index + 1}</span>
          {citation.heading}
        </button>
      ))}
    </div>
  )
}

/** Toolbar toggle for one panel tab. */
function PanelToggle({ tab, active, label, onClick }: {
  tab: Tab
  active: boolean
  label: string
  onClick: (tab: Tab) => void
}) {
  return (
    <button className={`panel-toggle ${active ? 'on' : ''}`}
            aria-pressed={active} title={label} aria-label={label}
            onClick={() => onClick(tab)}>
      {tab === 'page' ? <BookIcon /> : <GraphIcon />}
    </button>
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

/*
 * The logo, inlined from `logo.svg` (also the favicon) so `currentColor`
 * picks up the surrounding accent and theme; an <img> or a cross-file
 * <use> would not.  The file's own width/height (24) are for the favicon,
 * since Chrome ignores an SVG icon without an intrinsic size; `--logo-size`
 * overrides them here.
 */
function LogoIcon({ size = 22 }: { size?: number }) {
  return (
    <span className="logo" aria-hidden="true"
          style={{ '--logo-size': `${size}px` } as React.CSSProperties}
          dangerouslySetInnerHTML={{ __html: mark }} />
  )
}

function BookIcon() {
  return (
    <svg viewBox="0 0 24 24" width="17" height="17" fill="none"
         stroke="currentColor" strokeWidth="1.7" strokeLinecap="round"
         strokeLinejoin="round" aria-hidden="true">
      <path d="M4 4.5A1.5 1.5 0 0 1 5.5 3H12v18H5.5A1.5 1.5 0 0 1 4 19.5z" />
      <path d="M20 4.5A1.5 1.5 0 0 0 18.5 3H12v18h6.5a1.5 1.5 0 0 0 1.5-1.5z" />
    </svg>
  )
}

function PaneIcon() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none"
         stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round"
         aria-hidden="true">
      <rect x="3" y="4.5" width="18" height="15" rx="2" />
      <path d="M9.5 4.5v15" />
    </svg>
  )
}

function PlusIcon() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none"
         stroke="currentColor" strokeWidth="2" strokeLinecap="round"
         aria-hidden="true">
      <path d="M12 5v14M5 12h14" />
    </svg>
  )
}

function SunIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none"
         stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"
         aria-hidden="true">
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2.6v2.2M12 19.2v2.2M4.3 4.3l1.6 1.6M18.1 18.1l1.6 1.6M2.6 12h2.2M19.2 12h2.2M4.3 19.7l1.6-1.6M18.1 5.9l1.6-1.6" />
    </svg>
  )
}

function MoonIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none"
         stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"
         strokeLinejoin="round" aria-hidden="true">
      <path d="M20 14.4A8.5 8.5 0 0 1 9.6 4a8.5 8.5 0 1 0 10.4 10.4z" />
    </svg>
  )
}

function AutoIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none"
         stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <circle cx="12" cy="12" r="8.4" />
      <path d="M12 3.6a8.4 8.4 0 0 1 0 16.8z" fill="currentColor" stroke="none" />
    </svg>
  )
}

function GraphIcon() {
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
