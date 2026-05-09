import { defineWorkersConfig } from "@cloudflare/vitest-pool-workers/config";

export default defineWorkersConfig({
  test: {
    poolOptions: {
      workers: {
        singleWorker: true,
        miniflare: {
          compatibilityDate: "2025-01-15",
          compatibilityFlags: ["nodejs_compat"],
          d1Databases: ["DB"],
          bindings: {
            JARVIS_API_KEY: "test-token",
            OPENAI_API_KEY: "sk-test",
            JARVIS_MODEL: "gpt-4o-mini",
            JARVIS_SYSTEM_PROMPT: "You are Jarvis (test).",
            JARVIS_VERSION: "test",
            JARVIS_WEB_ORIGIN: "*",
            JARVIS_BUTLER_ENABLED: "false",
            JARVIS_BUTLER_MODEL: "gpt-4o-mini",
          },
        },
        wrangler: {
          configPath: "./wrangler.toml",
        },
      },
    },
  },
});
