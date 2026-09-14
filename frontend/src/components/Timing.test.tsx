/**
 * When a turn happened, and how long it is taking.
 *
 * The counter is the part worth testing: an agentic turn is quiet for a
 * whole round trip before it says anything, and a number that moves is the
 * difference between waiting and wondering.
 */

import { render, screen } from '@testing-library/react'
import { act } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { Clock, Elapsed, formatDuration, formatMoment } from './Timing'

describe('formatDuration', () => {
  it('given a short wait, when read, then tenths are kept', () => {
    /** Under ten seconds, the difference between 1.2s and 4.8s is the
        interesting part. */
    // Given a wait of a few seconds
    // When it is formatted
    // Then the tenth survives
    expect(formatDuration(4200)).toBe('4.2s')
  })

  it('given a longer wait, when read, then the tenth is dropped', () => {
    // Given a wait past ten seconds, where a tenth is noise
    // When it is formatted
    // Then it is whole seconds
    expect(formatDuration(13_500)).toBe('14s')
  })

  it('given a wait past a minute, when read, then it is minutes and seconds', () => {
    // Given a long turn
    // When it is formatted
    // Then it does not read as ninety-something seconds
    expect(formatDuration(94_000)).toBe('1m 34s')
  })
})

describe('formatMoment', () => {
  const now = new Date('2026-09-14T21:00:00')

  it('given today, when read, then the time alone is enough', () => {
    // Given a turn from this evening
    // When it is formatted
    // Then no date is spent on saying "today"
    expect(formatMoment(new Date('2026-09-14T13:15:00'), now))
      .toMatch(/^\d{1,2}:\d{2}/)
  })

  it('given yesterday, when read, then it is named rather than dated', () => {
    // Given a turn from the day before
    // When it is formatted
    // Then the day is said the way a person would say it
    expect(formatMoment(new Date('2026-09-13T13:15:00'), now))
      .toMatch(/^Yesterday, /)
  })

  it('given an earlier day this year, when read, then the date appears', () => {
    /**
     * The one this exists for: a conversation from three days ago reading
     * "11:15 PM" invites the reader to take it for this evening.
     */
    // Given a turn from earlier in the year
    const shown = formatMoment(new Date('2026-03-02T13:15:00'), now)

    // Then the day and month are there, and the year is not, being this one
    expect(shown).toContain('Mar')
    expect(shown).not.toContain('2026')
  })

  it('given a previous year, when read, then the year appears too', () => {
    // Given a turn from last year
    const shown = formatMoment(new Date('2025-12-30T13:15:00'), now)

    // Then the year is spelled out, since it is no longer the obvious one
    expect(shown).toContain('2025')
    expect(shown).toContain('Dec')
  })

  it('given the turn of the year, when read, then a day apart is still a date', () => {
    /**
     * A December 31st turn read on January 1st is neither today nor this
     * year, and "Yesterday" is the one thing a reader will not misread.
     */
    // Given a turn from the last day of the previous year
    const shown = formatMoment(new Date('2025-12-31T23:30:00'),
                               new Date('2026-01-01T00:30:00'))

    // Then it is dated as yesterday rather than mistaken for tonight
    expect(shown).toMatch(/^Yesterday, /)
  })
})

describe('Clock', () => {
  it('given a moment, when rendered, then it is a machine-readable time', () => {
    // Given the moment a turn was stored
    render(<Clock at="2026-09-14T08:57:45.000Z" />)

    // When it is read
    // Then the element carries the exact value as well as the display one
    expect(screen.getByRole('time')).toHaveAttribute(
      'datetime', '2026-09-14T08:57:45.000Z')
  })

  it('given no moment, when rendered, then nothing is drawn', () => {
    /** A conversation stored before turns were dated is still a
        conversation. */
    // Given a turn with no timestamp
    const { container } = render(<Clock />)

    // When it is rendered
    // Then there is no empty slot where a time would be
    expect(container).toBeEmptyDOMElement()
  })

  it('given an unreadable moment, when rendered, then nothing is drawn', () => {
    // Given something that is not a date
    const { container } = render(<Clock at="not a date" />)

    // When it is rendered
    // Then it is left out rather than rendered as "Invalid Date"
    expect(container).toBeEmptyDOMElement()
  })
})

describe('Elapsed', () => {
  beforeEach(() => { vi.useFakeTimers() })
  afterEach(() => { vi.useRealTimers() })

  it('given a running turn, when time passes, then the count moves', () => {
    // Given a turn that has just started
    const { container } = render(<Elapsed since={Date.now()} />)
    expect(container.textContent).toBe('0.0s')

    // When a second and a half passes
    act(() => { vi.advanceTimersByTime(1500) })

    // Then the reader can see it is still working
    expect(container.textContent).toBe('1.5s')
  })

  it('given a clock that has gone backwards, when rendered, then it is not negative', () => {
    // Given a start moment in the future, which a clock adjustment can cause
    const { container } = render(<Elapsed since={Date.now() + 5000} />)

    // When it is read
    // Then it floors at zero rather than counting down
    expect(container.textContent).toBe('0.0s')
  })
})
