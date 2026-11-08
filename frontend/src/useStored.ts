/**
 * `useState` persisted to `localStorage` as JSON.  Access is wrapped in
 * try/catch because blocked storage throws rather than returning null.
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
      // Storage blocked; the value lives for this session only.
    }
  }, [key, value])

  return [value, setValue] as const
}

export type Theme = 'system' | 'light' | 'dark'

/**
 * The stored theme, applied as `data-theme` on `<html>`.  `system` removes
 * the attribute so `color-scheme: light dark` follows the OS without a
 * listener.
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
