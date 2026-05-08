import { env, fetchMock, SELF } from "cloudflare:test";
import { afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import schema from "../migrations/0001_init.sql?raw";

declare module "cloudflare:test" {
  interface ProvidedEnv {
    DB: D1Database;
    JARVIS_API_KEY: string;
    OPENAI_API_KEY: string;
    JARVIS_MODEL: string;
    JARVIS_SYSTEM_PROMPT: string;
    JARVIS_VERSION: string;
  }
}

const AUTH = { Authorization: "Bearer test-token" };

beforeAll(async () => {
  const statements = schema
    .split(";")
    .map((s: string) => s.trim())
    .filter(Boolean);
  for (const stmt of statements) {
    await env.DB.exec(stmt.replace(/\s+/g, " "));
  }
  fetchMock.activate();
  fetchMock.disableNetConnect();
});

beforeEach(async () => {
  await env.DB.exec("DELETE FROM messages");
  await env.DB.exec("DELETE FROM threads");
});

afterEach(() => {
  fetchMock.assertNoPendingInterceptors();
});

function mockOpenAI(reply: string) {
  fetchMock
    .get("https://api.openai.com")
    .intercept({ path: "/v1/chat/completions", method: "POST" })
    .reply(
      200,
      {
        choices: [{ message: { role: "assistant", content: reply } }],
      },
      { headers: { "content-type": "application/json" } },
    );
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
