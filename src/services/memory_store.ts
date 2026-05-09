import type {
  Commitment,
  CommitmentStatus,
  Episode,
  Fact,
  MemoryKind,
  MemorySnapshot,
  Preference,
  Project,
  ProjectStatus,
} from "../types";
import { MEMORY_KINDS } from "../types";

function newId(): string {
  return crypto.randomUUID();
}

export function isMemoryKind(value: string): value is MemoryKind {
  return (MEMORY_KINDS as readonly string[]).includes(value);
}

interface ColumnSpec {
  name: string;
  type: "string" | "number" | "stringNullable" | "numberNullable";
  enum?: readonly string[];
  default?: string | number;
}

interface KindSpec {
  table: string;
  orderBy: string;
  columns: ColumnSpec[];
}

const SPECS: Record<MemoryKind, KindSpec> = {
  facts: {
    table: "facts",
    orderBy: "updated_at DESC",
    columns: [{ name: "content", type: "string" }],
  },
  preferences: {
    table: "preferences",
    orderBy: "updated_at DESC",
    columns: [
      { name: "category", type: "stringNullable" },
      { name: "content", type: "string" },
    ],
  },
  commitments: {
    table: "commitments",
    orderBy: "status ASC, due_at ASC, updated_at DESC",
    columns: [
      { name: "content", type: "string" },
      { name: "due_at", type: "numberNullable" },
      {
        name: "status",
        type: "string",
        enum: ["open", "done", "cancelled"],
        default: "open",
      },
    ],
  },
  projects: {
    table: "projects",
    orderBy: "status ASC, updated_at DESC",
    columns: [
      { name: "name", type: "string" },
      { name: "description", type: "stringNullable" },
      {
        name: "status",
        type: "string",
        enum: ["active", "paused", "done", "archived"],
        default: "active",
      },
    ],
  },
  episodes: {
    table: "episodes",
    orderBy: "occurred_at DESC, updated_at DESC",
    columns: [
      { name: "title", type: "stringNullable" },
      { name: "summary", type: "string" },
      { name: "occurred_at", type: "numberNullable" },
    ],
  },
};

function coerce(spec: ColumnSpec, raw: unknown): unknown {
  if (raw === undefined) {
    if (spec.default !== undefined) return spec.default;
    if (spec.type === "stringNullable" || spec.type === "numberNullable") {
      return null;
    }
    throw new ValidationError(`field "${spec.name}" is required`);
  }
  if (raw === null) {
    if (spec.type === "stringNullable" || spec.type === "numberNullable") {
      return null;
    }
    throw new ValidationError(`field "${spec.name}" cannot be null`);
  }
  if (spec.type === "string" || spec.type === "stringNullable") {
    if (typeof raw !== "string") {
      throw new ValidationError(`field "${spec.name}" must be a string`);
    }
    if (spec.type === "string" && raw.trim() === "") {
      throw new ValidationError(`field "${spec.name}" cannot be empty`);
    }
    if (spec.enum && !spec.enum.includes(raw)) {
      throw new ValidationError(
        `field "${spec.name}" must be one of: ${spec.enum.join(", ")}`,
      );
    }
    return raw;
  }
  if (spec.type === "number" || spec.type === "numberNullable") {
    if (typeof raw !== "number" || !Number.isFinite(raw)) {
      throw new ValidationError(`field "${spec.name}" must be a number`);
    }
    return raw;
  }
  return raw;
}

export class ValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ValidationError";
  }
}

export class MemoryStore {
  constructor(private readonly db: D1Database) {}

  async list(kind: MemoryKind): Promise<unknown[]> {
    const spec = SPECS[kind];
    const cols = ["id", ...spec.columns.map((c) => c.name), "created_at", "updated_at"].join(", ");
    const { results } = await this.db
      .prepare(`SELECT ${cols} FROM ${spec.table} ORDER BY ${spec.orderBy}`)
      .all();
    return results ?? [];
  }

  async create(kind: MemoryKind, body: Record<string, unknown>): Promise<unknown> {
    const spec = SPECS[kind];
    const now = Date.now();
    const id = newId();
    const values: Record<string, unknown> = {};
    for (const col of spec.columns) {
      values[col.name] = coerce(col, body[col.name]);
    }
    const colNames = ["id", ...spec.columns.map((c) => c.name), "created_at", "updated_at"];
    const placeholders = colNames.map(() => "?").join(", ");
    const params = [
      id,
      ...spec.columns.map((c) => values[c.name]),
      now,
      now,
    ];
    await this.db
      .prepare(`INSERT INTO ${spec.table} (${colNames.join(", ")}) VALUES (${placeholders})`)
      .bind(...params)
      .run();
    return { id, ...values, created_at: now, updated_at: now };
  }

