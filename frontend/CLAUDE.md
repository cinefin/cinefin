# frontend/ — the Cinefin SPA

SvelteKit + Svelte 5 (runes) + adapter-static in SPA mode + Tailwind CSS v4, TypeScript strict.
`npm run build` emits static assets to `frontend/build/`; Django serves them at `/app/`
(`cinefin.views.spa_view` — index.html fallback + build assets, no Node at runtime). The SPA is
**THE UI** (`/` redirects to `/app/`; the deleted legacy UI's old top-level paths 302 to their
SPA equivalents), including the first-run setup wizard (`src/routes/setup/`, served at
`/app/setup` — the installer-redirect middleware bounces every page there until setup completes).

## Commands

```bash
npm install            # once
npm run dev            # vite dev server at localhost:5173/app (proxies /api, /media, /stream to :8000)
npm run build          # static build → frontend/build/ (root: npm run build:spa)
npm run check          # svelte-kit sync + svelte-check (strict, fail on warnings)
npm run format         # prettier
npm run generate:api   # re-export the OpenAPI schema (poetry) + regenerate types.gen.ts
```

## Svelte 5 runes ONLY

- `$state` / `$derived` / `$effect` / `$props` / `$bindable` — no `export let`, no legacy
  reactive `$:`, no `svelte/store` by default. Shared reactive state is a class or object with
  `$state` fields in a `*.svelte.ts` module (see `src/lib/stores/playout.svelte.ts`).
- Snippets, not slots: `{#snippet action()}…{/snippet}` / `{@render children()}`.
- Events are props (`onclick={…}`), not `on:click`.
- Icons: `@lucide/svelte`, imported per icon and bundled at build time. **No CDN, no external
  fonts, no runtime fetches to third parties anywhere** — the app must stay self-contained.

## Files & routes

- One page = one `src/routes/<path>/+page.svelte`. SPA mode is set once in
  `src/routes/+layout.ts` (`ssr = false`, `prerender = false`) — don't override per-route.
- `paths.base` is `/app` (svelte.config.js). Internal links: `href="{base}/library"`.
- Shared code in `src/lib/`: `api/` (client + generated types), `components/ui/` (owned
  primitives), `components/shell/` (sidebar/topbar), `stores/` (shared runes state),
  `format.ts` (display formatters).

## API client

- `src/lib/api/client.ts` exports the openapi-fetch client (`api`), `unwrap()` and `ApiError`.
  **All API calls go through it** — no raw `fetch`. Paths carry the `/api/v2` prefix (it's baked
  into the schema): `unwrap(api.GET('/api/v2/movies/list', { params: { query: … } }))`.
- `unwrap()` peels the `{ success, message, data }` envelope and throws a typed `ApiError`
  (message / status / errorCode / details from the backend's ErrorResponseSchema).
- CSRF/auth mirror the legacy client: same-origin credentials, `X-CSRFToken` from the
  `csrftoken` cookie on unsafe methods (only enforced when `security.auth_enabled` is on).
- Regenerating types: `npm run generate:api` runs `manage.py export_openapi` (writes
  `src/lib/api/openapi.json`) then openapi-typescript (→ `src/lib/api/types.gen.ts`). **Both
  generated files are committed** so the frontend builds without a Python env. Regenerate and
  commit them with any backend schema change. Never edit them by hand; never guess payload
  shapes — where a backend schema is untyped, refine it in `src/lib/api/refinements.ts`
  mirrored from the backend serializers.

## Data loading & state conventions

One convention per failure class (ported from the legacy UI's rules):

- Page data goes through `query()` / `Query` (`src/lib/api/query.svelte.ts`): reactive
  `{ data, error, loading }` around a loader. `load()` = visible reload, `refresh()` = silent
  background refetch (keeps last good data), `poll(ms)` from an `$effect` for intervals.
- **Primary region initial load fails** → inline, retryable `<ErrorState error retry>` _in that
  region_ — never a toast that leaves the page blank. Loading = `<Spinner>`, no data =
  `<EmptyState>` with a call to action.
- **User-initiated action fails** → transient error surface; the region it acted on stays put.
- **Supplementary/background fetches** (filter options, poll ticks, poster garnish) degrade
  quietly — keep the last good state, no error stacking.

## Design tokens (src/app.css, Tailwind v4 `@theme`)

The look is **quiet, dark, media-first**: the posters carry the colour and the chrome stays
out of the way. The authority is **`docs/cinefin-ui-spec.html`** (the maintainer-approved blend
of his brand guide with the running interface, settled 2026-09 after many review rounds) — read
it before any visual change; these bullets are the summary, the spec is the law:

- Neutrals are **the room** — the brand guide's near-black taken almost neat (`#07090E` page)
  — and form a **ladder of light** that is how depth is expressed — panels may not use shadows or faceplate edges, so
  tone does the work: `shell` (sidebar + topbar, furthest back) → `bg` (page) → `surface-1`
  (a panel) → `surface-2` (the panel that matters, or a raised row) → `surface-3`. Each step
  is ~1.5× the luminance below it. Text ramp: `text` / `muted` / `faint`.
- **One lifted panel per page**: `<Card lifted>` puts the page's primary panel (now playing,
  the on-air state) on `surface-2` so the eye lands there with no heading or colour shouting.
  Two lifted panels on one page means neither is.
- **Texture**: the page carries a fixed radial falloff painted into `body`'s background (never
  an overlay — text must never lose contrast to it), and `.film-grain` puts fine fractal noise
  (soft light) plus a vignette on LARGE artwork only — a feature's poster, the film drawer.
  Never on thumbnails, list rows or grids, where noise reads as dirt. Both are dark-room
  devices: `theme-light` switches them off.
