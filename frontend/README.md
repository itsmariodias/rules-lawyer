# Frontend

The Rules Lawyer chat UI: React 19, TypeScript and Vite. Three columns: the
list of conversations, the conversation itself, and a side panel that shows
the cited page of the SRD or the graph around it.

It needs the [backend](../backend/README.md) running on `:8000`. In
development Vite proxies `/api/*` to it (dropping the `/api`), so the browser
only ever talks to one origin.

## Commands

```bash
npm install
npm run dev          # http://localhost:5173
npm test             # vitest, once
npm run test:watch   # vitest, re-running on save
npm run coverage     # with a coverage report
npm run lint         # oxlint
npm run build        # type-check and build to dist/
```

`VITE_API_TARGET` points the proxy at another backend; the end-to-end suite
uses it to run on its own port.

## Layout

```text
src/
  main.tsx              mounts <App />
  App.tsx               the shell: thread list, conversation, side panel
  api.ts                every call to the backend, and the types it returns
  useChat.ts            the open conversation: send, stream, retry, reopen
  useGraphStatus.ts     whether the graph is reachable, polled until it is
  useStored.ts          state remembered in localStorage; the light/dark theme
  index.css             all styles; colour tokens are at the top

  components/
    Markdown.tsx        an answer, with [11.2.114] citations as numbered links
    ToolTrace.tsx       the lookups the agent made during a turn
    Timing.tsx          elapsed time while a turn runs, its date after
    Usage.tsx           tokens used by a turn
    SidePanel.tsx       the Page and Graph tabs
    PdfPage.tsx         a PDF page drawn with pdf.js, cited lines boxed
    GraphView.tsx       the graph around the cited section
    graph-layout.ts     the graph's pure maths: spring length, fit, colours, merging
    Resizer.tsx         the drag handle that sizes the side panel
```

Tests sit beside the file they cover: `api.test.ts` tests `api.ts`.

## Features

**Stack.** React 19 and TypeScript, built and served by Vite. Markdown is
rendered with `react-markdown` and `remark-gfm` (tables), PDF pages with
Mozilla's `pdfjs-dist`. There is no state library, router, CSS framework or
graph library: state is React hooks, styles are one `index.css`, and the
graph is drawn in SVG by our own code. Tests use vitest and Testing Library.

**Streaming answers.** `useChat` calls `streamChat` in `api.ts`, which
`POST`s `/chat` and reads the Server-Sent Event stream with `fetch` (not
`EventSource`, which cannot `POST`). Each event updates the turn as it
arrives:

| Event | Effect |
| --- | --- |
| `start` | the turn has a thread id |
| `token` | more answer text |
| `tool_start` / `tool_end` | a lookup appears in the trace, then its outcome |
| `usage` | token counts |
| `citations` | the sections the answer cited, resolved, in order |
| `error` | the turn failed; the message is shown with "Try again" |
| `done` | the turn is over |

`ChatEvent` in `api.ts` is the type for these and mirrors the backend's
`chat/service.py`; change both together. Clicking a lookup in the trace
fetches its full result from `/chat/threads/{id}/lookups/{call_id}`.

### Citations

1. **The answer.** The model writes dotted section ids. `Markdown.tsx`
   rewrites each one to a `#cite-` link before parsing, so citations work
   inside tables and lists, then renders the link as a numbered button:
   `[1]`, `[2]`, in order of first appearance. Ids the backend could not
   resolve stay as plain text. The list under the answer is the legend.
2. **The excerpt.** Clicking a citation sets the cited section in `App`,
   which opens `SidePanel`. It fetches `/source/{id}`, which returns the
   section's heading, its pages, and `boxes`: one rectangle per printed line
   of the section, in PDF points with the origin top-left. The backend
   recorded those rectangles while parsing the PDF, so they match the print
   exactly. It also returns `ancestors` and `children`, shown as a
   breadcrumb above the page and a list of subsections below it.
3. **The page.** `PdfPage.tsx` loads the SRD once per session from `/pdf`
   (pdf.js fetches it in byte ranges) and, for each page the section is on,
   stacks three layers:
   - a `<canvas>` with the page drawn by pdf.js, at the device's pixel ratio
     so text stays sharp;
   - pdf.js's text layer, invisible spans over the glyphs, so text can be
     selected and copied;
   - the highlight boxes, scaled from points to pixels and blended with
     `mix-blend-mode: multiply`, so the paper takes the tint and the ink
     stays black.
4. **Long sections.** A section's boxes cover everything under it (Monsters
   A-Z spans 87 pages), so only the first boxed page renders straight away
   and scrolls itself into view. The rest are placeholders sized from page
   1's aspect ratio, rendered by an `IntersectionObserver` as they come
   within 900px of the viewport.
5. **Resizing and zoom.** The page's displayed size follows the panel's
   width on every frame (a `ResizeObserver`), but the bitmap is only redrawn
   once the width has been still for 150ms, off screen, then copied in, since
   resizing a visible canvas clears it. Zoom is Fit, 1.5x or 2x; above Fit,
   Space+drag or middle-drag pans, because a plain drag selects text.

