import { env, fetchMock, SELF } from "cloudflare:test";
import { afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import schema1 from "../migrations/0001_init.sql?raw";
import schema2 from "../migrations/0002_memory.sql?raw";
import schema3 from "../migrations/0003_events_suggestions.sql?raw";

const AUTH = { Authorization: "Bearer test-token" };

async function applySchema(sql: string) {
  const statements = sql
    .split(";")
    .map((s: string) => s.trim())
    .filter(Boolean);
  for (const stmt of statements) {
    await env.DB.exec(stmt.replace(/\s+/g, " "));
  }
}

beforeAll(async () => {
  await applySchema(schema1);
  await applySchema(schema2);
  await applySchema(schema3);
  fetchMock.activate();
  fetchMock.disableNetConnect();
});

beforeEach(async () => {
  await env.DB.exec("DELETE FROM messages");
  await env.DB.exec("DELETE FROM threads");
  await env.DB.exec("DELETE FROM facts");
  await env.DB.exec("DELETE FROM preferences");
  await env.DB.exec("DELETE FROM commitments");
  await env.DB.exec("DELETE FROM projects");
  await env.DB.exec("DELETE FROM episodes");
  await env.DB.exec("DELETE FROM events");
  await env.DB.exec("DELETE FROM suggestions");
});

afterEach(() => {
  fetchMock.assertNoPendingInterceptors();
});

describe("/state", () => {
  it("returns memory snapshot, suggestion list and recent events", async () => {
    await SELF.fetch("http://localhost/memory/facts", {
      method: "POST",
      headers: { ...AUTH, "content-type": "application/json" },
      body: JSON.stringify({ content: "alberte loves ginger tea" }),
    });
    await SELF.fetch("http://localhost/suggestions", {
      method: "POST",
      headers: { ...AUTH, "content-type": "application/json" },
      body: JSON.stringify({ title: "buy milk", priority: 2 }),
    });

    const r = await SELF.fetch("http://localhost/state", { headers: AUTH });
    expect(r.status).toBe(200);
    const state = (await r.json()) as {
      version: string;
      butler_enabled: boolean;
      memory: { facts: unknown[] };
      threads_count: number;
      pending_suggestions: Array<{ title: string }>;
      recent_events: Array<{ kind: string }>;
      server_time: number;
    };
    expect(state.version).toBe("test");
    expect(state.butler_enabled).toBe(false);
    expect(state.memory.facts.length).toBe(1);
    expect(state.pending_suggestions.map((s) => s.title)).toContain("buy milk");
    expect(state.recent_events.length).toBeGreaterThanOrEqual(1);
    const kinds = state.recent_events.map((e) => e.kind);
    expect(kinds).toContain("memory.facts.created");
    expect(kinds).toContain("suggestion.created");
  });

  it("requires auth", async () => {
    const r = await SELF.fetch("http://localhost/state");
    expect(r.status).toBe(401);
  });
});

describe("/ws", () => {
  it("rejects non-websocket GET", async () => {
    const r = await SELF.fetch("http://localhost/ws", { headers: AUTH });
    expect(r.status).toBe(400);
  });

  it("accepts ?token= for auth", async () => {
    const r = await SELF.fetch("http://localhost/ws?token=test-token");
    expect(r.status).toBe(400); // not 401 — auth passed, but no upgrade
  });

  it("rejects bad token", async () => {
    const r = await SELF.fetch("http://localhost/ws?token=nope");
    expect(r.status).toBe(401);
  });

  it("upgrades to websocket and broadcasts events", async () => {
    const r = await SELF.fetch("http://localhost/ws?token=test-token", {
      headers: { Upgrade: "websocket" },
    });
    expect(r.status).toBe(101);
    const ws = r.webSocket!;
    expect(ws).toBeTruthy();
    ws.accept();

    const messages: string[] = [];
    const received = new Promise<void>((resolve) => {
      ws.addEventListener("message", (ev: MessageEvent) => {
        messages.push(ev.data as string);
        // First "hello", then the event from emit below.
        if (messages.length >= 2) resolve();
      });
    });

    // Trigger an event by creating a fact via the public API.
    await SELF.fetch("http://localhost/memory/facts", {
      method: "POST",
      headers: { ...AUTH, "content-type": "application/json" },
      body: JSON.stringify({ content: "live test" }),
    });

    await Promise.race([
      received,
      new Promise<void>((_, reject) =>
        setTimeout(() => reject(new Error("timeout waiting for ws msg")), 4000),
      ),
    ]);

    expect(messages.length).toBeGreaterThanOrEqual(2);
    const parsed = messages.map((m) => JSON.parse(m));
    expect(parsed[0].type).toBe("hello");
    const eventMsg = parsed.find((m) => m.type === "event");
    expect(eventMsg).toBeTruthy();
    expect(eventMsg.event.kind).toBe("memory.facts.created");

    // Wait for the close to propagate to the DO so isolated storage can pop.
    const closed = new Promise<void>((resolve) => {
      ws.addEventListener("close", () => resolve());
    });
    ws.close();
    await Promise.race([
      closed,
      new Promise<void>((resolve) => setTimeout(resolve, 200)),
    ]);
  });
});
