import { env, fetchMock, SELF } from "cloudflare:test";
import { afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import schema1 from "../migrations/0001_init.sql?raw";
import schema2 from "../migrations/0002_memory.sql?raw";
import schema3 from "../migrations/0003_events_suggestions.sql?raw";

declare module "cloudflare:test" {
  interface ProvidedEnv {
    DB: D1Database;
    HUD_HUB: DurableObjectNamespace;
    JARVIS_API_KEY: string;
    OPENAI_API_KEY: string;
    JARVIS_MODEL: string;
    JARVIS_SYSTEM_PROMPT: string;
    JARVIS_VERSION: string;
    JARVIS_WEB_ORIGIN: string;
    JARVIS_BUTLER_ENABLED: string;
    JARVIS_BUTLER_MODEL: string;
  }
}

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

function mockOpenAI(reply: string, captureBody?: (b: unknown) => void) {
  fetchMock
    .get("https://api.openai.com")
    .intercept({ path: "/v1/chat/completions", method: "POST" })
    .reply(
      200,
      (opts) => {
        if (captureBody && typeof opts.body === "string") {
          captureBody(JSON.parse(opts.body));
        }
        return {
          choices: [{ message: { role: "assistant", content: reply } }],
        };
      },
      { headers: { "content-type": "application/json" } },
    );
}

function mockOpenAIStream(deltas: string[]) {
  const sseChunks: string[] = [];
  for (const d of deltas) {
    sseChunks.push(
      `data: ${JSON.stringify({ choices: [{ delta: { content: d } }] })}\n\n`,
    );
  }
  sseChunks.push("data: [DONE]\n\n");
  fetchMock
    .get("https://api.openai.com")
    .intercept({ path: "/v1/chat/completions", method: "POST" })
    .reply(200, sseChunks.join(""), {
      headers: { "content-type": "text/event-stream" },
    });
}

describe("health", () => {
  it("returns ok without auth", async () => {
    const res = await SELF.fetch("http://localhost/health");
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ ok: true, version: "test" });
  });
});

describe("auth", () => {
  it("rejects missing bearer", async () => {
    const res = await SELF.fetch("http://localhost/threads");
    expect(res.status).toBe(401);
  });

  it("rejects wrong bearer", async () => {
    const res = await SELF.fetch("http://localhost/threads", {
      headers: { Authorization: "Bearer wrong" },
    });
    expect(res.status).toBe(401);
  });
});

describe("chat", () => {
  it("creates a thread, persists user+assistant, returns reply", async () => {
    mockOpenAI("hello, I'm Jarvis");

    const res = await SELF.fetch("http://localhost/chat", {
      method: "POST",
      headers: { ...AUTH, "content-type": "application/json" },
      body: JSON.stringify({ message: "hi" }),
    });

    expect(res.status).toBe(200);
    const body = (await res.json()) as { thread_id: string; reply: string };
    expect(body.reply).toBe("hello, I'm Jarvis");
    expect(typeof body.thread_id).toBe("string");

    const got = await SELF.fetch(`http://localhost/threads/${body.thread_id}`, {
      headers: AUTH,
    });
    expect(got.status).toBe(200);
    const thread = (await got.json()) as {
      id: string;
      messages: Array<{ role: string; content: string }>;
    };
    expect(thread.messages.map((m) => [m.role, m.content])).toEqual([
      ["user", "hi"],
      ["assistant", "hello, I'm Jarvis"],
    ]);
  });

  it("rejects empty message", async () => {
    const res = await SELF.fetch("http://localhost/chat", {
      method: "POST",
      headers: { ...AUTH, "content-type": "application/json" },
      body: JSON.stringify({ message: "   " }),
    });
    expect(res.status).toBe(400);
  });

  it("404 when thread_id does not exist", async () => {
    const res = await SELF.fetch("http://localhost/chat", {
      method: "POST",
      headers: { ...AUTH, "content-type": "application/json" },
      body: JSON.stringify({ thread_id: "missing", message: "hi" }),
    });
    expect(res.status).toBe(404);
  });

  it("continues an existing thread (history grows)", async () => {
    mockOpenAI("first");
    const r1 = await SELF.fetch("http://localhost/chat", {
      method: "POST",
      headers: { ...AUTH, "content-type": "application/json" },
      body: JSON.stringify({ message: "one" }),
    });
    const { thread_id } = (await r1.json()) as { thread_id: string };

    mockOpenAI("second");
    const r2 = await SELF.fetch("http://localhost/chat", {
      method: "POST",
      headers: { ...AUTH, "content-type": "application/json" },
      body: JSON.stringify({ thread_id, message: "two" }),
    });
    expect(r2.status).toBe(200);

    const got = await SELF.fetch(`http://localhost/threads/${thread_id}`, {
      headers: AUTH,
    });
    const thread = (await got.json()) as {
      messages: Array<{ role: string; content: string }>;
    };
    expect(thread.messages.map((m) => m.content)).toEqual([
      "one",
      "first",
      "two",
      "second",
    ]);
  });

  it("injects memory snapshot into the system prompt", async () => {
    await env.DB.prepare(
      "INSERT INTO facts (id, content, created_at, updated_at) VALUES (?, ?, ?, ?)",
    )
      .bind("f1", "Alberte vive en Madrid", Date.now(), Date.now())
      .run();
    await env.DB.prepare(
      "INSERT INTO commitments (id, content, due_at, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
    )
      .bind("c1", "llamar al fontanero", null, "open", Date.now(), Date.now())
      .run();

    let captured: { messages: Array<{ role: string; content: string }> } | null = null;
    mockOpenAI("ok", (b) => {
      captured = b as typeof captured;
    });

    const res = await SELF.fetch("http://localhost/chat", {
      method: "POST",
      headers: { ...AUTH, "content-type": "application/json" },
      body: JSON.stringify({ message: "test" }),
    });
    expect(res.status).toBe(200);
    expect(captured).not.toBeNull();
    const sys = captured!.messages[0]!;
    expect(sys.role).toBe("system");
    expect(sys.content).toContain("Alberte vive en Madrid");
    expect(sys.content).toContain("llamar al fontanero");
  });
});

