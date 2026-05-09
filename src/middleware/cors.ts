import type { MiddlewareHandler } from "hono";
import type { Env } from "../env";

export const cors: MiddlewareHandler<{ Bindings: Env }> = async (c, next) => {
  const origin = c.req.header("origin");
  const allowed = (c.env.JARVIS_WEB_ORIGIN ?? "*")
    .split(",")
    .map((o) => o.trim())
    .filter(Boolean);

  let allowOrigin = "";
  if (allowed.includes("*")) {
    allowOrigin = "*";
  } else if (origin && allowed.includes(origin)) {
    allowOrigin = origin;
  }

  if (c.req.method === "OPTIONS") {
    if (!allowOrigin) return c.body(null, 403);
    return new Response(null, {
      status: 204,
      headers: {
        "access-control-allow-origin": allowOrigin,
        "access-control-allow-methods": "GET, POST, PATCH, DELETE, OPTIONS",
        "access-control-allow-headers":
          c.req.header("access-control-request-headers") ??
          "authorization, content-type, accept",
        "access-control-max-age": "86400",
        vary: "Origin",
      },
    });
  }

  await next();

  // 101 Switching Protocols (WebSocket upgrade) responses have immutable
  // headers and don't need CORS headers anyway.
  if (allowOrigin && c.res.status !== 101) {
    c.res.headers.set("access-control-allow-origin", allowOrigin);
    c.res.headers.append("vary", "Origin");
  }
};
