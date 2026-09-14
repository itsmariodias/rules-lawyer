/**
 * Build the data directory the end-to-end servers run against.
 *
 * `source/` and `output/` link through to the real ones, so the tests read
 * the same PDF and the same artifact the application does, while `chat/`
 * starts empty every run — a conversation left over from the last run would
 * make "the newest conversation is at the top" a coin toss.
 *
 * This is a script rather than a function the config calls, and that is the
 * whole point. Playwright loads the config once per worker as well as in the
 * main process, so anything it does to the filesystem happens again *after*
 * the servers are up — leaving the API holding an open handle to an unlinked
 * `chat.sqlite`, and every write failing with a disk I/O error partway
 * through a turn. Run from the server's own command line, it happens once,
 * before the server it belongs to.
 */

import { existsSync, mkdirSync, rmSync, symlinkSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const root = path.resolve(here, '..')
const data = path.join(here, '.data')

mkdirSync(data, { recursive: true })
for (const name of ['source', 'output']) {
  const link = path.join(data, name)
  if (!existsSync(link)) symlinkSync(path.join(root, 'data', name), link)
}
rmSync(path.join(data, 'chat'), { recursive: true, force: true })
mkdirSync(path.join(data, 'chat'), { recursive: true })
