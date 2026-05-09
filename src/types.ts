export type Role = "system" | "user" | "assistant";

export interface Thread {
  id: string;
  title: string | null;
  created_at: number;
  updated_at: number;
}

export interface Message {
  id: string;
  thread_id: string;
  role: Role;
  content: string;
  created_at: number;
}

export interface Fact {
  id: string;
  content: string;
  created_at: number;
  updated_at: number;
}

export interface Preference {
  id: string;
  category: string | null;
  content: string;
  created_at: number;
  updated_at: number;
}

export type CommitmentStatus = "open" | "done" | "cancelled";

export interface Commitment {
  id: string;
  content: string;
  due_at: number | null;
  status: CommitmentStatus;
  created_at: number;
  updated_at: number;
}

export type ProjectStatus = "active" | "paused" | "done" | "archived";

export interface Project {
  id: string;
  name: string;
  description: string | null;
  status: ProjectStatus;
  created_at: number;
  updated_at: number;
}

export interface Episode {
  id: string;
  title: string | null;
  summary: string;
  occurred_at: number | null;
  created_at: number;
  updated_at: number;
}

export const MEMORY_KINDS = [
  "facts",
  "preferences",
  "commitments",
  "projects",
  "episodes",
] as const;
export type MemoryKind = (typeof MEMORY_KINDS)[number];

export interface MemorySnapshot {
  facts: Fact[];
  preferences: Preference[];
  commitments: Commitment[];
  projects: Project[];
  episodes: Episode[];
}

export interface JarvisEvent {
  id: string;
  kind: string;
  source: string;
  payload: string | null;
  created_at: number;
}

export type SuggestionStatus = "pending" | "accepted" | "dismissed";

export interface Suggestion {
  id: string;
  title: string;
  reason: string | null;
  priority: number;
  status: SuggestionStatus;
  action_payload: string | null;
  thread_id: string | null;
  created_at: number;
  updated_at: number;
}