- Colour signals are the mark's **three channels**: blue `#3A7BFF` is interactive (and IS the
  accent — user-configurable via Settings → Appearance → `display.accent_color`, applied as a
  runtime `--color-accent` override), red `#FF2F4D` is live/destructive (`danger`), green
  `#25E88A` is ready (`success`); amber is the one borrowed non-channel (`warning`). One channel
  at a time per view; all three together only in the mark. Never hardcode the accent hex.
- **Type is three voices** (all bundled in `lib/assets/fonts/`, no CDN): **Tilt Warp names
  things** (page `h1`s via the base layer, the wordmark — single weight, never below 17px,
  never letterspaced), **Archivo explains** (body/labels/buttons — the `--font-sans` default),
  **IBM Plex Mono measures** (`font-mono`: timecodes, durations, counts, paths — the only place
  caps tracking is legal). Sentence case everywhere; no uppercase or letter-spacing utilities
  (app.css neutralises those app-wide; the kiosk is exempt).
- **Corners are binary**: all architecture is square (`rounded-lg`+ resolve to 0 — panels,
  cards, tables, dialog frames, posters); the one radius is 2px on pressable controls
  (`rounded-xs/sm/md` all resolve to 2px — buttons, fields, chips, menus): felt, never seen.
  Don't add arbitrary radii.
- **Motion never displaces on hover or press** — no lifts, no pop-outs, no press-shifts
  (use light changes: `active:brightness-90`, a surface rung, a border). Displacement is for
  things that travel. `ui/Spinner` is the channel chase (indeterminate only; determinate work
  gets a meter); it self-delays 250ms so fast loads never flash it.
- Panels are plain bordered cards (`Card`: 1px border, surface-1, bordered header with a
  sentence-case title). Buttons are subtly filled with a hairline border. Badges are small
  sentence-case tints. Active nav is a soft surface tint. No glassmorphism, no gradient heroes,
  no soft drop shadows on panels, no dashed "slot" outlines, no faceplate top-edges.
- Per-device display prefs (Topbar → Display menu + the sidebar collapse, `lib/display.svelte.ts`,
  legacy localStorage keys): fluid/fixed width, density zoom (rem scaling — always size in
  rem/Tailwind units, never px), theme dark/dim/light (`html.theme-*` overrides), icon-rail
  sidebar (`cpx-display-nav-rail`).
- Use the token utilities (`bg-surface-1`, `text-muted`, `border-border`, `text-accent`) — no
  hardcoded hex values in components.

## Item types (labels, icons, colours)

`src/lib/item-types.ts` is the **single source of truth** for every programme /
playlist item type — its label, its lucide icon and its colour. Never map a type locally
again (the old `TYPE_LABELS` / `formatBlockType` / per-page icon maps are gone).

- API: `itemTypeDisplay(type)` returns everything in one call — `label`, `short` (compact
  operator wording: Feature / Trailers / Hold / Cert), `noun` (`[singular, plural]` for
  breakdown lines), `family`, `icon` and `classes` (`icon` / `badge` / `edge` / `bar`).
  Smaller helpers: `itemType`, `itemTypeLabel(type, { short })`, `itemTypeIcon`,
  `itemTypeClasses`, `itemTypeCount(type, n)`, plus `CUE_LABEL` for instant commands.
  Unknown types fall back to the system family with a prettified label.
