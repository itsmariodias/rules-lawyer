/**
 * The assistant's answer, with its citations made clickable.
 *
 * The model writes citations as bare `[11.2.114]`, which is not markdown.
 * The rewrite into links before parsing is what makes a citation inside a
 * table cell or a list item work like any other, so that is what is tested.
 */

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { Markdown } from './Markdown'

describe('Markdown', () => {
  it('given a citation, when rendered, then it is a button carrying its id', () => {
    // Given an answer citing a section
    render(<Markdown text="A Prone creature has Disadvantage [11.2.114]."
                     onCite={() => {}} />)

    // When the citation is found
    const cite = screen.getByRole('button', { name: '11.2.114' })

    // Then it is pressable and says what it opens
    expect(cite).toHaveAttribute('title', 'Open SRD section 11.2.114')
  })

  it('given a citation, when pressed, then the section is opened', async () => {
    // Given a rendered answer
    const onCite = vi.fn()
    render(<Markdown text="Disadvantage [11.2.114]." onCite={onCite} />)

    // When the citation is pressed
    await userEvent.click(screen.getByRole('button', { name: '11.2.114' }))

    // Then the panel is told which section to open
    expect(onCite).toHaveBeenCalledWith('11.2.114')
  })

  it('given a citation inside a table, when rendered, then it is still a button', () => {
    /** Which is why it is a rewrite rather than a custom text renderer. */
    // Given an answer citing from inside a table cell
    const table = ['| Condition | Effect |', '|---|---|',
                   '| Prone [11.2.114] | Disadvantage |'].join('\n')

    // When it is rendered
    render(<Markdown text={table} onCite={() => {}} />)

    // Then the citation works there as anywhere else
    expect(screen.getByRole('button', { name: '11.2.114' })).toBeInTheDocument()
  })

  it('given a citation in a list item, when rendered, then it is still a button', () => {
    // Given an answer citing from inside a list
    render(<Markdown text={'- Prone [11.2.114]\n- Restrained [11.2.120]'}
                     onCite={() => {}} />)

    // When the citations are found
    // Then both are pressable
    expect(screen.getByRole('button', { name: '11.2.114' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '11.2.120' })).toBeInTheDocument()
  })

  it('given ordinary brackets, when rendered, then they are not citations', () => {
    /** Anchored on the digits, so prose brackets never become links. */
    // Given prose carrying brackets that are not ids
    render(<Markdown text="See [below] and step [3]." onCite={() => {}} />)

    // When buttons are looked for
    // Then there are none, and the words survive
    expect(screen.queryByRole('button')).toBeNull()
    expect(screen.getByText(/See \[below\] and step \[3\]/)).toBeInTheDocument()
  })

  it('given an ordinary link, when rendered, then it opens away from the app', () => {
    // Given an answer carrying a real link
    render(<Markdown text="[the SRD](https://example.com)" onCite={() => {}} />)

    // When the link is found
    const link = screen.getByRole('link', { name: 'the SRD' })

    // Then it leaves the conversation intact behind it
    expect(link).toHaveAttribute('href', 'https://example.com')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noreferrer')
  })

  it('given markdown, when rendered, then it is formatted rather than shown raw', () => {
    // Given an answer using markdown
    render(<Markdown text={'## Prone\n\n**Disadvantage** on attack rolls.'}
                     onCite={() => {}} />)

    // When it is rendered
    // Then the structure is markup, not characters on the page
    expect(screen.getByRole('heading', { name: 'Prone' })).toBeInTheDocument()
    expect(screen.getByText('Disadvantage').tagName).toBe('STRONG')
  })
})
