import type { Suggestion, SuggestionStatus } from "../types";
import { EventBus } from "./events";

interface ButlerHints {
  thread_id: string;
  conversation: Array<{ role: "user" | "assistant"; content: string }>;
}

interface ButlerProposal {
  title: string;
  reason?: string;
  priority?: number;
  action_payload?: unknown;
}

const BUTLER_SYSTEM_PROMPT = `Eres "Butler", un agente que escucha la conversación entre el usuario y Jarvis y detecta acciones concretas que el usuario podría querer ejecutar pronto: compromisos, recordatorios, llamadas, reservas, recados o seguimientos.

Devuelve SIEMPRE un objeto JSON estricto con la forma:
{"suggestions":[{"title":"...","reason":"...","priority":1-5,"action_payload":{...opcional}}]}

Reglas:
- Si no detectas ninguna acción accionable concreta, devuelve {"suggestions":[]}.
- Cada title debe ser una frase imperativa corta (máx 8 palabras). Ej: "Llamar al fontanero".
- reason explica de qué frase de la conversación se deduce.
- priority: 1=baja, 3=media, 5=alta. Por defecto 3.
- No inventes información que no aparezca explícita en la conversación.`;

export class SuggestionsStore {
  constructor(private readonly db: D1Database, private readonly bus: EventBus) {}

  async list(opts: { status?: SuggestionStatus } = {}): Promise<Suggestion[]> {
    if (opts.status) {
      const { results } = await this.db
        .prepare(
          "SELECT id, title, reason, priority, status, action_payload, thread_id, created_at, updated_at FROM suggestions WHERE status = ? ORDER BY priority DESC, updated_at DESC",
        )
        .bind(opts.status)
        .all<Suggestion>();
      return results ?? [];
    }
    const { results } = await this.db
      .prepare(
        "SELECT id, title, reason, priority, status, action_payload, thread_id, created_at, updated_at FROM suggestions ORDER BY status ASC, priority DESC, updated_at DESC",
      )
      .all<Suggestion>();
    return results ?? [];
  }

  async create(input: {
    title: string;
    reason?: string | null;
    priority?: number;
    action_payload?: unknown;
    thread_id?: string | null;
  }): Promise<Suggestion> {
    const now = Date.now();
    const id = crypto.randomUUID();
    const priority = clampPriority(input.priority);
    const sug: Suggestion = {
      id,
      title: input.title,
      reason: input.reason ?? null,
      priority,
      status: "pending",
      action_payload:
        input.action_payload === undefined || input.action_payload === null
          ? null
          : JSON.stringify(input.action_payload),
      thread_id: input.thread_id ?? null,
      created_at: now,
      updated_at: now,
    };
    await this.db
      .prepare(
        "INSERT INTO suggestions (id, title, reason, priority, status, action_payload, thread_id, created_at, updated_at) VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?)",
      )
      .bind(
        sug.id,
        sug.title,
        sug.reason,
        sug.priority,
        sug.action_payload,
        sug.thread_id,
        sug.created_at,
        sug.updated_at,
      )
      .run();
    await this.bus.emit("suggestion.created", "butler", {
      id: sug.id,
      title: sug.title,
      priority: sug.priority,
      thread_id: sug.thread_id,
    });
    return sug;
  }

  async update(
    id: string,
    patch: Partial<Pick<Suggestion, "status" | "priority" | "title" | "reason">>,
  ): Promise<Suggestion | null> {
    const sets: string[] = [];
    const params: unknown[] = [];
    if (patch.status) {
      if (!["pending", "accepted", "dismissed"].includes(patch.status)) {
        throw new Error("invalid status");
      }
      sets.push("status = ?");
      params.push(patch.status);
    }
    if (patch.priority !== undefined) {
      sets.push("priority = ?");
      params.push(clampPriority(patch.priority));
    }
    if (patch.title !== undefined) {
      sets.push("title = ?");
      params.push(patch.title);
    }
    if (patch.reason !== undefined) {
      sets.push("reason = ?");
      params.push(patch.reason);
    }
    if (sets.length === 0) return this.get(id);
    sets.push("updated_at = ?");
    params.push(Date.now());
    params.push(id);
    const res = await this.db
      .prepare(`UPDATE suggestions SET ${sets.join(", ")} WHERE id = ?`)
      .bind(...params)
      .run();
    if ((res.meta.changes ?? 0) === 0) return null;
    const sug = await this.get(id);
    if (sug && patch.status) {
      await this.bus.emit(`suggestion.${patch.status}`, "user", { id: sug.id });
    }
    return sug;
  }

  async get(id: string): Promise<Suggestion | null> {
    const row = await this.db
      .prepare(
        "SELECT id, title, reason, priority, status, action_payload, thread_id, created_at, updated_at FROM suggestions WHERE id = ?",
      )
      .bind(id)
      .first<Suggestion>();
    return row ?? null;
  }

  async delete(id: string): Promise<boolean> {
    const res = await this.db
      .prepare("DELETE FROM suggestions WHERE id = ?")
      .bind(id)
      .run();
    return (res.meta.changes ?? 0) > 0;
  }
}

function clampPriority(p: number | undefined): number {
  if (typeof p !== "number" || !Number.isFinite(p)) return 3;
  return Math.max(1, Math.min(5, Math.round(p)));
}

interface RunButlerOpts {
  apiKey: string;
  model: string;
  hints: ButlerHints;
  store: SuggestionsStore;
  fetcher?: typeof fetch;
}

export async function runButler(opts: RunButlerOpts): Promise<number> {
  const f = opts.fetcher ?? fetch;
  const lastFew = opts.hints.conversation.slice(-6);
  const userMessages = [
    {
      role: "system" as const,
      content: BUTLER_SYSTEM_PROMPT,
    },
    {
      role: "user" as const,
      content:
        "Conversación:\n\n" +
        lastFew.map((m) => `${m.role.toUpperCase()}: ${m.content}`).join("\n\n"),
    },
  ];

  const res = await f("https://api.openai.com/v1/chat/completions", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      authorization: `Bearer ${opts.apiKey}`,
    },
    body: JSON.stringify({
      model: opts.model,
      messages: userMessages,
      response_format: { type: "json_object" },
      temperature: 0.2,
    }),
  });

  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`butler openai ${res.status}: ${text.slice(0, 300)}`);
  }

  const data = (await res.json()) as {
    choices?: Array<{ message?: { content?: string } }>;
  };
  const raw = data.choices?.[0]?.message?.content ?? "";

  let parsed: { suggestions?: ButlerProposal[] };
  try {
    parsed = JSON.parse(raw);
  } catch {
    return 0;
  }

  const proposals = Array.isArray(parsed.suggestions) ? parsed.suggestions : [];
  let count = 0;
  for (const p of proposals) {
    if (!p || typeof p.title !== "string" || p.title.trim() === "") continue;
    await opts.store.create({
      title: p.title.trim().slice(0, 160),
      reason: typeof p.reason === "string" ? p.reason.slice(0, 600) : null,
      priority: typeof p.priority === "number" ? p.priority : undefined,
      action_payload: p.action_payload,
      thread_id: opts.hints.thread_id,
    });
    count++;
  }
  return count;
}