- **Six colour families** (types share within a family), as `--color-type-*` tokens in
  `app.css` and overridden for `theme-light` (`theme-dim` inherits the dark values):
  **film** (`movie`, `feature`, `random_movie`) gold · **trailer** (`trailer`,
  `trailer_rule`) violet · **media** (`bumper`, `random_bumper`, `audio_bumper`) cyan ·
  **command** (`command`, cue and hold) indigo (duller than the accent) · **certification**
  rose · **system** (`system`, `ident`, `title`, unknown) slate. All hue-shifted away from
  the channel signals so a type never reads as a status or a link.
- **Application rule**: coloured **icon** + tinted **badge** (always
  `lib/components/TypeBadge.svelte`, which wraps `Badge variant="type"`) + a **2px left
  edge** (`classes.edge`) on a row/card that IS one item — and nothing more. Rows and card
  headers stay on the neutral surface (no washes), so a list is never read through colour.
  In a column, badges share one fixed width with centred labels (spec §05) — ragged badge
  rails are a tell.
- **Adding a type** (or renaming one): add it to the module. Do not add a label, icon or
  colour anywhere else, and do not hardcode the hues — use the token classes the module
  hands out.

## Primitives

`src/lib/components/ui/` is owned code (shadcn-style, copied in, no component library dep):
Button, Card, Badge, Input, Select, Dialog (native `<dialog>`), Spinner, EmptyState,
ErrorState. Extend these rather than re-styling ad-hoc markup; new primitives follow the same
shape (typed `Props` interface, `$props()`, token classes, `class` passthrough).

## Shared components beyond ui/

Reuse these — do NOT reinvent them per page:

- `lib/toast.svelte.ts` (`showToast(msg, kind)`) + `lib/components/Toasts.svelte` — the one
  transient action-feedback surface (success/error/info/warning). Mounted **once** globally in
  `routes/+layout.svelte` as a top-centre stack; pages just call `showToast()` and never mount
  their own host.
- `lib/components/ui/Tabs.svelte` — **the one tab strip** (spec §06 C3): quiet labels over a
  hairline, the active one in text colour with a 2px blue underline drawn in from its centre.
  Use it for every set of tabs (sections of one thing — programme detail, ticket settings, the
  Get trailers / Add media modes); never hand-roll a strip. A status filter is chips and a
  grid/list switch is a pressed toggle (`aria-pressed`) — neither is tabs.
- **Statuses are lamps, not capsules** (spec §06 C3): anything that reports a state (a check's
  result, on disk / missing, active, up to date) is `StatusLamp` — a square lamp beside words,
  breathing (`lamp-pending`) only while in transition. `Badge` is for facts (a certificate,
  "No TMDB", a measured `4K · HDR`). And no spinners: the channel chase is the only loader, and a
  busy button disables and changes its label ("Refreshing…") rather than spinning its icon.
- `lib/components/ui/SidePanel.svelte` — **the detail drawer; detail views never use a `Dialog`.**
  One item beside the list it came from: docked right from `xl` (the page's `<main>` gives up
  `--panel-w` via `html.side-panel-open`, so the list reflows and stays clickable — clicking
  another item swaps the drawer in place), overlaid on a scrim below `xl` (full width on a
  phone). Prev/next + ←/→, Escape, and Back-closes (it pushes a shallow-routing entry unless the
  host owns history — the library passes `history={false}`; pages that aren't a list to browse
  pass `dock={false}`). Hosts mark list items `data-panel-item={id}` and the open one
  `data-panel-current` — it's lit (a neutral outline; the accent already means "selected") and
  kept in view. Content inside is laid out with container queries (`@xs:`/`@sm:`), not viewport
  breakpoints, and grids beside it use auto-fill so docking can't squeeze them.
  `lib/components/DetailPanel.svelte` adds loading/error around it (trailers, media);
  `lib/library/MoviePanel.svelte` is the film view (library, dashboard).
- `lib/components/ConfirmDialog.svelte` — awaitable confirm: hold one instance with
  `bind:this` and `if (!(await dlg.confirm('Delete X?', { confirmLabel: 'Delete' }))) return;`.
- `lib/components/JobConsole.svelte` + `lib/jobs.ts` — the live SSE job console
  (`/api/v2/jobs/stream?kind=sync|trailer`), used by Settings → Library source
  (`routes/settings/LibrarySourceSection.svelte` — the sync surface; the old
  /sync page redirects to `/app/settings?tab=library`) and the trailers page.
  The topbar's "Syncing" lamp is fed by `lib/stores/syncActivity.svelte.ts`, a
  subscriber-counted wrapper on the same stream.
