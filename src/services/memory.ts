import type { Message, Role, Thread } from "../types";

function newId(): string {
  return crypto.randomUUID();
}

export class Memory {
  constructor(private readonly db: D1Database) {}

  async createThread(title: string | null = null): Promise<Thread> {
    const now = Date.now();
    const thread: Thread = {
      id: newId(),
      title,
      created_at: now,
      updated_at: now,
    };
    await this.db
      .prepare("INSERT INTO threads (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)")
      .bind(thread.id, thread.title, thread.created_at, thread.updated_at)
      .run();
    return thread;
  }

  async getThread(id: string): Promise<Thread | null> {
    const row = await this.db
      .prepare("SELECT id, title, created_at, updated_at FROM threads WHERE id = ?")
      .bind(id)
      .first<Thread>();
    return row ?? null;
  }

  async listThreads(limit = 50): Promise<Thread[]> {
    const { results } = await this.db
      .prepare(
        "SELECT id, title, created_at, updated_at FROM threads ORDER BY updated_at DESC LIMIT ?",
      )
      .bind(limit)
      .all<Thread>();
    return results ?? [];
  }

  async deleteThread(id: string): Promise<boolean> {
    const res = await this.db.prepare("DELETE FROM threads WHERE id = ?").bind(id).run();
    return (res.meta.changes ?? 0) > 0;
  }

  async appendMessage(threadId: string, role: Role, content: string): Promise<Message> {
    const msg: Message = {
      id: newId(),
      thread_id: threadId,
      role,
      content,
      created_at: Date.now(),
    };
    await this.db.batch([
      this.db
        .prepare(
          "INSERT INTO messages (id, thread_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
        )
        .bind(msg.id, msg.thread_id, msg.role, msg.content, msg.created_at),
      this.db
        .prepare("UPDATE threads SET updated_at = ? WHERE id = ?")
        .bind(msg.created_at, threadId),
    ]);
    return msg;
  }

  async listMessages(threadId: string): Promise<Message[]> {
    const { results } = await this.db
      .prepare(
        "SELECT id, thread_id, role, content, created_at FROM messages WHERE thread_id = ? ORDER BY created_at ASC, id ASC",
      )
      .bind(threadId)
      .all<Message>();
    return results ?? [];
  }
}
