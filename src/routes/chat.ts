import { Hono } from "hono";
import type { Env } from "../env";
import { Memory } from "../services/memory";
import { chatCompletion, type ChatMessage } from "../services/openai";

export const chat = new Hono<{ Bindings: Env }>();

interface ChatBody {
  thread_id?: string;
  message?: string;
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

  let thread = body.thread_id ? await memory.getThread(body.thread_id) : null;
  if (body.thread_id && !thread) {
    return c.json({ error: "thread not found" }, 404);
  }
  if (!thread) {
    thread = await memory.createThread(message.slice(0, 80));
  }

  await memory.appendMessage(thread.id, "user", message);
  const history = await memory.listMessages(thread.id);

  const llmMessages: ChatMessage[] = [
    { role: "system", content: c.env.JARVIS_SYSTEM_PROMPT },
    ...history.map((m) => ({ role: m.role, content: m.content })),
  ];

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
