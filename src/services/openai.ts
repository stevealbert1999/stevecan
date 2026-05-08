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
