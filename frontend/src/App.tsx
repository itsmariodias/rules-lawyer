/**
 * The application shell: conversations, the chat, and the book beside it.
 *
 * Chat is primary and always mounted; the side panel opens beside it and
 * closes without disturbing the conversation. A citation opens it on the
 * page it was printed on, but the panel is not *only* a citation viewer —
 * the toolbar opens either tab on its own, so the book and the graph are
 * reachable before an answer has cited anything.
 *
 * Which tab is showing therefore lives here rather than in the panel: the
 * toolbar picks one, and a citation forces the page.
 */

import { useEffect, useRef, useState } from 'react'
import { useChat } from './useChat'
import { useGraphStatus } from './useGraphStatus'
import { useStored, useTheme, type Theme } from './useStored'
import { clampWidth, defaultPanel, Resizer } from './components/Resizer'
import { Markdown } from './components/Markdown'
import { ToolTrace } from './components/ToolTrace'
import { Clock, Elapsed, formatDuration } from './components/Timing'
import { SidePanel, type Tab } from './components/SidePanel'
import type { Citation, Thread } from './api'
/* The mark itself, as text. See `LogoIcon`, below, for why raw. */
import mark from './logo.svg?raw'

const EXAMPLES = [
  'What exactly does the Prone condition do?',
  'How does a Rogue’s Sneak Attack scale by level?',
  'Which creatures can inflict the Frightened condition, and how?',
  'What are the components and damage of Fireball?',
]

/**
 * The ellipsis after "Thinking", animated.
 *
 * Three elements rather than an animated `content` string: browsers disagree on
 * whether `content` is animatable, and opacity on three marks is the same
 * effect everywhere.
 */
function Dots() {
  return (
    <span className="dots" aria-hidden="true">
      <i />
      <i />
      <i />
    </span>
  )
}

