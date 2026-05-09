import { ApiClient, type JarvisEvent } from "./api";
import { loadSettings } from "./auth";

type EventHandler = (event: JarvisEvent) => void;

export class LiveBus {
  private ws: WebSocket | null = null;
  private handlers = new Set<EventHandler>();
  private reconnectTimer: number | null = null;
  private closed = false;

  constructor(private readonly client: ApiClient) {}

  on(handler: EventHandler): () => void {
    this.handlers.add(handler);
    return () => this.handlers.delete(handler);
  }

  start(): void {
    this.closed = false;
    this.connect();
  }

  stop(): void {
    this.closed = true;
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.ws?.close();
    this.ws = null;
  }

  private connect(): void {
    try {
      const ws = this.client.connectWebSocket();
      this.ws = ws;
      ws.addEventListener("message", (ev) => {
        try {
          const data = JSON.parse(ev.data as string) as
            | { type: "hello"; recent: JarvisEvent[] }
            | { type: "event"; event: JarvisEvent };
          if (data.type === "hello") {
            for (const e of data.recent) this.dispatch(e);
          } else if (data.type === "event") {
            this.dispatch(data.event);
          }
        } catch {
          // ignore malformed
        }
      });
      ws.addEventListener("close", () => {
        if (this.closed) return;
        this.scheduleReconnect();
      });
      ws.addEventListener("error", () => {
        ws.close();
      });
    } catch {
      this.scheduleReconnect();
    }
  }

  private scheduleReconnect(): void {
    if (this.closed || this.reconnectTimer !== null) return;
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, 2000);
  }

  private dispatch(e: JarvisEvent): void {
    for (const h of this.handlers) {
      try {
        h(e);
      } catch (err) {
        console.error("live handler", err);
      }
    }
  }
}

let shared: LiveBus | null = null;

export function getSharedLiveBus(): LiveBus | null {
  if (shared) return shared;
  const s = loadSettings();
  if (!s) return null;
  shared = new LiveBus(new ApiClient(s));
  shared.start();
  return shared;
}
