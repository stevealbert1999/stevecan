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
