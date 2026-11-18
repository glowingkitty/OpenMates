# Figma and Penpot APIs for the Design app

Researched 2026-11-16 from the providers' official documentation. Nothing here
was measured against a live account yet; the real-account test records actual
sizes and limits. Specification: `specifications/features/app-skills/design-figma/`.

## Figma REST API

Docs: https://developers.figma.com/docs/rest-api/ (file endpoints:
https://developers.figma.com/docs/rest-api/file-endpoints/, node types:
https://developers.figma.com/docs/rest-api/file-node-types/).

### What a file looks like

A Figma file is one JSON tree. `GET /v1/files/:key` returns file identity
(`name`, `version`, `lastModified`, `editorType`, `role`, `thumbnailUrl`,
`mainFileKey`, `branches`) plus three parts:

- `document`: the tree. The root `DOCUMENT` node has pages (`CANVAS`) as
  children. Each page holds top-level layers: `FRAME` (an artboard or screen),
  `SECTION` (a group of frames on the canvas), `GROUP`, `COMPONENT`,
  `COMPONENT_SET`, `INSTANCE`, `TEXT`, vectors and shapes. Frames nest frames.
- `components` and `componentSets`: metadata for the components the returned
  tree uses (name, description, key).
- `styles`: named colour, text, effect and grid styles.

Every node has an `id` (`12:34`; links write it as `node-id=12-34`), a `type`,
a `name` and type-specific fields: `absoluteBoundingBox` (position and size),
`absoluteRenderBounds` (including shadows), auto layout (`layoutMode`
NONE/HORIZONTAL/VERTICAL/GRID, padding, spacing), `fills`, `strokes`,
`effects`, `cornerRadius`, `characters` and `style` on text, and `componentId`
on instances.

### Reading less than the whole file

- `depth`: `1` returns pages only, `2` pages plus their top-level frames and
  sections; omitted returns everything.
- `ids`: returns only the listed nodes with their children and ancestor chain.
- `GET /v1/files/:key/nodes?ids=…&depth=…` returns a map from node id to
  `{document, components, componentSets, styles}`, so component and style
  metadata come back per node. Unknown ids come back as `null`.
- `geometry=paths` adds raw vector paths (large; OpenMates never asks for it).
- `version` pins a file version; `branch_data` lists branches.
- `GET /v1/files/:key/meta` (scope `file_metadata:read`) returns name,
  version, last change and thumbnail without the tree.

### Sizes

