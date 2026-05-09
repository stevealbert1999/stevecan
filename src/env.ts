export interface Env {
  DB: D1Database;
  HUD_HUB: DurableObjectNamespace;
  OPENAI_API_KEY: string;
  JARVIS_API_KEY: string;
  JARVIS_SYSTEM_PROMPT: string;
  JARVIS_MODEL: string;
  JARVIS_VERSION: string;
  JARVIS_WEB_ORIGIN?: string;
  JARVIS_BUTLER_ENABLED?: string;
  JARVIS_BUTLER_MODEL?: string;
}