describe("chat streaming (SSE)", () => {
  it("streams deltas and persists the full reply", async () => {
    mockOpenAIStream(["Ho", "la,", " ¿qué tal?"]);

    const res = await SELF.fetch("http://localhost/chat", {
      method: "POST",
      headers: {
        ...AUTH,
        "content-type": "application/json",
        accept: "text/event-stream",
      },
      body: JSON.stringify({ message: "hola" }),
    });
    expect(res.status).toBe(200);
    expect(res.headers.get("content-type")).toContain("text/event-stream");

    const text = await res.text();
    expect(text).toContain('"delta":"Ho"');
    expect(text).toContain('"delta":"la,"');
    expect(text).toContain('"delta":" ¿qué tal?"');
    expect(text).toContain("event: done");

    const threadIdMatch = text.match(/"thread_id":"([^"]+)"/);
    expect(threadIdMatch).not.toBeNull();
    const tid = threadIdMatch![1]!;

    const got = await SELF.fetch(`http://localhost/threads/${tid}`, { headers: AUTH });
    const thread = (await got.json()) as {
      messages: Array<{ role: string; content: string }>;
    };
    expect(thread.messages.map((m) => [m.role, m.content])).toEqual([
      ["user", "hola"],
      ["assistant", "Hola, ¿qué tal?"],
    ]);
  });
});

describe("memory CRUD", () => {
  it("creates, reads, updates, deletes a fact", async () => {
    const created = await SELF.fetch("http://localhost/memory/facts", {
      method: "POST",
      headers: { ...AUTH, "content-type": "application/json" },
      body: JSON.stringify({ content: "Le gusta el café." }),
    });
    expect(created.status).toBe(201);
    const fact = (await created.json()) as { id: string; content: string };

    const list = await SELF.fetch("http://localhost/memory/facts", { headers: AUTH });
    expect(list.status).toBe(200);
    expect((await list.json()) as unknown[]).toHaveLength(1);

    const patched = await SELF.fetch(`http://localhost/memory/facts/${fact.id}`, {
      method: "PATCH",
      headers: { ...AUTH, "content-type": "application/json" },
      body: JSON.stringify({ content: "Prefiere té." }),
    });
    expect(patched.status).toBe(200);
    expect(((await patched.json()) as { content: string }).content).toBe("Prefiere té.");

    const del = await SELF.fetch(`http://localhost/memory/facts/${fact.id}`, {
      method: "DELETE",
      headers: AUTH,
    });
    expect(del.status).toBe(204);

    const after = await SELF.fetch("http://localhost/memory/facts", { headers: AUTH });
    expect((await after.json()) as unknown[]).toHaveLength(0);
  });

  it("rejects invalid kind", async () => {
    const r = await SELF.fetch("http://localhost/memory/bogus", {
      method: "POST",
      headers: { ...AUTH, "content-type": "application/json" },
      body: JSON.stringify({ content: "x" }),
    });
    expect(r.status).toBe(400);
  });

  it("validates required fields", async () => {
    const r = await SELF.fetch("http://localhost/memory/facts", {
      method: "POST",
      headers: { ...AUTH, "content-type": "application/json" },
      body: JSON.stringify({}),
    });
    expect(r.status).toBe(400);
  });

  it("validates enum on commitments status", async () => {
    const r = await SELF.fetch("http://localhost/memory/commitments", {
      method: "POST",
      headers: { ...AUTH, "content-type": "application/json" },
      body: JSON.stringify({ content: "x", status: "weird" }),
    });
    expect(r.status).toBe(400);
  });

  it("snapshot returns all five buckets", async () => {
    await SELF.fetch("http://localhost/memory/facts", {
      method: "POST",
      headers: { ...AUTH, "content-type": "application/json" },
      body: JSON.stringify({ content: "f" }),
    });
    await SELF.fetch("http://localhost/memory/preferences", {
      method: "POST",
      headers: { ...AUTH, "content-type": "application/json" },
      body: JSON.stringify({ content: "p", category: "food" }),
    });
    await SELF.fetch("http://localhost/memory/projects", {
      method: "POST",
      headers: { ...AUTH, "content-type": "application/json" },
      body: JSON.stringify({ name: "Jarvis OS" }),
    });

    const r = await SELF.fetch("http://localhost/memory", { headers: AUTH });
    const snap = (await r.json()) as Record<string, unknown[]>;
    expect(Object.keys(snap).sort()).toEqual([
      "commitments",
      "episodes",
      "facts",
      "preferences",
      "projects",
    ]);
    expect(snap.facts).toHaveLength(1);
    expect(snap.preferences).toHaveLength(1);
    expect(snap.projects).toHaveLength(1);
    expect(snap.commitments).toHaveLength(0);
    expect(snap.episodes).toHaveLength(0);
  });
});

