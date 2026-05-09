import type { Settings } from "./types";

export interface MemoryItem {
  id: string;
  created_at: number;
  updated_at: number;
  [k: string]: unknown;
}

export type MemoryKind =
  | "facts"
  | "preferences"
  | "commitments"
  | "projects"
  | "episodes";

export interface MemorySnapshot {
  facts: MemoryItem[];
  preferences: MemoryItem[];
  commitments: MemoryItem[];
  projects: MemoryItem[];
  episodes: MemoryItem[];
}

export interface ThreadMeta {
  id: string;
  title: string | null;
  created_at: number;
  updated_at: number;
}

export interface ThreadDetail extends ThreadMeta {
  messages: Array<{
    id: string;
    role: "system" | "user" | "assistant";
    content: string;
    created_at: number;
  }>;
}

export type SuggestionStatus = "pending" | "accepted" | "dismissed";

export interface Suggestion {
  id: string;
  title: string;
  reason: string | null;
  priority: number;
  status: SuggestionStatus;
  action_payload: string | null;
  thread_id: string | null;
  created_at: number;
  updated_at: number;
}

export interface JarvisEvent {
  id: string;
  kind: string;
  source: string;
  payload: string | null;
  created_at: number;
}

export class ApiClient {
  constructor(private readonly settings: Settings) {}

  private url(path: string): string {
    return this.settings.apiUrl.replace(/\/$/, "") + path;
  }

  private headers(extra: Record<string, string> = {}): HeadersInit {
    return {
      authorization: `Bearer ${this.settings.apiKey}`,
      "content-type": "application/json",
      ...extra,
    };
  }

  async listThreads(): Promise<ThreadMeta[]> {
    const r = await fetch(this.url("/threads"), { headers: this.headers() });
    if (!r.ok) throw new Error(`listThreads ${r.status}`);
    return (await r.json()) as ThreadMeta[];
  }

  async getThread(id: string): Promise<ThreadDetail> {
    const r = await fetch(this.url(`/threads/${id}`), { headers: this.headers() });
    if (!r.ok) throw new Error(`getThread ${r.status}`);
    return (await r.json()) as ThreadDetail;
  }

  async deleteThread(id: string): Promise<void> {
    const r = await fetch(this.url(`/threads/${id}`), {
      method: "DELETE",
      headers: this.headers(),
    });
    if (!r.ok && r.status !== 204) throw new Error(`deleteThread ${r.status}`);
  }

  async getMemory(): Promise<MemorySnapshot> {
    const r = await fetch(this.url("/memory"), { headers: this.headers() });
    if (!r.ok) throw new Error(`getMemory ${r.status}`);
    return (await r.json()) as MemorySnapshot;
  }

  async createMemory(kind: MemoryKind, body: Record<string, unknown>): Promise<MemoryItem> {
    const r = await fetch(this.url(`/memory/${kind}`), {
      method: "POST",
      headers: this.headers(),
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error(`createMemory ${r.status}: ${await r.text()}`);
    return (await r.json()) as MemoryItem;
  }

  async updateMemory(
    kind: MemoryKind,
    id: string,
    patch: Record<string, unknown>,
  ): Promise<MemoryItem> {
    const r = await fetch(this.url(`/memory/${kind}/${id}`), {
      method: "PATCH",
      headers: this.headers(),
      body: JSON.stringify(patch),
    });
    if (!r.ok) throw new Error(`updateMemory ${r.status}`);
    return (await r.json()) as MemoryItem;
  }

  async deleteMemory(kind: MemoryKind, id: string): Promise<void> {
    const r = await fetch(this.url(`/memory/${kind}/${id}`), {
      method: "DELETE",
      headers: this.headers(),
    });
    if (!r.ok && r.status !== 204) throw new Error(`deleteMemory ${r.status}`);
  }

  async listSuggestions(status?: SuggestionStatus): Promise<Suggestion[]> {
    const path = status ? `/suggestions?status=${status}` : "/suggestions";
    const r = await fetch(this.url(path), { headers: this.headers() });
    if (!r.ok) throw new Error(`listSuggestions ${r.status}`);
    return (await r.json()) as Suggestion[];
  }

  async updateSuggestion(
    id: string,
    patch: Partial<Pick<Suggestion, "status" | "priority" | "title" | "reason">>,
  ): Promise<Suggestion> {
    const r = await fetch(this.url(`/suggestions/${id}`), {
      method: "PATCH",
      headers: this.headers(),
      body: JSON.stringify(patch),
    });
    if (!r.ok) throw new Error(`updateSuggestion ${r.status}`);
    return (await r.json()) as Suggestion;
  }

  async deleteSuggestion(id: string): Promise<void> {
    const r = await fetch(this.url(`/suggestions/${id}`), {
      method: "DELETE",
      headers: this.headers(),
    });
    if (!r.ok && r.status !== 204) throw new Error(`deleteSuggestion ${r.status}`);
  }

  async listEvents(opts: { kind?: string; since?: number; limit?: number } = {}): Promise<JarvisEvent[]> {
    const params = new URLSearchParams();
    if (opts.kind) params.set("kind", opts.kind);
    if (opts.since !== undefined) params.set("since", String(opts.since));
    if (opts.limit !== undefined) params.set("limit", String(opts.limit));
    const qs = params.toString();
    const r = await fetch(this.url(`/events${qs ? `?${qs}` : ""}`), {
      headers: this.headers(),
    });
    if (!r.ok) throw new Error(`listEvents ${r.status}`);
    return (await r.json()) as JarvisEvent[];
  }

  async chatStream(
    args: { thread_id?: string; message: string },
    onEvent: (e: StreamEvent) => void,
  ): Promise<void> {
    const r = await fetch(this.url("/chat"), {
      method: "POST",
      headers: this.headers({ accept: "text/event-stream" }),
      body: JSON.stringify(args),
    });
    if (!r.ok || !r.body) {
      const text = await r.text().catch(() => "");
      throw new Error(`chat ${r.status}: ${text.slice(0, 300)}`);
    }
    const reader = r.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let sep: number;
      while ((sep = buffer.indexOf("\n\n")) !== -1) {
        const block = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        const evt = parseSseBlock(block);
        if (evt) onEvent(evt);
      }
    }
  }
}

export type StreamEvent =
  | { type: "thread"; thread_id: string }
  | { type: "delta"; delta: string }
  | { type: "done"; thread_id: string; reply: string }
  | { type: "error"; message: string };

function parseSseBlock(block: string): StreamEvent | null {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (dataLines.length === 0) return null;
  let payload: Record<string, unknown>;
  try {
    payload = JSON.parse(dataLines.join("\n"));
  } catch {
    return null;
  }
  if (event === "thread" && typeof payload.thread_id === "string") {
    return { type: "thread", thread_id: payload.thread_id };
  }
  if (event === "done" && typeof payload.thread_id === "string") {
    return {
      type: "done",
      thread_id: payload.thread_id,
      reply: typeof payload.reply === "string" ? payload.reply : "",
    };
  }
  if (event === "error" && typeof payload.message === "string") {
    return { type: "error", message: payload.message };
  }
  if (event === "message" && typeof payload.delta === "string") {
    return { type: "delta", delta: payload.delta };
  }
  return null;
}
