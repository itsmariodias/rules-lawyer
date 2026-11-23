import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { ExportChat } from './ExportChat'

describe('ExportChat', () => {
  it('given an open thread, when rendered, then Export opens the menu of formats', () => {
    // Given an open conversation
    // When the header is drawn
    render(<ExportChat threadId="t1" disabled={false} />)

    // Then the button toggles the popover holding the formats; the browser
    // opens and closes it, which jsdom does not implement
    const menu = screen.getByRole('menu', { hidden: true })
    expect(menu).toHaveAttribute('popover', 'auto')
    expect(screen.getByRole('button', { name: 'Export chat' }))
      .toHaveAttribute('popovertarget', menu.id)
  })

  it('given the menu, when read, then markdown, Word and PDF each download this thread', () => {
    // Given an open conversation
    render(<ExportChat threadId="t1" disabled={false} />)

    // When its menu is read
    const links = screen.getAllByRole('menuitem', { hidden: true })

    // Then each format is a download of this thread
    expect(links.map((link) => link.textContent))
      .toEqual(['Markdown (.md)', 'Word (.docx)', 'PDF (.pdf)'])
    expect(links.map((link) => link.getAttribute('href'))).toEqual([
      '/api/chat/threads/t1/export?format=markdown',
      '/api/chat/threads/t1/export?format=docx',
      '/api/chat/threads/t1/export?format=pdf',
    ])
    expect(links.every((link) => link.hasAttribute('download'))).toBe(true)
  })

  it('given the menu, when a format is chosen, then the menu closes', () => {
    // Given the export menu
    render(<ExportChat threadId="t1" disabled={false} />)
    const menu = screen.getByRole('menu', { hidden: true })
    const hidePopover = vi.fn()
    menu.hidePopover = hidePopover

    // When a format is chosen
    fireEvent.click(screen.getByRole('menuitem', { name: 'PDF (.pdf)', hidden: true }))

    // Then the menu gets out of the way of the download
    expect(hidePopover).toHaveBeenCalled()
  })

  it('given a turn streaming, when rendered, then export waits for it', () => {
    // Given a conversation whose answer is still arriving
    // When the header is drawn
    render(<ExportChat threadId="t1" disabled />)

    // Then nothing half-written can be exported
    expect(screen.getByRole('button', { name: 'Export chat' })).toBeDisabled()
  })
})