describe("threads", () => {
  it("lists threads in updated_at desc", async () => {
    mockOpenAI("a");
    await SELF.fetch("http://localhost/chat", {
      method: "POST",
      headers: { ...AUTH, "content-type": "application/json" },
      body: JSON.stringify({ message: "first thread" }),
    });
    mockOpenAI("b");
    await SELF.fetch("http://localhost/chat", {
      method: "POST",
      headers: { ...AUTH, "content-type": "application/json" },
      body: JSON.stringify({ message: "second thread" }),
    });

    const res = await SELF.fetch("http://localhost/threads", { headers: AUTH });
    expect(res.status).toBe(200);
    const list = (await res.json()) as Array<{ title: string }>;
    expect(list.length).toBe(2);
  });

  it("deletes a thread", async () => {
    mockOpenAI("x");
    const r = await SELF.fetch("http://localhost/chat", {
      method: "POST",
      headers: { ...AUTH, "content-type": "application/json" },
      body: JSON.stringify({ message: "hello" }),
    });
    const { thread_id } = (await r.json()) as { thread_id: string };

    const del = await SELF.fetch(`http://localhost/threads/${thread_id}`, {
      method: "DELETE",
      headers: AUTH,
    });
    expect(del.status).toBe(204);

    const got = await SELF.fetch(`http://localhost/threads/${thread_id}`, {
      headers: AUTH,
    });
    expect(got.status).toBe(404);
  });
});

describe("CORS", () => {
  it("preflight responds 204 with allow headers", async () => {
    const res = await SELF.fetch("http://localhost/chat", {
      method: "OPTIONS",
      headers: {
        origin: "https://example.com",
        "access-control-request-method": "POST",
        "access-control-request-headers": "authorization, content-type",
      },
    });
    expect(res.status).toBe(204);
    expect(res.headers.get("access-control-allow-origin")).toBe("*");
    expect(res.headers.get("access-control-allow-methods")).toContain("POST");
  });
});

describe("events", () => {
  it("emits chat events on /chat", async () => {
    mockOpenAI("ok");
    await SELF.fetch("http://localhost/chat", {
      method: "POST",
      headers: { ...AUTH, "content-type": "application/json" },
      body: JSON.stringify({ message: "hola" }),
    });
    const r = await SELF.fetch("http://localhost/events?limit=10", { headers: AUTH });
    expect(r.status).toBe(200);
    const evts = (await r.json()) as Array<{ kind: string }>;
    const kinds = evts.map((e) => e.kind);
    expect(kinds).toContain("thread.created");
    expect(kinds).toContain("chat.message.user");
    expect(kinds).toContain("chat.message.assistant");
  });

  it("emits memory events on CRUD", async () => {
    const created = await SELF.fetch("http://localhost/memory/facts", {
      method: "POST",
      headers: { ...AUTH, "content-type": "application/json" },
      body: JSON.stringify({ content: "x" }),
    });
    const fact = (await created.json()) as { id: string };
    await SELF.fetch(`http://localhost/memory/facts/${fact.id}`, {
      method: "PATCH",
      headers: { ...AUTH, "content-type": "application/json" },
      body: JSON.stringify({ content: "y" }),
    });
    await SELF.fetch(`http://localhost/memory/facts/${fact.id}`, {
      method: "DELETE",
      headers: AUTH,
    });

    const r = await SELF.fetch("http://localhost/events?limit=10", { headers: AUTH });
    const kinds = ((await r.json()) as Array<{ kind: string }>).map((e) => e.kind);
    expect(kinds).toContain("memory.facts.created");
    expect(kinds).toContain("memory.facts.updated");
    expect(kinds).toContain("memory.facts.deleted");
  });

  it("filters by kind", async () => {
    mockOpenAI("a");
    await SELF.fetch("http://localhost/chat", {
      method: "POST",
      headers: { ...AUTH, "content-type": "application/json" },
      body: JSON.stringify({ message: "hi" }),
    });
    const r = await SELF.fetch(
      "http://localhost/events?kind=chat.message.user",
      { headers: AUTH },
    );
    const list = (await r.json()) as Array<{ kind: string }>;
    expect(list.length).toBeGreaterThanOrEqual(1);
    expect(list.every((e) => e.kind === "chat.message.user")).toBe(true);
  });
});
