# Jarvis OS Cloud — MVP

Serverless Jarvis backend on Cloudflare Workers. This is the **MVP**: a `/chat`
endpoint that talks to OpenAI and persists threads in D1. Web HUD, voice
realtime, mobile, agents and the rest of the architecture are future iterations.

## Endpoints

| Method | Path | Auth | Body | Returns |
| --- | --- | --- | --- | --- |
| GET | `/health` | — | — | `{ok, version}` |
| POST | `/chat` | Bearer | `{thread_id?, message}` | `{thread_id, reply}` |
| GET | `/threads` | Bearer | — | `[{id,title,updated_at,...}]` |
| GET | `/threads/:id` | Bearer | — | `{id, messages:[…], ...}` |
| DELETE | `/threads/:id` | Bearer | — | `204` |

Bearer token = `JARVIS_API_KEY` (set as Worker secret). `/health` is public.

## Local development

```bash
npm install

# secrets for `wrangler dev`
cp .dev.vars.example .dev.vars
# edit .dev.vars and set OPENAI_API_KEY + JARVIS_API_KEY

# create local D1 + apply migrations
npm run db:migrate:local

# run worker locally
npm run dev

# in another shell
curl http://localhost:8787/health
curl -X POST http://localhost:8787/chat \
  -H "Authorization: Bearer dev-local-token" \
  -H "content-type: application/json" \
  -d '{"message":"hola Jarvis"}'
```

## Tests

```bash
npm run typecheck
npm test
```

Tests use `@cloudflare/vitest-pool-workers` with miniflare. OpenAI is mocked via
`fetchMock` from `cloudflare:test`, so no real API key is needed.

## First-time setup (production)

You need a Cloudflare account and an OpenAI account.

```bash
# 1. login
npx wrangler login

# 2. create D1 database
npx wrangler d1 create jarvis
# copy the database_id from the output into wrangler.toml

# 3. apply migrations to remote D1
npm run db:migrate:remote

# 4. set secrets
npx wrangler secret put OPENAI_API_KEY
npx wrangler secret put JARVIS_API_KEY

# 5. first deploy
npx wrangler deploy
```

After this, every push to `main` will redeploy via GitHub Actions (see below).

## GitHub Actions

`.github/workflows/deploy.yml` runs on push to `main`:
1. install + typecheck + test
2. apply D1 migrations (remote)
3. `wrangler deploy`

Required repo secrets:
- `CLOUDFLARE_API_TOKEN` — token with `Workers Scripts:Edit` and `D1:Edit`
- `CLOUDFLARE_ACCOUNT_ID` — Cloudflare account id

`OPENAI_API_KEY` and `JARVIS_API_KEY` live as **Worker** secrets (`wrangler
secret put`), not GitHub secrets.

## Layout

```
src/
  index.ts           Hono app wiring
  env.ts             Env type (D1 + secrets + vars)
  middleware/auth.ts Bearer auth
  routes/            health, chat, threads
  services/          memory (D1), openai (chat completions)
  types.ts           Thread, Message
migrations/0001_init.sql
test/chat.test.ts
.github/workflows/deploy.yml
```

## Roadmap (next iterations, not in MVP)

- Web HUD (Cloudflare Pages → fetches this Worker).
- SSE streaming on `/chat`.
- Embeddings + Vectorize for memory graph.
- Voice realtime via WebRTC + Durable Objects.
- OAuth (Apple / Google) instead of static bearer.
- Capability marketplace (LLM-callable tools).
