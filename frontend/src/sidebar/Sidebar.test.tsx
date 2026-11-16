/** `useGraphStatus` is mocked; it has its own tests. */

import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { Thread } from '../api'
import { Sidebar } from './Sidebar'

vi.mock('./useGraphStatus', () => ({ useGraphStatus: () => 'connected' }))

const thread = (overrides: Partial<Thread> = {}): Thread => ({
  thread_id: 't1', title: 'Prone condition', updated_at: '2026-01-01',
  messages: 2, pinned: false, ...overrides,
})

function sidebar(props: Partial<Parameters<typeof Sidebar>[0]> = {}) {
  const merged = {
    threads: [thread()], activeId: null, expanded: true,
    onExpand: vi.fn(), onOpen: vi.fn(), onNew: vi.fn(), onPin: vi.fn(),
    onForget: vi.fn((_id: string) => Promise.resolve()), ...props,
  }
  return { ...render(<Sidebar {...merged} />), props: merged }
}

const openMenu = () => userEvent.click(screen.getByRole(
  'button', { name: 'Options for conversation: Prone condition' }))

beforeEach(() => {
  // jsdom lacks showModal/close; without `open`, dialog contents are not
  // in the accessibility tree.
  HTMLDialogElement.prototype.showModal = vi.fn(function (
      this: HTMLDialogElement) { this.open = true })
  HTMLDialogElement.prototype.close = vi.fn(function (
      this: HTMLDialogElement) { this.open = false })
})

