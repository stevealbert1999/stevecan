import type { Role } from "../types";

export interface ChatMessage {
  role: Role;
  content: string;
}

export interface ChatCompletionOpts {
  apiKey: string;
  model: string;
  messages: ChatMessage[];
  fetcher?: typeof fetch;
}

export async function chatCompletion(opts: ChatCompletionOpts): Promise<string> {
  const f = opts.fetcher ?? fetch;
  const res = await f("https://api.openai.com/v1/chat/completions", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      authorization: `Bearer ${opts.apiKey}`,
    },
    body: JSON.stringify({
      model: opts.model,
      messages: opts.messages,
      stream: false,
    }),
  });

  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`openai ${res.status}: ${text.slice(0, 500)}`);
  }

  const data = (await res.json()) as {
    choices?: Array<{ message?: { content?: string } }>;
  };
  const reply = data.choices?.[0]?.message?.content;
  if (typeof reply !== "string" || reply.length === 0) {
    throw new Error("openai: empty completion");
  }
  return reply;
}

export async function* chatCompletionStream(
  opts: ChatCompletionOpts,
): AsyncGenerator<string, void, unknown> {
  const f = opts.fetcher ?? fetch;
  const res = await f("https://api.openai.com/v1/chat/completions", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      authorization: `Bearer ${opts.apiKey}`,
      accept: "text/event-stream",
    },
    body: JSON.stringify({
      model: opts.model,
      messages: opts.messages,
      stream: true,
    }),
  });

  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`openai ${res.status}: ${text.slice(0, 500)}`);
  }
  if (!res.body) {
    throw new Error("openai: empty stream body");
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let nlIndex: number;
    while ((nlIndex = buffer.indexOf("\n")) !== -1) {
      const rawLine = buffer.slice(0, nlIndex).trim();
      buffer = buffer.slice(nlIndex + 1);
      if (!rawLine.startsWith("data:")) continue;
      const payload = rawLine.slice(5).trim();
      if (payload === "[DONE]") return;
      try {
        const obj = JSON.parse(payload) as {
          choices?: Array<{ delta?: { content?: string } }>;
        };
        const delta = obj.choices?.[0]?.delta?.content;
        if (typeof delta === "string" && delta.length > 0) yield delta;
      } catch {
        // ignore malformed chunks (keepalives, etc.)
      }
    }
  }
}
