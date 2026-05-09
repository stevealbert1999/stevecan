import { Hono } from "hono";
import type { Env } from "../env";
import { EventBus } from "../services/events";
import { Memory } from "../services/memory";

export const threads = new Hono<{ Bindings: Env }>();

threads.get("/threads", async (c) => {
  const memory = new Memory(c.env.DB);
  const list = await memory.listThreads();
  return c.json(list);
});

threads.get("/threads/:id", async (c) => {
  const memory = new Memory(c.env.DB);
  const id = c.req.param("id");
  const thread = await memory.getThread(id);
  if (!thread) return c.json({ error: "not found" }, 404);
  const messages = await memory.listMessages(id);
  return c.json({ ...thread, messages });
});

threads.delete("/threads/:id", async (c) => {
  const memory = new Memory(c.env.DB);
  const bus = new EventBus(c.env.DB);
  const id = c.req.param("id");
  const ok = await memory.deleteThread(id);
  if (!ok) return c.json({ error: "not found" }, 404);
  await bus.emit("thread.deleted", "user", { id });
  return c.body(null, 204);
});
