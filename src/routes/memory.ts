import { Hono } from "hono";
import type { Env } from "../env";
import { EventBus } from "../services/events";
import { isMemoryKind, MemoryStore, ValidationError } from "../services/memory_store";

export const memory = new Hono<{ Bindings: Env }>();

memory.get("/memory", async (c) => {
  const store = new MemoryStore(c.env.DB);
  const snap = await store.snapshot();
  return c.json(snap);
});

memory.get("/memory/:kind", async (c) => {
  const kind = c.req.param("kind");
  if (!isMemoryKind(kind)) return c.json({ error: "unknown kind" }, 400);
  const store = new MemoryStore(c.env.DB);
  return c.json(await store.list(kind));
});

memory.post("/memory/:kind", async (c) => {
  const kind = c.req.param("kind");
  if (!isMemoryKind(kind)) return c.json({ error: "unknown kind" }, 400);

  let body: Record<string, unknown>;
  try {
    body = await c.req.json();
  } catch {
    return c.json({ error: "invalid json" }, 400);
  }

  const store = new MemoryStore(c.env.DB);
  const bus = new EventBus(c.env.DB);
  try {
    const item = (await store.create(kind, body)) as { id: string };
    await bus.emit(`memory.${kind}.created`, "user", { id: item.id });
    return c.json(item, 201);
  } catch (err) {
    if (err instanceof ValidationError) return c.json({ error: err.message }, 400);
    throw err;
  }
});

memory.patch("/memory/:kind/:id", async (c) => {
  const kind = c.req.param("kind");
  if (!isMemoryKind(kind)) return c.json({ error: "unknown kind" }, 400);
  const id = c.req.param("id");

  let body: Record<string, unknown>;
  try {
    body = await c.req.json();
  } catch {
    return c.json({ error: "invalid json" }, 400);
  }

  const store = new MemoryStore(c.env.DB);
  const bus = new EventBus(c.env.DB);
  try {
    const item = await store.update(kind, id, body);
    if (!item) return c.json({ error: "not found" }, 404);
    await bus.emit(`memory.${kind}.updated`, "user", { id });
    return c.json(item);
  } catch (err) {
    if (err instanceof ValidationError) return c.json({ error: err.message }, 400);
    throw err;
  }
});

memory.delete("/memory/:kind/:id", async (c) => {
  const kind = c.req.param("kind");
  if (!isMemoryKind(kind)) return c.json({ error: "unknown kind" }, 400);
  const id = c.req.param("id");
  const store = new MemoryStore(c.env.DB);
  const bus = new EventBus(c.env.DB);
  const ok = await store.delete(kind, id);
  if (!ok) return c.json({ error: "not found" }, 404);
  await bus.emit(`memory.${kind}.deleted`, "user", { id });
  return c.body(null, 204);
});
