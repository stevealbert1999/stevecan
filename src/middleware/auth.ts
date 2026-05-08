import type { MiddlewareHandler } from "hono";
import type { Env } from "../env";

export const bearerAuth: MiddlewareHandler<{ Bindings: Env }> = async (c, next) => {
  const header = c.req.header("Authorization") ?? "";
  const expected = c.env.JARVIS_API_KEY;

  if (!expected) {
    return c.json({ error: "server misconfigured: JARVIS_API_KEY not set" }, 500);
  }

  const prefix = "Bearer ";
  if (!header.startsWith(prefix) || header.slice(prefix.length) !== expected) {
    return c.json({ error: "unauthorized" }, 401);
  }

  await next();
};
