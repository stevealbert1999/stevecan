import { Hono } from "hono";
import type { Env } from "../env";
import { Memory } from "../services/memory";
import { MemoryStore, renderMemoryContext } from "../services/memory_store";
import {
  chatCompletion,
  chatCompletionStream,
  type ChatMessage,
} from "../services/openai";

export const chat = new Hono<{ Bindings: Env }>();

interface ChatBody {
  thread_id?: string;
  message?: string;
}

function buildSystemPrompt(base: string, memoryContext: string): string {
  if (!memoryContext) return base;
  return `${base}\n\n${memoryContext}`;
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

  let thread = body.thread_id ? await memory.getThread(body.thread_id) : null;
  if (body.thread_id && !thread) {
    return c.json({ error: "thread not found" }, 404);
  }
  if (!thread) {
    thread = await memory.createThread(message.slice(0, 80));
  }

  await memory.appendMessage(thread.id, "user", message);
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

    (async () => {
      let acc = "";
      try {
        await send("thread", { thread_id: threadId });
        for await (const delta of chatCompletionStream({
          apiKey: c.env.OPENAI_API_KEY,
          model: c.env.JARVIS_MODEL,
          messages: llmMessages,
        })) {
          acc += delta;
          await send(null, { delta });
        }
        if (acc.length > 0) {
          await memory.appendMessage(threadId, "assistant", acc);
        }
        await send("done", { thread_id: threadId, reply: acc });
      } catch (err) {
        await send("error", {
          message: err instanceof Error ? err.message : String(err),
        });
      } finally {
        await writer.close();
      }
    })();

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

  return c.json({ thread_id: thread.id, reply });
});
