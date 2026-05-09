import { Hono } from "hono";
import type { Env } from "../env";
import { Memory } from "../services/memory";
import { MemoryStore } from "../services/memory_store";
import { EventBus } from "../services/events";
import { SuggestionsStore } from "../services/suggestions";

export const state = new Hono<{ Bindings: Env }>();

state.get("/state", async (c) => {
  const memory = new Memory(c.env.DB);
  const memStore = new MemoryStore(c.env.DB);
  const bus = new EventBus(c.env.DB, c.env.HUD_HUB);
  const sugStore = new SuggestionsStore(c.env.DB, bus);

  const [snapshot, threads, suggestions, recentEvents] = await Promise.all([
    memStore.snapshot(),
    memory.listThreads(),
    sugStore.list({ status: "pending" }),
    bus.list({ limit: 30 }),
  ]);

  return c.json({
    version: c.env.JARVIS_VERSION,
    butler_enabled: c.env.JARVIS_BUTLER_ENABLED === "true",
    memory: snapshot,
    threads_count: threads.length,
    pending_suggestions: suggestions,
    recent_events: recentEvents,
    server_time: Date.now(),
  });
});
