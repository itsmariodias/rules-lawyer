import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { SourceExcerpt } from '../../api'
import { SectionTree } from './SectionTree'

const excerpt = (overrides: Partial<SourceExcerpt> = {}): SourceExcerpt => ({
  section_id: '11.2.114', heading: 'Prone [Condition]',
  entity_type: 'glossary_term', page: 186, text: 'While you have…',
  highlight: null, boxes: [], pages: [186],
  ancestors: [{ id: '11', heading: 'Rules Glossary' },
              { id: '11.2', heading: 'Rules Definitions' }],
  parent: { id: '11.2', heading: 'Rules Definitions' },
  children: [{ id: '11.2.114.1', heading: 'Standing Up' }],
  ...overrides,
})

const roots = [{ id: '1', heading: 'Legal Information' },
               { id: '2', heading: 'Playing the Game' }]

function tree(props: Partial<Parameters<typeof SectionTree>[0]> = {}) {
  const merged = {
    sectionId: '11.2.114' as string | null, excerpt: excerpt() as SourceExcerpt | null,
    roots, loading: false, error: null as string | null, onNavigate: vi.fn(),
    ...props,
  }
  return { ...render(<SectionTree {...merged} />), props: merged }
}

const nav = () => screen.getByRole('navigation', { name: 'Location in the book' })
const crumbs = () => within(nav()).getAllByRole('list')[0]
const current = () => within(nav()).getByText(
  (_, element) => element?.getAttribute('aria-current') === 'location')

describe('SectionTree', () => {
  it('given a nested section, when drawn, then its path runs from the book down to it', () => {
    // Given a section two levels below a top-level section
    tree()

    // When the breadcrumb is read
    const path = within(crumbs()).getAllByRole('listitem')
      .map((crumb) => crumb.textContent)

    // Then it reads like a path, ending on the section (and the count of
    // its subsections), which is marked
    expect(path).toEqual(['SRD', 'Rules Glossary', 'Rules Definitions',
                          'Prone [Condition]1'])
    expect(current()).toHaveTextContent('Prone [Condition]')
    expect(current()).toHaveAttribute('title', '11.2.114')
    expect(within(nav()).getByText('glossary term')).toBeInTheDocument()
  })

  it('given an ancestor, when pressed, then the panel navigates to it', async () => {
    // Given a nested section
    const { props } = tree()

    // When the top-level section is pressed
    await userEvent.click(screen.getByRole('button', { name: 'Rules Glossary' }))

    // Then it is asked for by id
    expect(props.onNavigate).toHaveBeenCalledWith('11')
  })

  it('given a section open, when the book is pressed, then the citation is cleared', async () => {
    // Given a section open
    const { props } = tree()

    // When the first crumb is pressed
    await userEvent.click(screen.getByRole('button', { name: 'SRD' }))

    // Then the panel is asked for the whole book
    expect(props.onNavigate).toHaveBeenCalledWith(null)
  })

  it('given subsections, when the dropdown is opened, then they are offered in book order', async () => {
    // Given a section with two subsections
    tree({ excerpt: excerpt({ children: [
      { id: '11.2.114.1', heading: 'Standing Up' },
      { id: '11.2.114.2', heading: 'Crawling' }] }) })

    // When the dropdown after the section is opened
    const opener = screen.getByRole('button', { name: 'Subsections (2)' })
    await userEvent.click(opener)

    // Then they are listed as menu entries, the first one focused
    const menu = screen.getByRole('menu', { name: 'Subsections' })
    const entries = within(menu).getAllByRole('menuitem')
    expect(entries.map((entry) => entry.textContent)).toEqual(['Standing Up', 'Crawling'])
    expect(entries[0]).toHaveFocus()
    expect(opener).toHaveAttribute('aria-expanded', 'true')
  })

  it('given the dropdown open, when a subsection is chosen, then the panel navigates to it', async () => {
    // Given the subsections offered
    const { props } = tree()
    await userEvent.click(screen.getByRole('button', { name: 'Subsections (1)' }))

    // When one is chosen
    await userEvent.click(screen.getByRole('menuitem', { name: 'Standing Up' }))

    // Then it becomes the open section and the menu closes
    expect(props.onNavigate).toHaveBeenCalledWith('11.2.114.1')
    expect(screen.queryByRole('menu')).toBeNull()
  })

  it('given the dropdown open, when Escape is pressed, then it closes and focus returns', async () => {
    // Given the subsections offered
    tree()
    const opener = screen.getByRole('button', { name: 'Subsections (1)' })
    await userEvent.click(opener)

    // When Escape is pressed
    await userEvent.keyboard('{Escape}')

    // Then the menu is gone and the keyboard is back where it was
    expect(screen.queryByRole('menu')).toBeNull()
    expect(opener).toHaveFocus()
  })

  it('given the dropdown open, when the reader presses elsewhere, then it closes', async () => {
    // Given the subsections offered
    tree()
    await userEvent.click(screen.getByRole('button', { name: 'Subsections (1)' }))

    // When something outside it is pressed
    await userEvent.click(document.body)

    // Then the menu is gone
    expect(screen.queryByRole('menu')).toBeNull()
  })

  it('given the dropdown open, when its button is pressed again, then it closes', async () => {
    // Given the subsections offered
    tree()
    const opener = screen.getByRole('button', { name: 'Subsections (1)' })
    await userEvent.click(opener)

    // When the same button is pressed
    await userEvent.click(opener)

    // Then the press toggles it shut rather than reopening it
    expect(screen.queryByRole('menu')).toBeNull()
    expect(opener).toHaveAttribute('aria-expanded', 'false')
  })

  it('given no subsections, when drawn, then there is no dropdown', () => {
    // Given a leaf section
    tree({ excerpt: excerpt({ children: [] }) })

    // When the bar is read
    // Then only the path is shown
    expect(screen.queryByRole('button', { name: /Subsections/ })).toBeNull()
  })

  it('given nothing open, when drawn, then the book is current and its sections are a dropdown', async () => {
    // Given no section open
    tree({ sectionId: null, excerpt: null })

    // When the dropdown after the book is opened
    await userEvent.click(screen.getByRole('button', { name: 'Sections (2)' }))

    // Then the book is where the reader is, with its sections offered
    expect(current()).toHaveTextContent('SRD')
    expect(within(nav()).queryByRole('button', { name: 'SRD' })).toBeNull()
    expect(screen.getAllByRole('menuitem').map((entry) => entry.textContent))
      .toEqual(['Legal Information', 'Playing the Game'])
  })

  it('given a section loading, when drawn, then the tree says so', () => {
    // Given a citation whose source has not arrived
    tree({ excerpt: null, loading: true })

    // When the tree is read
    // Then it says it is loading, and the book is still a way out
    expect(within(nav()).getByText('Loading…')).toBeInTheDocument()
    expect(within(nav()).getByRole('button', { name: 'SRD' })).toBeInTheDocument()
  })

  it('given a section that failed, when drawn, then the reason is shown', () => {
    // Given a source that could not be loaded
    tree({ excerpt: null, error: 'Error: 503 unavailable' })

    // When the tree is read
    // Then the failure is in the tree
    expect(within(nav()).getByText('Error: 503 unavailable')).toBeInTheDocument()
  })
})
