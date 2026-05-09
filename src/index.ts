import { Hono } from "hono";
import type { Env } from "./env";
import { bearerAuth } from "./middleware/auth";
import { cors } from "./middleware/cors";
import { chat } from "./routes/chat";
import { events } from "./routes/events";
import { health } from "./routes/health";
import { memory } from "./routes/memory";
import { suggestions } from "./routes/suggestions";
import { threads } from "./routes/threads";

const app = new Hono<{ Bindings: Env }>();

app.use("*", cors);

app.route("/", health);

const protectedApp = new Hono<{ Bindings: Env }>();
protectedApp.use("*", bearerAuth);
protectedApp.route("/", chat);
protectedApp.route("/", threads);
protectedApp.route("/", memory);
protectedApp.route("/", events);
protectedApp.route("/", suggestions);

app.route("/", protectedApp);

app.onError((err, c) => {
  console.error("unhandled", err);
  return c.json({ error: "internal", detail: err.message }, 500);
});

app.notFound((c) => c.json({ error: "not found" }, 404));

export default app;
