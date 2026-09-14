/**
 * State that outlives a reload.
 *
 * Reading and writing are both guarded: a private window, cleared site data
 * or a browser set to block storage makes `localStorage` throw on access
 * rather than return null, and a reading preference is never worth a blank
 * page.
 */

import { useEffect, useState } from 'react'

export function useStored<T>(key: string, fallback: T) {
  const [value, setValue] = useState<T>(() => {
    try {
      const stored = localStorage.getItem(key)
      return stored === null ? fallback : (JSON.parse(stored) as T)
    } catch {
      return fallback
    }
  })

  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify(value))
    } catch {
      // Nothing to do and nothing worth telling the reader about.
    }
  }, [key, value])

  return [value, setValue] as const
}

export type Theme = 'system' | 'light' | 'dark'

/**
 * The reader's theme, remembered and applied to the document.
 *
 * `system` is the absence of a choice rather than a third palette, so it
 * removes the attribute entirely and leaves the stylesheet's
 * `color-scheme: light dark` to follow the machine — which is also why
 * nothing here listens for the OS changing: the browser re-resolves every
 * `light-dark()` on its own, and a listener could only arrive at the same
 * answer later.
 */
export function useTheme() {
  const [theme, setTheme] = useStored<Theme>('theme', 'system')

  useEffect(() => {
    const root = document.documentElement
    if (theme === 'system') delete root.dataset.theme
    else root.dataset.theme = theme
  }, [theme])

  return [theme, setTheme] as const
}
