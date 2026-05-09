import type { MiddlewareHandler } from "hono";
import type { Env } from "../env";

export const bearerAuth: MiddlewareHandler<{ Bindings: Env }> = async (c, next) => {
  const header = c.req.header("Authorization") ?? "";
  const expected = c.env.JARVIS_API_KEY;

  if (!expected) {
    return c.json({ error: "server misconfigured: JARVIS_API_KEY not set" }, 500);
  }

  const prefix = "Bearer ";
  let provided = "";
  if (header.startsWith(prefix)) {
    provided = header.slice(prefix.length);
  } else {
    // WebSocket clients can't set custom headers; allow ?token=
    const token = c.req.query("token");
    if (token) provided = token;
  }

  if (provided !== expected) {
    return c.json({ error: "unauthorized" }, 401);
  }

  await next();
};
