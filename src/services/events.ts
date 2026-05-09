import type { JarvisEvent } from "../types";

export class EventBus {
  constructor(private readonly db: D1Database) {}

  async emit(
    kind: string,
    source: string,
    payload?: unknown,
  ): Promise<JarvisEvent> {
    const event: JarvisEvent = {
      id: crypto.randomUUID(),
      kind,
      source,
      payload: payload === undefined ? null : JSON.stringify(payload),
      created_at: Date.now(),
    };
    await this.db
      .prepare(
        "INSERT INTO events (id, kind, source, payload, created_at) VALUES (?, ?, ?, ?, ?)",
      )
      .bind(event.id, event.kind, event.source, event.payload, event.created_at)
      .run();
    return event;
  }

  async list(opts: { since?: number; kind?: string; limit?: number } = {}): Promise<JarvisEvent[]> {
    const limit = Math.min(opts.limit ?? 100, 500);
    const where: string[] = [];
    const params: unknown[] = [];
    if (opts.since !== undefined) {
      where.push("created_at >= ?");
      params.push(opts.since);
    }
    if (opts.kind) {
      where.push("kind = ?");
      params.push(opts.kind);
    }
    const whereSql = where.length ? `WHERE ${where.join(" AND ")}` : "";
    params.push(limit);
    const { results } = await this.db
      .prepare(
        `SELECT id, kind, source, payload, created_at FROM events ${whereSql} ORDER BY created_at DESC LIMIT ?`,
      )
      .bind(...params)
      .all<JarvisEvent>();
    return results ?? [];
  }
}
