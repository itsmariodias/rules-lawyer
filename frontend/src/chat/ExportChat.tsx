/**
 * Export the open conversation: a native popover of the file types the
 * backend makes, each a download link, so the browser saves the file under
 * the name the server gives it.  The browser closes the popover on an
 * outside click or Escape.
 */

import { useId, useRef } from 'react'
import { exportUrl, type ExportFormat } from '../api'
import { DownloadIcon } from '../shared/icons'

const FORMATS: { format: ExportFormat; label: string }[] = [
  { format: 'markdown', label: 'Markdown (.md)' },
  { format: 'docx', label: 'Word (.docx)' },
  { format: 'pdf', label: 'PDF (.pdf)' },
]

type Props = {
  threadId: string
  /** A turn is streaming, so the conversation is not finished. */
  disabled: boolean
}

export function ExportChat({ threadId, disabled }: Props) {
  const menuId = useId()
  const menu = useRef<HTMLDivElement>(null)

  return (
    <div className="export-chat">
      <button className="head-button" disabled={disabled}
              popoverTarget={menuId} aria-haspopup="menu"
              title="Export chat" aria-label="Export chat">
        <DownloadIcon />
      </button>
      <div id={menuId} ref={menu} popover="auto" role="menu"
           className="export-menu">
        {FORMATS.map(({ format, label }) => (
          // A download does not leave the page, so nothing else closes it.
          <a key={format} role="menuitem" href={exportUrl(threadId, format)}
             download onClick={() => menu.current?.hidePopover()}>
            {label}
          </a>
        ))}
      </div>
    </div>
  )
}
