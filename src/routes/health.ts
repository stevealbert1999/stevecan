import { Hono } from "hono";
import type { Env } from "../env";

export const health = new Hono<{ Bindings: Env }>();

health.get("/health", (c) =>
  c.json({ ok: true, version: c.env.JARVIS_VERSION ?? "0.0.0" }),
);
