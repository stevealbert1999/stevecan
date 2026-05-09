import {
  createExecutionContext,
  env,
  fetchMock,
  SELF,
  waitOnExecutionContext,
} from "cloudflare:test";
import { afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import worker from "../src/index";
import schema1 from "../migrations/0001_init.sql?raw";
import schema2 from "../migrations/0002_memory.sql?raw";
import schema3 from "../migrations/0003_events_suggestions.sql?raw";
import { EventBus } from "../src/services/events";
import { runButler, SuggestionsStore } from "../src/services/suggestions";

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
  await env.DB.exec("DELETE FROM events");
  await env.DB.exec("DELETE FROM suggestions");
  env.JARVIS_BUTLER_ENABLED = "false";
});

afterEach(() => {
  fetchMock.assertNoPendingInterceptors();
});

function mockChatJson(reply: string) {
  fetchMock
    .get("https://api.openai.com")
    .intercept({ path: "/v1/chat/completions", method: "POST" })
    .reply(
      200,
      { choices: [{ message: { role: "assistant", content: reply } }] },
      { headers: { "content-type": "application/json" } },
    );
}

function mockButlerJson(payload: unknown) {
  fetchMock
    .get("https://api.openai.com")
    .intercept({ path: "/v1/chat/completions", method: "POST" })
    .reply(
      200,
      { choices: [{ message: { role: "assistant", content: JSON.stringify(payload) } }] },
      { headers: { "content-type": "application/json" } },
    );
}

describe("SuggestionsStore", () => {
  it("creates with clamped priority and emits suggestion.created", async () => {
    const bus = new EventBus(env.DB);
    const store = new SuggestionsStore(env.DB, bus);
    const sug = await store.create({ title: "Test", priority: 99, reason: "r" });
    expect(sug.priority).toBe(5);
    expect(sug.status).toBe("pending");

    const events = await bus.list({ kind: "suggestion.created" });
    expect(events.length).toBe(1);
  });

  it("updates status and emits event", async () => {
    const bus = new EventBus(env.DB);
    const store = new SuggestionsStore(env.DB, bus);
    const sug = await store.create({ title: "x" });
    const updated = await store.update(sug.id, { status: "accepted" });
    expect(updated?.status).toBe("accepted");
    const events = await bus.list({ kind: "suggestion.accepted" });
    expect(events.length).toBe(1);
  });

  it("rejects invalid status", async () => {
    const bus = new EventBus(env.DB);
    const store = new SuggestionsStore(env.DB, bus);
    const sug = await store.create({ title: "x" });
    await expect(
      // @ts-expect-error testing runtime guard
      store.update(sug.id, { status: "weird" }),
    ).rejects.toThrow();
  });
});

describe("runButler", () => {
  it("creates suggestions from a JSON object response", async () => {
    const bus = new EventBus(env.DB);
    const store = new SuggestionsStore(env.DB, bus);

    const fakeFetch: typeof fetch = async () =>
      new Response(
        JSON.stringify({
          choices: [
            {
              message: {
                content: JSON.stringify({
                  suggestions: [
                    {
                      title: "Llamar al fontanero",
                      reason: "el usuario lo dijo",
                      priority: 4,
                    },
                    {
                      title: "Reservar restaurante",
                      reason: "mencionó cena el sábado",
                      priority: 2,
                    },
                  ],
                }),
              },
            },
          ],
        }),
        { headers: { "content-type": "application/json" } },
      );

    const n = await runButler({
      apiKey: "sk-test",
      model: "gpt-4o-mini",
      hints: {
        thread_id: "t1",
        conversation: [
          { role: "user", content: "tengo que llamar al fontanero y reservar" },
          { role: "assistant", content: "anotado" },
        ],
      },
      store,
      fetcher: fakeFetch,
    });
    expect(n).toBe(2);

    const list = await store.list({ status: "pending" });
    expect(list.map((s) => s.title)).toEqual([
      "Llamar al fontanero",
      "Reservar restaurante",
    ]);
    expect(list.find((s) => s.title === "Llamar al fontanero")?.priority).toBe(4);
  });

  it("returns 0 on malformed JSON without throwing", async () => {
    const bus = new EventBus(env.DB);
    const store = new SuggestionsStore(env.DB, bus);
    const fakeFetch: typeof fetch = async () =>
      new Response(
        JSON.stringify({
          choices: [{ message: { content: "not json at all" } }],
        }),
        { headers: { "content-type": "application/json" } },
      );
    const n = await runButler({
      apiKey: "sk-test",
      model: "gpt-4o-mini",
      hints: { thread_id: "t1", conversation: [] },
      store,
      fetcher: fakeFetch,
    });
    expect(n).toBe(0);
  });

  it("ignores entries without a title", async () => {
    const bus = new EventBus(env.DB);
    const store = new SuggestionsStore(env.DB, bus);
    const fakeFetch: typeof fetch = async () =>
      new Response(
        JSON.stringify({
          choices: [
            {
              message: {
                content: JSON.stringify({
                  suggestions: [{ priority: 1 }, { title: "ok" }],
                }),
              },
            },
          ],
        }),
        { headers: { "content-type": "application/json" } },
      );
    const n = await runButler({
      apiKey: "sk-test",
      model: "gpt-4o-mini",
      hints: { thread_id: "t1", conversation: [] },
      store,
      fetcher: fakeFetch,
    });
    expect(n).toBe(1);
  });
});

