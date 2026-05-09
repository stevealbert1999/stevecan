import { Hono } from "hono";
import type { Env } from "../env";

export const ws = new Hono<{ Bindings: Env }>();

ws.get("/ws", async (c) => {
  if (c.req.header("upgrade")?.toLowerCase() !== "websocket") {
    return c.json({ error: "expected websocket" }, 400);
  }
  const id = c.env.HUD_HUB.idFromName("default");
  const stub = c.env.HUD_HUB.get(id);
  try {
    return await stub.fetch(c.req.raw.clone());
  } catch (err) {
    console.error("ws forward failed", err);
    return c.json({ error: "ws forward failed", detail: err instanceof Error ? err.message : String(err) }, 500);
  }
});
