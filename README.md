# Jarvis OS Cloud — Personal v1

Serverless Jarvis on Cloudflare. Two pieces:

- **Worker** (root): API on Cloudflare Workers + D1, with `/chat`, `/threads`,
  `/memory` and SSE streaming.
- **Web HUD** (`web/`): vanilla TS + Vite, deployed to Cloudflare Pages.

This is the **Personal v1** iteration: usable daily by you, with structured
memory (5 categories: facts, preferences, commitments, projects, episodes),
streaming chat, and an editable memory page. Voice realtime, mobile, agents,
Durable Objects per user, etc., come in later iterations.

## Endpoints

| Method | Path | Auth | Body | Returns |
| --- | --- | --- | --- | --- |
| GET | `/health` | — | — | `{ok, version}` |
| POST | `/chat` | Bearer | `{thread_id?, message}` | `{thread_id, reply}` (or SSE if `Accept: text/event-stream`) |
| GET | `/threads` | Bearer | — | `[{id,title,...}]` |
| GET | `/threads/:id` | Bearer | — | `{id, messages:[…], ...}` |
| DELETE | `/threads/:id` | Bearer | — | `204` |
| GET | `/memory` | Bearer | — | `{facts, preferences, commitments, projects, episodes}` |
| GET | `/memory/:kind` | Bearer | — | array |
| POST | `/memory/:kind` | Bearer | item without `id` | created item |
| PATCH | `/memory/:kind/:id` | Bearer | partial | updated item |
| DELETE | `/memory/:kind/:id` | Bearer | — | `204` |
| GET | `/events?kind=&since=&limit=` | Bearer | — | `Event[]` (most recent first) |
| GET | `/suggestions?status=` | Bearer | — | `Suggestion[]` |
| POST | `/suggestions` | Bearer | `{title, reason?, priority?, action_payload?, thread_id?}` | created suggestion |
| PATCH | `/suggestions/:id` | Bearer | `{status?, priority?, title?, reason?}` | updated suggestion |
| DELETE | `/suggestions/:id` | Bearer | — | `204` |

`:kind` ∈ `facts | preferences | commitments | projects | episodes`. Bearer
token = `JARVIS_API_KEY` (Worker secret). `/health` is public. Memory snapshot
is auto-injected as the system prompt on every `/chat`.

After every `/chat` response, if `JARVIS_BUTLER_ENABLED=true` (default), the
**Butler** agent runs in `waitUntil` and asks the LLM whether the conversation
implies any actionable suggestions (commitments, calls, reminders). Each is
written to `suggestions` and surfaces in the HUD's Butler tab.

## Local development

### Worker

```bash
npm install
cp .dev.vars.example .dev.vars   # set OPENAI_API_KEY + JARVIS_API_KEY
npm run db:migrate:local
npm run dev   # http://localhost:8787

# in another shell
curl http://localhost:8787/health
curl -N -X POST http://localhost:8787/chat \
  -H "Authorization: Bearer dev-local-token" \
  -H "Accept: text/event-stream" \
  -H "content-type: application/json" \
  -d '{"message":"hola"}'
```

### Web HUD

```bash
cd web
npm install
npm run dev   # http://localhost:5173
```

Open the page, click *Ajustes*, paste `http://localhost:8787` and your bearer.

## Tests

```bash
npm run typecheck && npm test          # worker — 31 tests
cd web && npm run typecheck            # web — type-only
```

## First-time production setup

You need a Cloudflare account and an OpenAI account.

```bash
npx wrangler login

npx wrangler d1 create jarvis
# copy database_id into wrangler.toml

npm run db:migrate:remote
npx wrangler secret put OPENAI_API_KEY
npx wrangler secret put JARVIS_API_KEY
npx wrangler deploy

# Pages project (web HUD)
cd web
npx wrangler pages project create jarvis-hud
npm run build
npx wrangler pages deploy dist --project-name=jarvis-hud --branch=main
```

After the first Pages deploy, update `wrangler.toml` so `JARVIS_WEB_ORIGIN`
points at the Pages URL (instead of `*`) for tighter CORS.

## CI/CD

`.github/workflows/deploy.yml` runs two jobs in parallel on push to `main`:

- **worker** — install + typecheck + test + apply D1 migrations + deploy
  Worker.
- **web** — install + typecheck + build + deploy Pages.

Required repo secrets:
- `CLOUDFLARE_API_TOKEN` — token with `Workers Scripts:Edit`, `D1:Edit`,
  `Cloudflare Pages:Edit`.
- `CLOUDFLARE_ACCOUNT_ID`.

`OPENAI_API_KEY` and `JARVIS_API_KEY` live as **Worker** secrets, not GitHub
secrets.

## Layout

```
src/                       Worker source
  index.ts                 Hono app wiring (cors → health → auth → routes)
  env.ts                   Env type
  middleware/
    auth.ts                Bearer
    cors.ts                CORS w/ JARVIS_WEB_ORIGIN allowlist
  routes/
    health.ts
    chat.ts                streaming SSE + memory injection + butler trigger
    threads.ts             emits thread.* events
    memory.ts              CRUD over 5 kinds, emits memory.* events
    events.ts              GET /events
    suggestions.ts         CRUD /suggestions
  services/
    memory.ts              threads + messages
    memory_store.ts        5-kind memory CRUD + snapshot + context render
    events.ts              EventBus.emit/list
    suggestions.ts         SuggestionsStore + runButler
    openai.ts              chatCompletion + chatCompletionStream
  types.ts
migrations/
  0001_init.sql            threads, messages
  0002_memory.sql          facts, preferences, commitments, projects, episodes
  0003_events_suggestions.sql   events, suggestions
test/{chat,butler}.test.ts 31 tests
web/                       Vite vanilla TS HUD (Cloudflare Pages)
  index.html               chat page
  memory.html              memory editor
  butler.html              suggestions inbox
  src/{main,memory,butler,api,auth,badge,types,styles}.{ts,css}
.github/workflows/deploy.yml
```

## Roadmap (next iterations)

- Durable Object per user for hot state + WebSockets.
- OpenAI Realtime + 3D orb (voice).
- Embeddings + Vectorize for memory search.
- Function calling so the LLM can write to memory itself.
- Apple mode (CloudKit + iCloud Drive sync).
- Mobile app, Mac Agent.
- Home Assistant + n8n integrations.
- Specialized agents (Butler / Planner / Coder / Home / Research / Ops / Finance).
- Capability marketplace (manifest + permissions + tests + rollback).
- Real auth (OAuth) instead of static bearer.
