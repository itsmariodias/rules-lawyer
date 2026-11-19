/**
 * The app shell: thread list, conversation, and side panel.  The panel's
 * tab is held here because both the toolbar and citations set it.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { useChat } from './chat/useChat'
import { useStored } from './shared/useStored'
import { clampWidth, defaultPanel, Resizer, SIDEBAR } from './panel/Resizer'
import { ChatMessage } from './chat/ChatMessage'
import { BookIcon, GraphIcon, LogoIcon } from './shared/icons'
import { SidePanel, type Tab } from './panel/SidePanel'
import { Sidebar } from './sidebar/Sidebar'

const EXAMPLES = [
  'What exactly does the Prone condition do?',
  'How does a Rogue’s Sneak Attack scale by level?',
  'Which creatures can inflict the Frightened condition, and how?',
  'What are the components and damage of Fireball?',
]

export default function App() {
  const { messages, threads, threadId, streaming, send, retry,
          stop, open, reset, forget, pin, arriving } = useChat()
  const [draft, setDraft] = useState('')
  // A new chat, not a thread whose turns are still on their way.
  const blank = messages.length === 0 && !arriving
  // Separate from `panelOpen`: the panel can open with nothing cited.
  // Closing it clears the citation, so the toolbar reopens the whole book.
  const [cited, setCited] = useState<string | null>(null)
  // Bumped on every citation, so citing the open section again scrolls to it.
  const [visit, setVisit] = useState(0)
  const [tab, setTab] = useState<Tab>('page')
  const [panelOpen, setPanelOpen] = useState(false)
  const [panel, setPanel] = useStored('panel-width', defaultPanel())
  // Width the panel clamp should reserve; 0 when the sidebar is hidden.
  const [sidebarOpen, setSidebarOpen] = useStored('sidebar-open', true)
  const sidebarRoom = sidebarOpen ? SIDEBAR : 0
  const end = useRef<HTMLDivElement>(null)

  // Re-clamp on load as well as resize: a width stored on a large display
  // would otherwise squeeze the conversation on a laptop.
  useEffect(() => {
    const fit = () => setPanel((width) => clampWidth(width, sidebarRoom))
    fit()
    window.addEventListener('resize', fit)
    return () => window.removeEventListener('resize', fit)
  }, [sidebarRoom, setPanel])

  useEffect(() => {
    end.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const submit = (text: string) => {
    setDraft('')
    void send(text)
  }

  const navigate = useCallback((sectionId: string | null) => {
    setCited(sectionId)
    setVisit((count) => count + 1)
  }, [])

  // Re-seed the open tab; open on Page if the panel was closed.  Stable, so
  // a streamed token does not redraw every memoised answer.
  const cite = useCallback((sectionId: string) => {
    navigate(sectionId)
    if (!panelOpen) setTab('page')
    setPanelOpen(true)
  }, [panelOpen, navigate])

  const lastAsked = messages.map((message) => message.role).lastIndexOf('user')

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
      <Sidebar threads={threads} activeId={threadId}
               expanded={sidebarOpen} onExpand={setSidebarOpen}
               onOpen={(id) => void open(id)} onNew={reset}
               onPin={(id, pinned) => void pin(id, pinned)}
               onForget={forget} />

      <main className={`chat ${blank ? 'empty' : ''}`}>
        <header className="chat-head">
          <PanelToggle tab="page" active={panelOpen && tab === 'page'}
                       label="Book page" onClick={toggle} />
          <PanelToggle tab="graph" active={panelOpen && tab === 'graph'}
                       label="Graph" onClick={toggle} />
        </header>

        <div className="messages">
          {blank && (
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
            // Retry is offered on the last question and the last answer,
            // once the turn is over and the server has a thread to rewind.
            const retryable = !streaming && threadId !== null
              && (index === messages.length - 1 || index === lastAsked)
            return (
              <ChatMessage key={index} message={message}
                           running={streaming && index === messages.length - 1}
                           threadId={threadId}
                           onRetry={retryable ? retry : undefined}
                           onCite={cite} />
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

        {blank && (
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
        <SidePanel sectionId={cited} visit={visit} tab={tab} onTab={setTab}
                   onClose={closePanel} onNavigate={navigate} />
      )}
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