describe('the thread list', () => {
  it('given conversations, when listed, then each is a row that opens it', async () => {
    // Given one stored conversation
    const { props } = sidebar()

    // When its row is pressed
    await userEvent.click(screen.getByRole('button', { name: 'Prone condition' }))

    // Then it is opened
    expect(props.onOpen).toHaveBeenCalledWith('t1')
  })

  it('given the conversation on screen, when listed, then its row is marked', () => {
    // Given two conversations, one of them open
    // When the list is rendered
    sidebar({ threads: [thread(), thread({ thread_id: 't2', title: 'Grappled' })],
              activeId: 't2' })

    // Then only the open one's row is highlighted
    const row = (title: string) =>
      screen.getByRole('button', { name: title }).closest('li')
    expect(row('Grappled')).toHaveClass('on')
    expect(row('Prone condition')).not.toHaveClass('on')
  })

  it('given a pinned conversation, when listed, then it has a section of its own', () => {
    // Given one pinned conversation and one not
    // When the list is rendered
    sidebar({ threads: [thread({ thread_id: 'p', title: 'Kept', pinned: true }),
                        thread()] })

    // Then both groups are named
    expect(screen.getByRole('heading', { name: 'Pinned' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Conversations' }))
      .toBeInTheDocument()
  })

  it('given nothing pinned, when listed, then there is no empty Pinned section', () => {
    // Given only unpinned conversations
    // When the list is rendered
    sidebar()

    // Then the section appears only when something is in it
    expect(screen.queryByRole('heading', { name: 'Pinned' })).toBeNull()
  })

  it('given a row, when its menu is opened, then pin and delete are offered', async () => {
    // Given a conversation
    sidebar()

    // When its menu is opened
    await openMenu()

    // Then the two things you can do to it are there
    const menu = screen.getByRole('menu')
    expect(within(menu).getByRole('menuitem', { name: /Pin/ }))
      .toBeInTheDocument()
    expect(within(menu).getByRole('menuitem', { name: /Delete/ }))
      .toBeInTheDocument()
  })

  it('given the menu, when pin is chosen, then the conversation is pinned', async () => {
    // Given an unpinned conversation's menu
    const { props } = sidebar()
    await openMenu()

    // When pin is chosen
    await userEvent.click(screen.getByRole('menuitem', { name: /Pin/ }))

    // Then the shell is told, and the menu closes
    expect(props.onPin).toHaveBeenCalledWith('t1', true)
    expect(screen.queryByRole('menu')).toBeNull()
  })

  it('given a pinned conversation, when its menu is opened, then it offers to unpin', async () => {
    // Given a pinned conversation
    sidebar({ threads: [thread({ pinned: true })] })

    // When its menu is opened
    await openMenu()

    // Then the action offered is the one that changes something
    expect(screen.getByRole('menuitem', { name: /Unpin/ })).toBeInTheDocument()
  })

  it('given an open menu, when Escape is pressed, then it closes', async () => {
    // Given an open menu
    sidebar()
    await openMenu()

    // When Escape is pressed
    await userEvent.keyboard('{Escape}')

    // Then it is dismissed
    expect(screen.queryByRole('menu')).toBeNull()
  })

  it('given an open menu, when the pointer goes down elsewhere, then it closes', async () => {
    // Given an open menu
    sidebar()
    await openMenu()

    // When the reader presses somewhere else, once the opening click is past
    await new Promise((resolve) => setTimeout(resolve, 0))
    fireEvent.pointerDown(document.body)

    // Then it is dismissed
    expect(screen.queryByRole('menu')).toBeNull()
  })

  it('given an open menu, when its button is pressed again, then it closes', async () => {
    // Given an open menu, its row marked so the button stays shown
    sidebar()
    await openMenu()
    expect(screen.getByRole('button', { name: 'Prone condition' }).closest('li'))
      .toHaveClass('menu-open')

    // When the same button is pressed again
    await openMenu()

    // Then it toggles shut
    expect(screen.queryByRole('menu')).toBeNull()
  })

  it('given an open menu, when another key is pressed, then it stays', async () => {
    // Given an open menu
    sidebar()
    await openMenu()

    // When a key other than Escape is pressed
    await userEvent.keyboard('a')

    // Then the menu is still there
    expect(screen.getByRole('menu')).toBeInTheDocument()
  })

  it('given an open menu, when its thread leaves the list, then it still offers to pin', async () => {
    // Given an open menu
    const { props, rerender } = sidebar()
    await openMenu()

    // When a refreshed list no longer holds the thread
    rerender(<Sidebar {...props} threads={[]} />)

    // Then the menu reads it as unpinned rather than breaking
    expect(screen.getByRole('menuitem', { name: /^Pin/ })).toBeInTheDocument()
  })

  it('given the list, when it is collapsed, then the shell is told', async () => {
    // Given the full list
    const { props } = sidebar()

    // When it is hidden
    await userEvent.click(screen.getByRole('button', { name: 'Hide the thread list' }))

    // Then the shell, which owns the layout, is asked to collapse it
    expect(props.onExpand).toHaveBeenCalledWith(false)
  })
})

describe('deleting a conversation', () => {
  async function armDelete(props: Partial<Parameters<typeof Sidebar>[0]> = {}) {
    const rendered = sidebar(props)
    await openMenu()
    await userEvent.click(screen.getByRole('menuitem', { name: /Delete/ }))
    return rendered
  }

  it('given delete is chosen, when the dialog opens, then it asks first', async () => {
    // Given a conversation
    // When delete is chosen
    const { props } = await armDelete()

    // Then nothing is deleted yet, and the conversation is named
    expect(props.onForget).not.toHaveBeenCalled()
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByRole(
      'heading', { name: 'Delete this conversation?' })).toBeInTheDocument()
    expect(within(dialog).getByText('Prone condition')).toBeInTheDocument()
  })

  it('given the dialog, when it opens, then Cancel has the focus', async () => {
    // Given the dialog
    await armDelete()

    // When the focus is read
    // Then it is on the button that does nothing
    expect(screen.getByRole('button', { name: 'Cancel' })).toHaveFocus()
  })

  it('given the dialog, when Delete is pressed, then the conversation goes', async () => {
    // Given the dialog
    const { props } = await armDelete()

    // When delete is confirmed
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }))

    // Then it is deleted and the dialog closes
    expect(props.onForget).toHaveBeenCalledWith('t1')
    await waitFor(() => expect(screen.queryByRole('heading',
      { name: 'Delete this conversation?' })).toBeNull())
  })

  it('given the dialog, when Cancel is pressed, then nothing is deleted', async () => {
    // Given the dialog
    const { props } = await armDelete()

    // When it is cancelled
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))

    // Then the conversation is untouched and the dialog is gone
    expect(props.onForget).not.toHaveBeenCalled()
    expect(screen.queryByRole('heading',
                              { name: 'Delete this conversation?' })).toBeNull()
  })

  it('given the dialog, when Escape is pressed, then nothing is deleted', async () => {
    // Given the dialog
    const { props } = await armDelete()

    // When the browser cancels it, as Escape does
    fireEvent(screen.getByRole('dialog'), new Event('cancel', { cancelable: true }))

    // Then it closes through the same path as Cancel
    expect(props.onForget).not.toHaveBeenCalled()
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('given the dialog, when the backdrop is clicked, then nothing is deleted', async () => {
    // Given the dialog
    const { props } = await armDelete()

    // When the click lands on the dialog itself, which only the backdrop
    // can be, since its contents sit in an inner element
    fireEvent.click(screen.getByRole('dialog'))

    // Then it is dismissed
    expect(props.onForget).not.toHaveBeenCalled()
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('given the dialog, when its contents are clicked, then it stays', async () => {
    // Given the dialog
    await armDelete()

    // When the heading inside it is clicked
    fireEvent.click(screen.getByRole('heading', { name: 'Delete this conversation?' }))

    // Then it is still asking
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('given a delete that fails, when confirmed, then the dialog stays open', async () => {
    // Given a server that refuses the delete
    await armDelete({ onForget: vi.fn(async () => { throw new Error('503') }) })

    // When delete is confirmed
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }))

    // Then the failure is shown, in the dialog that is still up
    expect(await screen.findByText(/503/)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Delete this conversation?' }))
      .toBeInTheDocument()
  })

  it('given an open dialog, when its thread leaves the list, then it still asks', async () => {
    // Given the dialog
    const { props, rerender } = await armDelete()

    // When a refreshed list no longer holds the thread
    rerender(<Sidebar {...props} threads={[]} />)

    // Then it still asks, untitled, rather than vanishing mid-decision
    expect(screen.getByRole('heading', { name: 'Delete this conversation?' }))
      .toBeInTheDocument()
  })
})

describe('the footer', () => {
  it('given the theme switch, when Dark is chosen, then the page goes dark and it is shown as chosen', async () => {
    // Given the sidebar on the system theme
    sidebar()

    // When Dark is chosen
    await userEvent.click(screen.getByRole('button', { name: 'Dark' }))

    // Then the document carries the theme, and the switch says which is on
    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(screen.getByRole('button', { name: 'Dark' }))
      .toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Match the system' }))
      .toHaveAttribute('aria-pressed', 'false')
    delete document.documentElement.dataset.theme
  })

  it('given a graph status, when shown, then it is said in words', () => {
    // Given a connected graph
    // When the footer is read
    sidebar()

    // Then the word carries the meaning, not only the dot's colour
    expect(screen.getByText('graph connected')).toBeInTheDocument()
  })
})

describe('the rail', () => {
  it('given a collapsed list, when rendered, then only expand and new remain', async () => {
    // Given the list collapsed
    const { props } = sidebar({ expanded: false })

    // When expand is pressed
    await userEvent.click(screen.getByRole('button', { name: 'Show the thread list' }))

    // Then no rows are drawn, a conversation can still be started, and the
    // shell is asked to expand
    expect(screen.queryByRole('button', { name: 'Prone condition' })).toBeNull()
    expect(screen.getByRole('button', { name: 'New conversation' }))
      .toBeInTheDocument()
    expect(props.onExpand).toHaveBeenCalledWith(true)
  })
})
