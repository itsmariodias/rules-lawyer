/**
 * What an answer cost in tokens: the total on the line, the split on hover.
 */

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { formatTokens, Usage } from './Usage'

describe('formatTokens', () => {
  it('given a large count, when formatted, then it is grouped', () => {
    // Given a typical agentic turn
    // When it is formatted
    // Then the thousands are readable at a glance
    expect(formatTokens(18_240)).toBe('18,240 tokens')
    expect(formatTokens(500)).toBe('500 tokens')
  })

  it('given one token, when formatted, then it is singular', () => {
    // Given the smallest count there is
    // When it is formatted
    // Then it reads as English
    expect(formatTokens(1)).toBe('1 token')
  })
})

describe('Usage', () => {
  it('given counts, when drawn, then the total shows and the split is on hover', () => {
    /** The total is what counts against a quota; the split explains it. */
    // Given a turn of five calls
    render(<Usage usage={{ input: 17_790, output: 450, total: 18_240, calls: 5 }} />)

    // When it is drawn
    const line = screen.getByText('18,240 tokens')

    // Then hovering says how it divides
    expect(line).toHaveAttribute('title', '17,790 in · 450 out · 5 model calls')
  })

  it('given one call, when drawn, then the hover says call', () => {
    // Given a turn that needed no tools
    render(<Usage usage={{ input: 3_000, output: 120, total: 3_120, calls: 1 }} />)

    // When it is drawn
    // Then the split is singular too
    expect(screen.getByText('3,120 tokens'))
      .toHaveAttribute('title', '3,000 in · 120 out · 1 model call')
  })
})
