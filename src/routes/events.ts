import { Hono } from "hono";
import type { Env } from "../env";
import { EventBus } from "../services/events";

export const events = new Hono<{ Bindings: Env }>();

events.get("/events", async (c) => {
  const bus = new EventBus(c.env.DB, c.env.HUD_HUB);
  const since = parseIntParam(c.req.query("since"));
  const limit = parseIntParam(c.req.query("limit"));
  const kind = c.req.query("kind");
  const list = await bus.list({
    since: since ?? undefined,
    kind: kind ?? undefined,
    limit: limit ?? undefined,
  });
  return c.json(list);
});

function parseIntParam(v: string | undefined): number | null {
  if (!v) return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}
