---
name: fin-skills
description: Índice de los skills de Fin 2x (intercom/2x-skills) vendorizados en este repo: revisión de skills, seguridad de GitHub Actions, tests inestables, code review estricto, creación de PRs y meta-herramientas de Claude Code.
---

# Fin 2x skills (vendorizados)

Skills disponibles en `.claude/skills/<nombre>/`; invócalos con la herramienta Skill por su nombre:

| Skill | Para qué |
|---|---|
| `skill-review` | Revisar un skill contra una rúbrica de 8 categorías |
| `secure-github-actions` | Endurecer workflows de GitHub Actions (supply-chain, inyección) — úsalo al editar `.github/workflows/*.yml` |
| `fix-flaky-tests` | Investigar y arreglar tests inestables |
| `thermo-nuclear-code-review` | Revisión estructural/arquitectónica muy estricta |
| `create-pr` | Abrir pull requests bien formados |
| `attach-github-assets` | Subir capturas/grabaciones a GitHub para PRs e issues |
| `permissions-analyzer` | Auditar la allowlist de permisos de Claude Code |
| `tool-misses` | Detectar y arreglar herramientas CLI que faltan |
| `cc-cost-analysis` | Analizar costes de uso de Claude Code (OpenTelemetry) |
| `audit-memory` | Verificar y archivar memorias guardadas obsoletas |

Origen: https://github.com/intercom/2x-skills (MIT). Plugins oficiales: `/plugin marketplace add intercom/2x-skills` y `/plugin install <plugin>@fin-2x`.