describe("/suggestions endpoints", () => {
  it("creates, lists by status, accepts, deletes", async () => {
    const create = await SELF.fetch("http://localhost/suggestions", {
      method: "POST",
      headers: { ...AUTH, "content-type": "application/json" },
      body: JSON.stringify({ title: "test", priority: 4 }),
    });
    expect(create.status).toBe(201);
    const sug = (await create.json()) as { id: string };

    const pending = await SELF.fetch(
      "http://localhost/suggestions?status=pending",
      { headers: AUTH },
    );
    expect(((await pending.json()) as unknown[]).length).toBe(1);

    const accept = await SELF.fetch(`http://localhost/suggestions/${sug.id}`, {
      method: "PATCH",
      headers: { ...AUTH, "content-type": "application/json" },
      body: JSON.stringify({ status: "accepted" }),
    });
    expect(accept.status).toBe(200);
    expect(((await accept.json()) as { status: string }).status).toBe("accepted");

    const stillPending = await SELF.fetch(
      "http://localhost/suggestions?status=pending",
      { headers: AUTH },
    );
    expect(((await stillPending.json()) as unknown[]).length).toBe(0);

    const del = await SELF.fetch(`http://localhost/suggestions/${sug.id}`, {
      method: "DELETE",
      headers: AUTH,
    });
    expect(del.status).toBe(204);
  });

  it("rejects invalid status filter", async () => {
    const r = await SELF.fetch("http://localhost/suggestions?status=bogus", {
      headers: AUTH,
    });
    expect(r.status).toBe(400);
  });

  it("requires title on POST", async () => {
    const r = await SELF.fetch("http://localhost/suggestions", {
      method: "POST",
      headers: { ...AUTH, "content-type": "application/json" },
      body: JSON.stringify({}),
    });
    expect(r.status).toBe(400);
  });
});

describe("/chat → butler integration", () => {
  it("when butler enabled, suggestions are created after a chat", async () => {
    env.JARVIS_BUTLER_ENABLED = "true";

    mockChatJson("anotado");
    mockButlerJson({
      suggestions: [
        { title: "Llamar al fontanero", reason: "lo pidió", priority: 4 },
      ],
    });

    const ctx = createExecutionContext();
    const req = new Request("http://localhost/chat", {
      method: "POST",
      headers: { ...AUTH, "content-type": "application/json" },
      body: JSON.stringify({ message: "tengo que llamar al fontanero" }),
    });
    const res = await worker.fetch(req, env, ctx);
    expect(res.status).toBe(200);
    await waitOnExecutionContext(ctx);

    const list = await SELF.fetch(
      "http://localhost/suggestions?status=pending",
      { headers: AUTH },
    );
    const sugs = (await list.json()) as Array<{ title: string }>;
    expect(sugs.map((s) => s.title)).toEqual(["Llamar al fontanero"]);
  });

  it("when butler disabled, chat does not call OpenAI twice", async () => {
    env.JARVIS_BUTLER_ENABLED = "false";
    mockChatJson("ok");

    const ctx = createExecutionContext();
    const req = new Request("http://localhost/chat", {
      method: "POST",
      headers: { ...AUTH, "content-type": "application/json" },
      body: JSON.stringify({ message: "hola" }),
    });
    const res = await worker.fetch(req, env, ctx);
    expect(res.status).toBe(200);
    await waitOnExecutionContext(ctx);

    const list = await SELF.fetch(
      "http://localhost/suggestions?status=pending",
      { headers: AUTH },
    );
    expect(((await list.json()) as unknown[]).length).toBe(0);
  });
});