  async update(
    kind: MemoryKind,
    id: string,
    patch: Record<string, unknown>,
  ): Promise<unknown | null> {
    const spec = SPECS[kind];
    const sets: string[] = [];
    const params: unknown[] = [];
    for (const col of spec.columns) {
      if (Object.prototype.hasOwnProperty.call(patch, col.name)) {
        const value = coerce({ ...col, default: undefined }, patch[col.name]);
        sets.push(`${col.name} = ?`);
        params.push(value);
      }
    }
    if (sets.length === 0) {
      return this.get(kind, id);
    }
    const now = Date.now();
    sets.push("updated_at = ?");
    params.push(now);
    params.push(id);
    const res = await this.db
      .prepare(`UPDATE ${spec.table} SET ${sets.join(", ")} WHERE id = ?`)
      .bind(...params)
      .run();
    if ((res.meta.changes ?? 0) === 0) return null;
    return this.get(kind, id);
  }

  async get(kind: MemoryKind, id: string): Promise<unknown | null> {
    const spec = SPECS[kind];
    const cols = ["id", ...spec.columns.map((c) => c.name), "created_at", "updated_at"].join(", ");
    const row = await this.db
      .prepare(`SELECT ${cols} FROM ${spec.table} WHERE id = ?`)
      .bind(id)
      .first();
    return row ?? null;
  }

  async delete(kind: MemoryKind, id: string): Promise<boolean> {
    const spec = SPECS[kind];
    const res = await this.db
      .prepare(`DELETE FROM ${spec.table} WHERE id = ?`)
      .bind(id)
      .run();
    return (res.meta.changes ?? 0) > 0;
  }

  async snapshot(): Promise<MemorySnapshot> {
    const [facts, preferences, commitments, projects, episodes] = await Promise.all([
      this.list("facts") as Promise<Fact[]>,
      this.list("preferences") as Promise<Preference[]>,
      this.list("commitments") as Promise<Commitment[]>,
      this.list("projects") as Promise<Project[]>,
      this.list("episodes") as Promise<Episode[]>,
    ]);
    return { facts, preferences, commitments, projects, episodes };
  }
}

export function renderMemoryContext(snapshot: MemorySnapshot): string {
  const lines: string[] = [];

  if (snapshot.facts.length) {
    lines.push("## Hechos sobre el usuario");
    for (const f of snapshot.facts) lines.push(`- ${f.content}`);
    lines.push("");
  }

  if (snapshot.preferences.length) {
    lines.push("## Preferencias");
    for (const p of snapshot.preferences) {
      lines.push(`- ${p.category ? `[${p.category}] ` : ""}${p.content}`);
    }
    lines.push("");
  }

  const openCommitments = snapshot.commitments.filter(
    (c: Commitment) => c.status === ("open" satisfies CommitmentStatus),
  );
  if (openCommitments.length) {
    lines.push("## Compromisos abiertos");
    for (const c of openCommitments) {
      const due = c.due_at ? ` (vence ${new Date(c.due_at).toISOString().slice(0, 10)})` : "";
      lines.push(`- ${c.content}${due}`);
    }
    lines.push("");
  }

  const activeProjects = snapshot.projects.filter(
    (p: Project) => p.status === ("active" satisfies ProjectStatus),
  );
  if (activeProjects.length) {
    lines.push("## Proyectos activos");
    for (const p of activeProjects) {
      lines.push(`- ${p.name}${p.description ? `: ${p.description}` : ""}`);
    }
    lines.push("");
  }

  if (snapshot.episodes.length) {
    lines.push("## Episodios recientes");
    for (const e of snapshot.episodes.slice(0, 20)) {
      const when = e.occurred_at
        ? new Date(e.occurred_at).toISOString().slice(0, 10)
        : "—";
      lines.push(`- [${when}] ${e.title ? `${e.title}: ` : ""}${e.summary}`);
    }
    lines.push("");
  }

  return lines.join("\n").trim();
}
