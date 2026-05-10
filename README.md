# Jarvis OS v0

Jarvis OS v0 is the first executable nucleus for a personal AI operating layer: voice-ready API, event bus, user state, minimal HUD, and controlled capability requests.

This repository intentionally starts small. The goal is not to ship a fake Iron Man demo; the goal is to build a deployable, observable core that can later support realtime voice, editable memory, agents, and safe capability evolution.

## Architecture

```text
Client app / HUD
  -> Cloudflare Worker API
  -> Durable Object per user
  -> Event log + hot state
  -> OpenAI session broker later
  -> CloudKit/iCloud sync later
```

## MVP scope

- Cloudflare Worker API.
- Durable Object per user.
- Event stream as the source of traceability.
- Minimal HUD shell.
- Shared TypeScript domain types.
- Capability manifest convention.
- GitHub Actions CI.

## Explicit non-goals for v0

- No VPS dependency.
- No OpenAI key in client code.
- No marketplace.
- No hidden 24/7 iPhone wake-word daemon.
- No automatic production self-patching.
- No raw JSON as the normal user experience.

## Core endpoints

- `GET /health`
- `GET /state`
- `POST /events`
- `GET /events`
- `POST /agent/message`
- `POST /voice/realtime/session`
- `POST /capabilities/request`
- `GET /suggestions`
- `GET /devices`

## Development

```bash
npm install
npm run typecheck
```

Worker development will live under `workers/api`.
