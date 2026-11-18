import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { Citation } from '../api'
import { Markdown, numbering } from './Markdown'

const cited = (...ids: string[]): Citation[] =>
  ids.map((section_id) => ({
    section_id, heading: `Section ${section_id}`, entity_type: 'rule',
    page: 1, labels: [],
  }))

describe('numbering', () => {
  it('given resolved citations, when numbered, then they set the order', () => {
    // Given an answer and the citations resolved from it
    const order = numbering('a [11.2.114] b [7.1.44]',
                            cited('11.2.114', '7.1.44'))

    // When the numbers are read
    // Then they run in the order the list gives
    expect([...order]).toEqual([['11.2.114', 1], ['7.1.44', 2]])
  })

  it('given ids sharing a bracket mid-stream, when numbered, then each gets a number', () => {
    // Given an answer mid-stream citing two sections in one bracket
    const order = numbering('servants [9.7.6, 9.7.7] and staff [9.7.7]')

    // When the numbers are read
    // Then the bracket counts as two citations, in the order written
    expect([...order]).toEqual([['9.7.6', 1], ['9.7.7', 2]])
  })

  it('given no citations yet, when numbered, then the text decides', () => {
    // Given an answer mid-stream, citing one section twice
    const order = numbering('a [11.2.114] b [7.1.44] c [11.2.114]')

    // When the numbers are read
    // Then each distinct section has one, by first appearance
    expect([...order]).toEqual([['11.2.114', 1], ['7.1.44', 2]])
  })
})

describe('Markdown', () => {
  it('given a citation, when rendered, then it is numbered rather than dotted', () => {
    // Given an answer citing a section
    render(<Markdown text="A Prone creature has Disadvantage [11.2.114]."
                     citations={cited('11.2.114')} onCite={() => {}} />)

    // When the citation is found
    const cite = screen.getByRole('button', { name: '1' })

    // Then the id it opens is one hover away, with what it names
    expect(cite).toHaveAttribute('title', 'Section 11.2.114 (11.2.114)')
  })

  it('given one section cited repeatedly, when rendered, then it keeps one number', () => {
    // Given an answer leaning on the same section three times
    render(<Markdown text="One [11.2.114] two [11.2.114] three [11.2.114]."
                     citations={cited('11.2.114')} onCite={() => {}} />)

    // When the citations are counted
    // Then they are all the same number rather than three of the same id
    expect(screen.getAllByRole('button', { name: '1' })).toHaveLength(3)
  })

  it('given a citation, when pressed, then the section is opened', () => {
    // Given a rendered answer
    const onCite = vi.fn()
    render(<Markdown text="Disadvantage [11.2.114]."
                     citations={cited('11.2.114')} onCite={onCite} />)

    // When the citation is pressed
    return userEvent.click(screen.getByRole('button', { name: '1' }))
      .then(() => {
        // Then the panel is told which section to open
        expect(onCite).toHaveBeenCalledWith('11.2.114')
      })
  })

  it('given an id that resolved to nothing, when rendered, then it is not a link', () => {
    /**
     * Regression: an unresolved id used to render as a link that opened
     * nothing.
     */
    // Given an answer citing one real section and one invented id
    render(<Markdown text="Real [11.2.114], invented [99.99.99]."
                     citations={cited('11.2.114')} onCite={() => {}} />)

    // When the buttons are counted
    // Then only the resolved one is pressable, and the other is left as
    // written rather than silently deleted
    expect(screen.getAllByRole('button')).toHaveLength(1)
    expect(screen.getByText(/invented \[99\.99\.99\]/)).toBeInTheDocument()
  })

  it('given several ids in one bracket, when rendered, then each is its own button', async () => {
    /** Regression: "[9.7.6, 9.7.7]" matched nothing and stayed plain text. */
    // Given a claim resting on two sections, cited together
    const onCite = vi.fn()
    render(<Markdown text="Wealthy households keep servants [9.7.6, 9.7.7]."
                     citations={cited('9.7.6', '9.7.7')} onCite={onCite} />)

    // When the second is pressed
    await userEvent.click(screen.getByRole('button', { name: '2' }))

    // Then both are numbered buttons, and each opens its own section
    expect(screen.getByRole('button', { name: '1' }))
      .toHaveAttribute('title', 'Section 9.7.6 (9.7.6)')
    expect(onCite).toHaveBeenCalledWith('9.7.7')
    expect(screen.queryByText(/9\.7\.6, 9\.7\.7/)).toBeNull()
  })

  it('given a bracket mixing a real id and an invented one, when rendered, then only the real one is a button', () => {
    // Given one bracket citing a resolved section and an id that resolved to nothing
    render(<Markdown text="Servants [9.7.6; 99.99.99]."
                     citations={cited('9.7.6')} onCite={() => {}} />)

    // When the buttons are counted
    // Then the real id is pressable and the invented one is left as written
    expect(screen.getAllByRole('button')).toHaveLength(1)
    expect(screen.getByText(/\[99\.99\.99\]/)).toBeInTheDocument()
  })

  it('given an answer still streaming, when rendered, then it is already numbered', () => {
    // Given tokens arriving before the citations have been resolved
    render(<Markdown text="A [11.2.114] and B [7.1.44]." onCite={() => {}} />)

    // When the citations are found
    // Then the reader is not made to read dotted ids until the turn ends
    expect(screen.getByRole('button', { name: '1' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '2' })).toBeInTheDocument()
  })

  it('given a citation inside a table, when rendered, then it is still a button', () => {
    // Given an answer citing from inside a table cell
    const table = ['| Condition | Effect |', '|---|---|',
                   '| Prone [11.2.114] | Disadvantage |'].join('\n')

    // When it is rendered
    render(<Markdown text={table} citations={cited('11.2.114')}
                     onCite={() => {}} />)

    // Then the citation works there as anywhere else
    expect(screen.getByRole('button', { name: '1' })).toBeInTheDocument()
  })

  it('given a citation in a list item, when rendered, then it is still a button', () => {
    // Given an answer citing from inside a list
    render(<Markdown text={'- Prone [11.2.114]\n- Restrained [11.2.120]'}
                     citations={cited('11.2.114', '11.2.120')}
                     onCite={() => {}} />)

    // When the citations are found
    // Then both are pressable
    expect(screen.getByRole('button', { name: '1' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '2' })).toBeInTheDocument()
  })

  it('given ordinary brackets, when rendered, then they are not citations', () => {
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