With nothing cited, the Page tab shows the whole book, every page lazily
rendered the same way, with a box to jump to a page. The text layer's CSS is
our own (under `.pdf-stack` in `index.css`): pdf.js's `pdf_viewer.css` would
add the whole viewer's global styles to the app.

### Graph

1. **The data.** The Graph tab calls `/neighbourhood?section={id}&depth=1`,
   answered by the backend's `chat/neighbourhood.py` (the agent's
   `explore_srd_graph` tool uses the same walk). One Cypher query per hop
   takes every relationship of the nodes found so far, groups them by type
   and direction, and keeps at most `fan` (default 8) per group,
   highest-degree neighbours first and name as the tie-break, so the same
   request always returns the same sample. Nodes are admitted until the
   `limit` of 60. With nothing cited the call has no seed, and the walk
   starts at the book, a node the server makes and joins to the 16
   top-level sections. The response has:
   - `nodes`: each with `uid` (Neo4j's `elementId`, since derived nodes have
     no section id), its labels, name, `section_id` and page if it is a
     section, a short plain-text `summary` (or a few `facts` when it has no
     prose), its `degree` in the whole graph and its `depth` from the seed;
   - `edges`: `uid`, relationship `type`, `source` and `target`;
   - `truncated`: per node, type and direction, how many edges exist against
     how many were sent ("121 in the graph, 8 shown").
2. **The model.** The fetched `Neighbourhood` is React state. Positions live
   outside it, in a `Map` of bodies (`x`, `y`, velocity, pinned) held in a
   ref, so the simulation can move them every frame without touching React
   state per node. The seed is pinned at the centre. A new node is placed at
   rest length from a neighbour already on screen, at its index times the
   golden angle, so expanding grows the picture outward instead of
   scrambling it.
3. **The layout.** A force simulation on `requestAnimationFrame`. Each frame:
   - every pair of nodes repels, with a force falling off with the square of
     the distance (capped, so overlapping nodes do not explode apart);
   - every edge pulls its two ends toward a rest length, like a spring;
   - every node is pulled weakly toward the centre, and its velocity damped
     by friction;
   - movement is scaled by `alpha`, which cools by a fixed factor every
     frame; below a threshold the loop stops and the picture stays still.

   The rest length is the panel's area per node (`restLength`), clamped, so
   a crowded graph packs tighter and a sparse one spreads out; repulsion is
   scaled from it so the two stay balanced. Pairwise repulsion is O(n²),
   which is nothing at 60 nodes.
4. **The framing.** Until the user pans, zooms or drags, every frame also
   refits the view (`fit`): it frames every node and its label (labels
   overhang a node by about 130 units), zooms no further out than 1:1, and
   keeps clear of the details card's measured height. `Fit` hands the
   framing back.
5. **The drawing.** Each frame publishes the positions to React, which
   redraws one `<svg>`: a `<g>` transformed by the pan and zoom, `<line>`s
   with arrow markers for edges, `<circle>`s for nodes and `<text>` for
   labels.
   - A node's radius grows with the square root of its degree.
   - Its colour comes from `KINDS` in `graph-layout.ts`, a priority list of
     labels (creature, ability, spell, item, glossary, class, rule) where the
     first match wins, since a node like `:Section:Creature` has several.
   - **Filled nodes are sections of the book and open on the Page tab;
     hollow ones are derived** (a creature's ability, a damage type).
   - A dashed halo marks a node the server holds more edges for.
   - Edge types are labelled only on the selected node's edges, at most
     five.
6. **Expanding.** Clicking a node selects it and shows a details card: its
   summary or facts, and one row per relationship type and direction, edges
   drawn against total. Expanding calls `/neighbourhood?node={uid}` with
   `fan` set to twice the node's largest drawn group (the sample is
   deterministic, so the same `fan` would return the same nodes) and
   `merge`s the result: new nodes and edges are added, existing ones keep
   their depth and position, and the simulation runs again. Dragging a node
   moves it, the wheel zooms about the pointer, and dragging the background
   pans. The depth selector (1 to 3 hops) refetches from the cited section.

There is no graph library (no D3, Cytoscape, Sigma or vis.js): the Graph tab
is about 700 lines of our own TypeScript, `GraphView.tsx` for state,
simulation and SVG, and `graph-layout.ts` for the pure parts (`restLength`,
`fit`, `kindOf`, `merge`, the edge counting), tested without a DOM. The
backend's tests check that `KINDS` covers every label the graph has, so a new
label cannot silently draw grey.

### Conversations

The thread list comes from `/chat/threads`, pinned first. Threads can be
pinned, deleted after a confirmation (a native `<dialog>`), and reopened with
their trace. Retry re-asks the last question. Panel width, whether the thread
list is open, page zoom, graph depth and theme are remembered in localStorage
through `useStored`.

## Tests

`npm test` runs vitest with Testing Library in jsdom. It needs no backend:
`fetch`, pdf.js and the graph view are mocked where needed. The end-to-end
suite in [`../e2e`](../e2e/README.md) covers the app against the real stack.
