import type { Env } from "../env";

interface Broadcast {
  kind: string;
  source: string;
  payload: unknown;
  created_at: number;
  id?: string;
}

export class HudHub {
  private sessions = new Set<WebSocket>();
  private recent: Broadcast[] = [];

  constructor(_state: DurableObjectState, _env: Env) {}

  async fetch(req: Request): Promise<Response> {
    const url = new URL(req.url);

    if (url.pathname === "/ws") {
      const upgrade = req.headers.get("upgrade")?.toLowerCase();
      if (upgrade !== "websocket") {
        return new Response("expected websocket", { status: 400 });
      }
      const pair = new WebSocketPair();
      const client = pair[0];
      const server = pair[1];
      this.accept(server);
      return new Response(null, { status: 101, webSocket: client });
    }

    if (url.pathname === "/broadcast" && req.method === "POST") {
      const body = (await req.json()) as Broadcast;
      this.broadcast(body);
      return new Response(null, { status: 204 });
    }

    if (url.pathname === "/recent" && req.method === "GET") {
      return Response.json({ events: this.recent, sessions: this.sessions.size });
    }

    return new Response("not found", { status: 404 });
  }

  private accept(ws: WebSocket): void {
    ws.accept();
    this.sessions.add(ws);
    try {
      ws.send(JSON.stringify({ type: "hello", recent: this.recent.slice(-20) }));
    } catch {
      // ignore
    }
    const drop = () => this.sessions.delete(ws);
    ws.addEventListener("close", drop);
    ws.addEventListener("error", drop);
  }

  private broadcast(event: Broadcast): void {
    this.recent.push(event);
    if (this.recent.length > 200) this.recent.splice(0, this.recent.length - 200);
    const msg = JSON.stringify({ type: "event", event });
    for (const ws of [...this.sessions]) {
      try {
        ws.send(msg);
      } catch {
        this.sessions.delete(ws);
      }
    }
  }
}