- `lib/programmes/RandomPickDialog.svelte` — configure a **random movie** slot (genres/certificate/
  year/runtime + a live match count). Used by the create page's feature slots and the library's
  filter bar; it is the only producer of a `random_movie` slot outside the programme editor's
  own block config, so extend it rather than building a second filter form.
- `lib/programmes/ProgrammeEditor.svelte`, `lib/templates/TemplateEditor.svelte` and
  `lib/titles/TitleEditor.svelte` — the three editing surfaces (a BlockEditor instance, reference lists, pickers, add/remove/clear,
  validation, save, unsaved-changes guards) around `lib/editor`'s BlockList + palette. **There
  are no editor routes**: a thing is edited on its own page (issue #404), and both editors are
  mounted by their thing's detail route —
  `/programmes/{id}?edit=1`, `/templates/{id}?edit=1` and `/titles/{id}?edit=1` for an existing
  one, and `/programmes/new`, `/templates/new`, `/titles/new` (the same routes, virtual id) for
  one that does not exist yet, where nothing is written until the first save and the editor is
  the whole page. Reference lists
  load when the editor mounts, so viewing never pays for editing. The host passes the blocks it
  already has, reads `bind:dirty`, and calls `discardChanges()` before closing so the
  navigation guard doesn't ask what the discard dialog just asked.
- `lib/components/FilterBar.svelte` — the one toolbar (search / filters / sort / count / view).
  Past three filters it collapses them behind a **Filters** button with an active count
  (`filterPanel` overrides); what is active still reads out as chips on the row beneath. Its
  right-hand cluster (count, page extras, view toggle) is `shrink-0` on the first line, so it
  can never be pushed onto a line of its own — only the left group wraps.
- `lib/upload.ts` — typed XHR multipart upload with progress (openapi-fetch can't do this).
- `lib/api/mutate.ts` — unwrap for message-only envelopes.

## E2E smoke pack

`npm run e2e` runs the Playwright smoke pack (`e2e/*.spec.ts`, config in
`playwright.config.ts`): it builds the SPA, boots a throwaway seeded Django server
(`../scripts/e2e-server.sh` — temp DB, `seed_demo` data, auth off) and drives the load-bearing
flows (shell/nav, library, programme lifecycle, settings, kiosk + remote). It is deliberately a
SMOKE pack, not a test suite — correctness lives in pytest and `npm run check`. Run it before
merging anything that touches routing, the shell, or the SPA↔API contract.

## The home screen

`routes/+page.svelte` is the dashboard: a status board for the whole system,
read top to bottom — playout state in a hero panel, a line of figures (library
and machine), then four panels: next screenings, recently added, programmes, and a
System panel carrying the playout host, the schedule runner, library sync and
any failing health check. It is budgeted to ONE screen on a desktop, so panels
keep a fixed, small number of rows (four) instead of scrolling inside
themselves — adding a row is a decision about what the board can still show.

- `lib/dashboard/data.svelte.ts` holds every feed the page reads, with the
  shared readings (playout badge, item progress, `untilLabel`). Cadences
  differ on purpose: `/system/health` probes the printer, the agent and the
  disks — the app's slowest read — so it polls at 60 s, the rest at 20 s, and
  the sync-job banner check at 5 s.
- **Artwork appears only while a programme is loaded** (maintainer's rule): that
  programme's first feature poster, blurred behind the readout by
  `lib/dashboard/ArtBackdrop.svelte` and crisp beside it. With nothing loaded the
  panel is flat, so artwork always means something is cued. `ArtBackdrop` masks
  rather than overlays, so type never loses contrast to it.
- `lib/dashboard/StatTile.svelte` is one figure in the strip (`tone` only for a
  figure that carries a state); `lib/dashboard/PosterShelf.svelte` is the
  recently-added tiles plus the library's film drawer, its `cols` grid sized to
  fill its panel exactly.

## The setup wizard

`src/routes/setup/+page.svelte` is the first-run wizard (the port of the old server-rendered
installer; that page and the root TypeScript toolchain were deleted with it). It renders as a
fixed full-viewport overlay above the shell (the kiosk trick) so the layout needs no special
casing. Step 1 touches only the always-reachable `/api/v2/installer/` endpoints and finalises
setup atomically at the end of step 1 (playback is what the operator reaches for first); steps
2–5 (playout, movies, trailers & tickets, the readiness check) use the regular
settings/playout/sync endpoints and resume via `setup.wizard_step` (POST /installer/wizard-step)
after a closed browser. Every post-finalise step has a Back button.
