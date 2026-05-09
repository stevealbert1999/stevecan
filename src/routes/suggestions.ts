import { Hono } from "hono";
import type { Env } from "../env";
import { EventBus } from "../services/events";
import { SuggestionsStore } from "../services/suggestions";
import type { SuggestionStatus } from "../types";

export const suggestions = new Hono<{ Bindings: Env }>();

suggestions.get("/suggestions", async (c) => {
  const bus = new EventBus(c.env.DB, c.env.HUD_HUB);
  const store = new SuggestionsStore(c.env.DB, bus);
  const status = c.req.query("status");
  if (status && !["pending", "accepted", "dismissed"].includes(status)) {
    return c.json({ error: "invalid status" }, 400);
  }
  const list = await store.list({ status: status as SuggestionStatus | undefined });
  return c.json(list);
});

suggestions.post("/suggestions", async (c) => {
  let body: Record<string, unknown>;
  try {
    body = await c.req.json();
  } catch {
    return c.json({ error: "invalid json" }, 400);
  }
  const title = typeof body.title === "string" ? body.title.trim() : "";
  if (!title) return c.json({ error: "title is required" }, 400);

  const bus = new EventBus(c.env.DB, c.env.HUD_HUB);
  const store = new SuggestionsStore(c.env.DB, bus);
  const sug = await store.create({
    title,
    reason: typeof body.reason === "string" ? body.reason : null,
    priority: typeof body.priority === "number" ? body.priority : undefined,
    action_payload: body.action_payload,
    thread_id: typeof body.thread_id === "string" ? body.thread_id : null,
  });
  return c.json(sug, 201);
});

suggestions.patch("/suggestions/:id", async (c) => {
  const id = c.req.param("id");
  let body: Record<string, unknown>;
  try {
    body = await c.req.json();
  } catch {
    return c.json({ error: "invalid json" }, 400);
  }
  const bus = new EventBus(c.env.DB, c.env.HUD_HUB);
  const store = new SuggestionsStore(c.env.DB, bus);
  try {
    const sug = await store.update(id, {
      status: body.status as SuggestionStatus | undefined,
      priority: typeof body.priority === "number" ? body.priority : undefined,
      title: typeof body.title === "string" ? body.title : undefined,
      reason: typeof body.reason === "string" ? body.reason : undefined,
    });
    if (!sug) return c.json({ error: "not found" }, 404);
    return c.json(sug);
  } catch (err) {
    return c.json(
      { error: err instanceof Error ? err.message : "invalid" },
      400,
    );
  }
});

suggestions.delete("/suggestions/:id", async (c) => {
  const id = c.req.param("id");
  const bus = new EventBus(c.env.DB, c.env.HUD_HUB);
  const store = new SuggestionsStore(c.env.DB, bus);
  const ok = await store.delete(id);
  if (!ok) return c.json({ error: "not found" }, 404);
  return c.body(null, 204);
});