/**
 * Ask the last question again.
 *
 * `plain` is the failure case, where the retry is the whole way forward and
 * has to read as one; everywhere else it is the quiet icon beside a
 * timestamp, because an answer somebody is reading should not be crowded by
 * an offer to throw it away.
 */
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
 * Take the answer out of the app.
 *
 * The copy is the markdown the model wrote, citations and all: the numbers
 * on screen are this app's way of showing them, and what a reader pastes
 * into a note should still say which section of the book it came from.
 *
 * It says so afterwards, because a clipboard write is silent and otherwise
 * nothing on screen changes. The tick is a second state of the same button
 * rather than a message beside it, so nothing moves under the pointer.
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
              // It can be refused outright: a clipboard write needs a
              // secure context and the reader's permission, and saying
              // "Copied" when nothing was copied is worse than saying
              // nothing at all.
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
  // The section the panel is showing, and whether it is showing at all —
  // separate, because the panel opens with nothing cited and because
  // closing it should not forget where the reader had got to.
  const [cited, setCited] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('page')
  const [panelOpen, setPanelOpen] = useState(false)
  // Wide enough that the page is legible at Fit, and remembered, because
  // these are preferences rather than per-visit choices.
  // Which thread the delete dialog is asking about, and why the last
  // attempt did not go through.
  const [arming, setArming] = useState<string | null>(null)
  const [failed, setFailed] = useState<string | null>(null)
  // Which row's menu is open, and where to draw it. One at a time.
  const [menu, setMenu] = useState<{ id: string; x: number; y: number } | null>(null)
  const [panel, setPanel] = useStored('panel-width', defaultPanel())
  const [sidebar, setSidebar] = useStored('sidebar-width', 260)
  // Collapsed or not is a preference like the widths are, so it is
  // remembered the same way. What the rest of the layout has to know is
  // how much room the sidebar is actually taking, which is none when it is
  // shut — otherwise the panel would keep clamping around a pane that is
  // not on screen.
  const [sidebarOpen, setSidebarOpen] = useStored('sidebar-open', true)
  const sidebarRoom = sidebarOpen ? sidebar : 0
  const end = useRef<HTMLDivElement>(null)

  // A window narrowed since the widths were stored would otherwise leave no
  // room for the conversation between them.
  useEffect(() => {
    const fit = () => {
      setSidebar((current) => clampWidth('sidebar', current, panel))
      setPanel((current) => clampWidth('panel', current, sidebarRoom))
    }
    window.addEventListener('resize', fit)
    return () => window.removeEventListener('resize', fit)
  }, [panel, sidebarRoom, setPanel, setSidebar])

  useEffect(() => {
    end.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const submit = (text: string) => {
    setDraft('')
    void send(text)
  }

  // A citation names one passage, and both tabs answer a question about it
  // — what the book printed, and what it is connected to. So it re-seeds
  // whichever tab is already open and falls back to the page, which is what
  // someone clicking a rules claim out of an answer is usually after.
  const cite = (sectionId: string) => {
    setCited(sectionId)
    if (!panelOpen) setTab('page')
    setPanelOpen(true)
  }

  // The question a retry would re-ask, so both halves of that turn can offer
  // it. Everything before it stays as it is, since the rewind branches from
  // the checkpoint under this one and takes whatever follows with it.
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

  // The toolbar toggles: the tab you are already looking at closes the
  // panel, any other one switches to it.
  const toggle = (next: Tab) => {
    if (panelOpen && tab === next) setPanelOpen(false)
    else { setTab(next); setPanelOpen(true) }
  }

  return (
    <div className={`app ${panelOpen ? 'with-panel' : ''} ${sidebarOpen ? '' : 'no-sidebar'}`}
         style={{
           '--panel': `${panel}px`,
           '--sidebar': `${sidebar}px`,
         } as React.CSSProperties}>
      {sidebarOpen && (<>
      <nav className="sidebar">
        {/* The name lives here rather than only on the welcome screen,
            which disappears the moment a conversation starts. */}
        <div className="brand">
          <LogoIcon />Rules Lawyer
          <button className="collapse" title="Hide the thread list"
                  aria-label="Hide the thread list" aria-expanded={true}
                  onClick={() => setSidebarOpen(false)}>
            <PaneIcon />
          </button>
        </div>
        <button className="new" onClick={reset}><PlusIcon />New conversation</button>
        {/* Pinned conversations are a section, not a sort order. Ordering
            alone said which came first and nothing about why, so a pin
            looked like luck; a heading says what the group *is*. Pinned
            appears only when something is in it; Conversations always
            names the list, so pinning the first thread adds a section
            above rather than renaming the one already there. */}
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
        {/* Whether the graph is up, said where a caption used to name two
            technologies. A dead or unloaded database is otherwise only
            discoverable by asking a question and being told nothing came
            back. The dot carries the colour and the word carries the
            meaning, so it reads without seeing the difference between
            them, and nothing is claimed until the first answer arrives. */}
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

      <Resizer edge="sidebar" width={sidebar} other={panelOpen ? panel : 0}
               onResize={setSidebar} />
      </>)}

      {/* Collapsed, the pane keeps the width of its own controls: the one
          that brings it back, and the one thing you would have opened it
          to do. Anything else here would be a second thread list drawn as
          icons, which is what the pane itself is for. */}
      {!sidebarOpen && (
        <nav className="rail">
          {/* The mark does not leave when the pane does — it moves here and
              stands in for the toggle, turning into it only when someone
              reaches for it. Two icons, one button: the label is the
              button's throughout, so what it *is* never depends on which
              one is currently showing.

              Both are drawn at the size they are in the open pane, the
              mark at its and the toggle at its. Collapsing moves things;
              it does not resize them. */}
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
            // The one still being written is always the last, and only
            // while the stream is open.
            const running = streaming && index === messages.length - 1
            const since = running && message.at
              ? new Date(message.at).getTime() : null
            // Only the last turn can be asked again, and only once it is
            // over. A conversation the server has never seen has nothing
            // to rewind, which is a turn that failed before it began.
            // Both halves of the last turn offer it, and they do the same
            // thing: the question is what a reader reaches for when they
            // want it asked differently, the answer is what they are
            // looking at when they decide it was not good enough.
            const retryable = !streaming && threadId !== null
              && (index === messages.length - 1 || index === lastAsked)
            return (
            <article key={index} className={`message ${message.role}`}>
              {message.role === 'user' ? (
                <>
                  <p>{message.content}</p>
                  {/* A div rather than a p: every `p` in a user message is
                      drawn as the bubble itself. A turn that failed stores
                      no answer, so a failed conversation reopened from the
                      list ends on its question, and this is the only place
                      left to offer it again. */}
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
                      {/* The model is required, so a failure is the reply
                          rather than a banner over something else. The one
                          thing offered beside it is the same question again,
                          since retyping it was the only way forward. */}
                      <p className="error">{message.error}</p>
                      {retryable && <Retry plain onRetry={retry} />}
                    </div>
                  )}
                  <Citations citations={message.citations ?? []} onCite={cite} />
                  {/* Nothing to date until there is something to read: while
                      the turn is only thinking, the counter beside it is
                      already saying everything a timestamp would. */}
                  {(message.content || message.error) && (
                  <p className="timing">
                    <Clock at={message.at} />
                    {message.ms !== undefined && (
                      <span className="took">{formatDuration(message.ms)}</span>
                    )}
                    {since !== null && <Elapsed since={since} />}
                    {/* Quiet, and off to the side of what is being read:
                        taking an answer away and replacing it are both
                        things you do *after* reading it. Copy is offered on
                        every answer, since any of them is worth keeping;
                        retry only on the last, and not on a failure, where
                        the block above already says it louder. */}
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

        {/* The composer, then the examples under it. They are suggestions
            for the box rather than an introduction to it, so they follow
            it — which is also why they live out here rather than in
            `.welcome`, above. The form itself never moves in the DOM, so
            sending a message re-lays the page out without rebuilding the
            textarea under the reader's cursor. */}
        <form className="composer"
              onSubmit={(event) => { event.preventDefault(); submit(draft) }}>
          <textarea
            value={draft}
            placeholder="Ask a rules question…"
            rows={1}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              // Enter sends, Shift+Enter is a newline — the convention every
              // chat interface has trained people into.
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

        {/* The SRD is CC BY 4.0, and its licence requires this statement
            word for word in any work carrying its material. Every answer
            here quotes the book, so it belongs in the application and not
            only in the repository, and it stays on screen rather than
            behind a link nobody opens. The same licence asks that no other
            attribution to Wizards of the Coast appear anywhere, which is
            why this is the only mention of them in the UI. */}
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

      {panelOpen && <Resizer edge="panel" width={panel} other={sidebarRoom}
                             onResize={setPanel} />}
      {panelOpen && (
        <SidePanel sectionId={cited} tab={tab} onTab={setTab}
                   onClose={() => setPanelOpen(false)} onNavigate={setCited} />
      )}
      {arming && (
        <ConfirmDelete
          title={threads.find((t) => t.thread_id === arming)?.title ?? ''}
          failed={failed}
          onCancel={() => { setArming(null); setFailed(null) }}
          onDelete={() => {
            // Dismissed only once it is actually gone: a delete that failed
            // silently leaves the reader believing a conversation was
            // deleted that is still there.
            forget(arming)
              .then(() => { setArming(null); setFailed(null) })
              .catch((problem) => setFailed(String(problem)))
          }} />
      )}
    </div>
  )
}

/**
 * One conversation in the list, and the things you can do to it.
 *
 * The menu button is hidden until the row is hovered or something in it is
 * focused — and while its own menu is open, or it would vanish under the
 * menu it opened. Reading a conversation is what you do to one of these a
 * hundred times more often than pinning or deleting it, and a column of
 * controls reads like a list of things to act on rather than a list of
 * conversations.
 */
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
                // The menu is placed from the button rather than nested in
                // the row: the list scrolls, and anything drawn inside it
                // is clipped at its edges.
                const box = event.currentTarget.getBoundingClientRect()
                onMenu({ x: box.right, y: box.bottom + 4 })
              }}>
        <MoreIcon />
      </button>
    </li>
  )
}

/**
 * Asking before deleting a conversation.
 *
 * A native `<dialog>` rather than a div: `showModal` puts it in the top
 * layer, so no stacking context can bury it, and brings the focus trap, the
 * inert background, the Escape key and the backdrop with it. All of that is
 * a lot to hand-roll badly.
 *
 * **Cancel** takes the focus, not **Delete**. There is no undo — the
 * checkpointer is the whole store — so the key someone presses without
 * reading must be the one that changes nothing. Escape and the backdrop
 * agree with it.
 */
function ConfirmDelete({ title, failed, onCancel, onDelete }: {
  title: string
  /** Why the last attempt did not delete it, if one has been made. */
  failed: string | null
  onCancel: () => void
  onDelete: () => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)

  useEffect(() => { dialog.current?.showModal() }, [])

  return (
    <dialog className="modal" ref={dialog}
            aria-labelledby="confirm-delete-title"
            // Escape fires `cancel`; letting it close the dialog on its own
            // would leave this component mounted and believing otherwise.
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
 * The menu those buttons open.
 *
 * Fixed rather than absolute, and positioned from the button that opened
 * it, because the thread list scrolls and clips: a menu nested in a row
 * would be cut off by the pane it lives in. That is also why scrolling
 * closes it — the anchor it was measured against has moved.
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
    // Deferred a tick: the click that opened it is still on its way up, and
    // would otherwise close it again immediately.
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
      {/*
        * The legend for the numbers in the prose, so it is ordered by them
        * and labelled by them. The section id is not on it: it is how the
        * app finds the passage, not something a reader knows or wants, and
        * it is still one hover away.
        */}
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

/**
 * One toolbar button per panel tab.
 *
 * It is a toggle rather than an opener, and says so: `aria-pressed` is what
 * a screen reader reads off it, and the same state draws the button as on.
 */
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

/*
 * Light, dark, or whatever the machine is set to.
 *
 * Three buttons rather than one that cycles: with three states, a single
 * button cannot say what pressing it will do, and the one people reach for
 * most is the one they are already on — going back to it would mean
 * pressing through the other two. `system` is offered as its own choice
 * because it is not a third look, it is the absence of an override.
 */
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

/* Drawn rather than imported: eight icons is still not a dependency. The
   book is the panel's Page tab; the mark is that book with the graph
   behind it. */

/*
 * The app's mark: the book as the hub of its own graph, drawn in
 * `logo.svg`, which is the only copy of it.
 *
 * The book is *open* where the panel's Page tab is closed, so the two
 * never read as the same drawing. Six nodes sit at the corners of a
 * hexagon and the edges run between them, so the graph is the frame and
 * the book is what it holds — a closed ring rather than spikes, which said
 * the same thing but pointed away from the subject.
 *
 * The hexagon is pointy-top, and that is the whole reason the book is the
 * size it is. What binds is not the frame's width but its four slanted
 * sides: the book's top corners run into them long before its flanks come
 * near the two upright ones. Pointy-top leaves those corners the most room
 * of the two orientations, so the book inside is larger than a flat-top
 * ring of the same width would allow. It is drawn to leave about a stroke
 * of daylight at the corners — nearer than that and the two merge at the
 * size the favicon is read at.
 *
 * The book is two curved leaves either side of a drawn spine, rather than
 * two rectangles with a notch between them. The notch version has to put
 * the spine's foot below the pages, and at this size that hangs off the
 * bottom as a nub; squaring the pages off instead loses the book and
 * leaves a window. Curving both edges gives the V at the top something to
 * answer at the bottom, and it is the pair that reads as open.
 *
 * The nodes are hollow on hairlines rather than discs on full-weight
 * strokes, which is what keeps the frame behind the book rather than
 * competing with it.
 *
 * `?raw` is Vite's, not a plugin: the file arrives as a string and is
 * inlined, which is what keeps `currentColor` working — the mark takes the
 * accent from the sidebar or the heading it sits in, including a theme the
 * reader has overridden. An `<img>` would not: it loads the file as its own
 * document, which the app's colours never reach. Nor would
 * `<use href="logo.svg#…">`, which no browser resolves across files any
 * more. That is also why the file names a colour at all — as the favicon it
 * is loaded exactly that way, with no page to take one from.
 *
 * `size` is the only thing that varies — the wordmark wants it at text
 * height, the welcome screen at heading height — so `.logo` hands one down
 * in a custom property. The file states 24 of its own, which the rule
 * beats: that pair is there for the favicon, since an SVG with only a
 * viewBox has no intrinsic size and Chrome will not take it as an icon.
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

/* A pane hinged on the left edge: the same mark whichever way it is
   about to go, since it is one control with two states. */
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

/* Half the dial filled: the theme is being taken from somewhere else. */
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
