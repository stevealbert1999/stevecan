import { Hono } from "hono";
import type { Env } from "../env";
import { EventBus } from "../services/events";
import { Memory } from "../services/memory";
import { MemoryStore, renderMemoryContext } from "../services/memory_store";
import {
  chatCompletion,
  chatCompletionStream,
  type ChatMessage,
} from "../services/openai";
import { runButler, SuggestionsStore } from "../services/suggestions";

export const chat = new Hono<{ Bindings: Env }>();

interface ChatBody {
  thread_id?: string;
  message?: string;
}

function buildSystemPrompt(base: string, memoryContext: string): string {
  if (!memoryContext) return base;
  return `${base}\n\n${memoryContext}`;
}

async function maybeRunButler(
  env: Env,
  threadId: string,
  userMessage: string,
  assistantReply: string,
): Promise<void> {
  if (env.JARVIS_BUTLER_ENABLED !== "true") return;
  if (!assistantReply.trim()) return;

  const bus = new EventBus(env.DB, env.HUD_HUB);
  const store = new SuggestionsStore(env.DB, bus);
  try {
    await runButler({
      apiKey: env.OPENAI_API_KEY,
      model: env.JARVIS_BUTLER_MODEL ?? env.JARVIS_MODEL,
      hints: {
        thread_id: threadId,
        conversation: [
          { role: "user", content: userMessage },
          { role: "assistant", content: assistantReply },
        ],
      },
      store,
    });
  } catch (err) {
    console.error("butler failed", err);
  }
}

chat.post("/chat", async (c) => {
  let body: ChatBody;
  try {
    body = await c.req.json<ChatBody>();
  } catch {
    return c.json({ error: "invalid json" }, 400);
  }

  const message = body.message?.trim();
  if (!message) {
    return c.json({ error: "message is required" }, 400);
  }

  const memory = new Memory(c.env.DB);
  const store = new MemoryStore(c.env.DB);
  const bus = new EventBus(c.env.DB, c.env.HUD_HUB);

  let thread = body.thread_id ? await memory.getThread(body.thread_id) : null;
  if (body.thread_id && !thread) {
    return c.json({ error: "thread not found" }, 404);
  }
  const isNewThread = !thread;
  if (!thread) {
    thread = await memory.createThread(message.slice(0, 80));
    await bus.emit("thread.created", "user", { id: thread.id });
  }

  await memory.appendMessage(thread.id, "user", message);
  await bus.emit("chat.message.user", "user", {
    thread_id: thread.id,
    new_thread: isNewThread,
  });

  const history = await memory.listMessages(thread.id);
  const snapshot = await store.snapshot();
  const systemPrompt = buildSystemPrompt(
    c.env.JARVIS_SYSTEM_PROMPT,
    renderMemoryContext(snapshot),
  );

  const llmMessages: ChatMessage[] = [
    { role: "system", content: systemPrompt },
    ...history.map((m) => ({ role: m.role, content: m.content })),
  ];

  const wantsStream = c.req.header("accept")?.includes("text/event-stream");

  if (wantsStream) {
    const threadId = thread.id;
    const env = c.env;
    const userMessage = message;
    const { readable, writable } = new TransformStream<Uint8Array, Uint8Array>();
    const writer = writable.getWriter();
    const encoder = new TextEncoder();

    const send = async (event: string | null, data: unknown) => {
      const lines: string[] = [];
      if (event) lines.push(`event: ${event}`);
      lines.push(`data: ${JSON.stringify(data)}`);
      lines.push("", "");
      await writer.write(encoder.encode(lines.join("\n")));
    };

    const work = async () => {
      let acc = "";
      try {
        await send("thread", { thread_id: threadId });
        for await (const delta of chatCompletionStream({
          apiKey: env.OPENAI_API_KEY,
          model: env.JARVIS_MODEL,
          messages: llmMessages,
        })) {
          acc += delta;
          await send(null, { delta });
        }
        if (acc.length > 0) {
          await memory.appendMessage(threadId, "assistant", acc);
          await bus.emit("chat.message.assistant", "agent", {
            thread_id: threadId,
            length: acc.length,
          });
        }
        await send("done", { thread_id: threadId, reply: acc });
      } catch (err) {
        await send("error", {
          message: err instanceof Error ? err.message : String(err),
        });
      } finally {
        await writer.close();
      }
      if (acc.length > 0) {
        await maybeRunButler(env, threadId, userMessage, acc);
      }
    };

    c.executionCtx.waitUntil(work());

    return new Response(readable, {
      headers: {
        "content-type": "text/event-stream; charset=utf-8",
        "cache-control": "no-cache, no-transform",
        connection: "keep-alive",
        "x-accel-buffering": "no",
      },
    });
  }

  let reply: string;
  try {
    reply = await chatCompletion({
      apiKey: c.env.OPENAI_API_KEY,
      model: c.env.JARVIS_MODEL,
      messages: llmMessages,
    });
  } catch (err) {
    return c.json(
      { error: "llm failed", detail: err instanceof Error ? err.message : String(err) },
      502,
    );
  }

  await memory.appendMessage(thread.id, "assistant", reply);
  await bus.emit("chat.message.assistant", "agent", {
    thread_id: thread.id,
    length: reply.length,
  });

  c.executionCtx.waitUntil(maybeRunButler(c.env, thread.id, message, reply));

  return c.json({ thread_id: thread.id, reply });
});