Figma publishes no size figure. Its only guidance is to narrow requests: since
December 2024 an oversized `GET file` returns "Request too large" instead of a
timeout (https://developers.figma.com/docs/rest-api/changelog). Our own
estimate, to be replaced by real measurements: a node is roughly 0.5 to 2 KB of
JSON, one detailed screen has a few hundred to a few thousand nodes (about
0.3 to 3 MB, i.e. 100k to 1M tokens raw), and a product file with a hundred
screens is tens of MB. The raw tree never fits a context window; it has to be
reduced on the server.

### Image export

- `GET /v1/images/:key?ids=…` renders nodes as `png`, `jpg`, `svg` or `pdf`,
  `scale` 0.01 to 4, with SVG options and `use_absolute_bounds`. It returns
  `{images: {id: url}}`; a `null` url means that render failed. Renders over
  32 megapixels are scaled down. URLs expire after 30 days.
- `GET /v1/files/:key/images` returns download URLs for image fills (photos
  placed in the design); they expire after at most 14 days.

### Rate limits and plans

Source: https://developers.figma.com/docs/rest-api/rate-limits/. Limits count
per user, per plan and per OAuth app.

| Tier | Endpoints | View or Collab seat | Dev or Full seat |
|---|---|---|---|
| 1 | GET file, GET file nodes, GET image | up to 20 per **month** | 10/min (Starter), 15/min (Pro), 20/min (Org) |
| 2 | comments, image fills, variables (GET), team/folder listing, versions, webhooks | up to 5/min | 25 / 50 / 100 per min |
| 3 | file metadata, components and styles, users, POST variables | up to 10/min | 50 / 100 / 150 per min |

The same page says a View seat "might only be able to make 2 requests in a
month to get a file" and a Starter file is capped at "up to 6 per month". So a
viewer-seat user can afford only a handful of design reads per month. A 429
carries `Retry-After`, `X-Figma-Plan-Tier`, `X-Figma-Rate-Limit-Type` (`low`
= View/Collab seat) and `X-Figma-Upgrade-Link`.

### Scopes

Source: https://developers.figma.com/docs/rest-api/scopes/. Available to every
OAuth app: `current_user:read`, `file_content:read`, `file_metadata:read`,
`file_versions:read`, `file_comments:read/write`, `file_dev_resources:read/write`,
`library_*:read`, `webhooks:read/write`, `folders:read`. Enterprise only:
`file_variables:read/write`. Private apps only: team listing (`teams:read`),
file duplication and folder writes. `files:read` and `projects:read` are
deprecated; the old project listing endpoints do not work for public OAuth apps.

### What can be written

- REST writes: comments and reactions, dev resources (links on nodes),
  webhooks, and variables (`POST /v1/files/:key/variables`, Enterprise only).
- No REST endpoint creates or edits frames, shapes or text.
- The Plugin API edits the canvas, but plugins run inside the open Figma
  editor, not from a server.
- Figma's MCP server (https://developers.figma.com/docs/figma-mcp-server/)
  now writes to the canvas too (`use_figma`, `generate_figma_design`; Full seat
  outside drafts). It is meant for desktop or agent tools, its auth model for a
  server-side integration is not documented, and it is free only during beta.
  OpenMates does not use it.

So Figma is a read source for OpenMates. Writing designs into Figma is out of
reach through the documented REST API.

## Penpot

Docs: https://help.penpot.app/technical-guide/integration/ and the API
reference generated by each instance at `/api/_doc`
(https://design.penpot.app/api/_doc). Open source (MPL-2.0,
https://github.com/penpot/penpot), self-hostable with Docker Compose or
Kubernetes (https://help.penpot.app/technical-guide/getting-started/).

### API

- RPC over HTTP: `POST https://<instance>/api/rpc/command/<method>`. It speaks
  JSON or Transit, chosen with the `Accept` header (Transit is the default).
- Penpot documents it for integrations ("expect more functions in the future")
  but gives no stability or versioning promise; the reference is generated from
  the backend source of each version.
- Self-hosted instances expose the same API for their version. Access tokens
  must be enabled there (`enable-access-tokens`, Penpot 2.0+).

### Authentication

- Personal access tokens only: Your account > Integrations > Personal access
  tokens, with an expiry of never, 30, 60, 90 or 180 days, shown once, sent as
  `Authorization: Token <token>`.
- Tokens have no scopes; a token can do everything the user can.
- Penpot offers no OAuth for third-party apps, so the user pastes a token.

### Reading

- `get-file` (`id`): the file with its pages, components, colours and
  typographies. `get-file-summary` and `get-file-info` are lighter.
- `get-page` (`fileId`, `pageId`, `objectId` one or a set): one page or just
  selected boards. Penpot uses it for its own exporter. This is the targeted
  read.
- `get-project-files`, `get-team-recent-files`, `get-team-shared-files` and
  `search-files` list files, which Figma's public apps cannot do.
- `get-file-object-thumbnails`: stored board thumbnails.
- Shapes are a tree under a root frame. Boards are Penpot's frames. A shape
  has a selection rectangle, transform, constraints, fills, strokes, shadow,
  blur, text content and font, export settings and flex or grid layout
  (https://help.penpot.app/technical-guide/developer/data-model/).
- Design tokens are native and follow the W3C Design Tokens format, in sets
  and themes per file (https://help.penpot.app/user-guide/design-tokens/).
  Whether `get-file` returns them still needs a real-instance check.
- Rendering boards to PNG or SVG runs in Penpot's internal exporter service,
  which the API reference does not document. Only stored thumbnails are a
  documented read.

### Writing

`create-file`, `update-file` (a list of changes against a revision) and
comment methods exist in the API reference, so Penpot can create and edit
designs from a server. The change format is the internal one and is not
promised stable. Penpot's MCP server (https://help.penpot.app/mcp/) also edits
designs, but only through an open Penpot browser tab with its plugin connected.

### Limits

Penpot publishes no API quota for design.penpot.app. Self-hosted instances can
turn on RPC rate limiting. The pricing page (https://penpot.app/pricing) has
no API terms.

### Integration consequences

- The instance URL is user-supplied: https only, public DNS only (no private,
  loopback or link-local addresses after resolution), no redirects to other hosts.
- The token is full-account access, so OpenMates calls only an allowlist of
  read methods and asks users to create a dedicated token with an expiry.
- API shape changes are likely between versions; parsing tolerates unknown
  fields and contract tests pin the shapes we rely on.
