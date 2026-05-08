import { Hono } from "hono";
import type { Env } from "./env";
import { bearerAuth } from "./middleware/auth";
import { chat } from "./routes/chat";
import { health } from "./routes/health";
import { threads } from "./routes/threads";

const app = new Hono<{ Bindings: Env }>();

app.route("/", health);

const protectedApp = new Hono<{ Bindings: Env }>();
protectedApp.use("*", bearerAuth);
protectedApp.route("/", chat);
protectedApp.route("/", threads);

app.route("/", protectedApp);

app.onError((err, c) => {
  console.error("unhandled", err);
  return c.json({ error: "internal", detail: err.message }, 500);
});

app.notFound((c) => c.json({ error: "not found" }, 404));

export default app;
