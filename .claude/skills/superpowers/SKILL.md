---
name: superpowers
description: Punto de entrada a Superpowers (obra/superpowers) vendorizado en este repo. Úsalo al iniciar cualquier tarea de desarrollo para elegir el skill de proceso adecuado (brainstorming, writing-plans, test-driven-development, systematic-debugging, etc.).
---

# Superpowers (vendorizado)

Los skills de Superpowers viven en `.claude/skills/<nombre>/` de este repositorio, sin prefijo `superpowers:`.
Invoca cada uno con la herramienta Skill usando su nombre simple.

Primero lee y aplica `using-superpowers`. Después elige según la situación:

| Situación | Skill |
|---|---|
| Empezar algo nuevo, idea difusa | `brainstorming` |
| Diseño aprobado, hay que planificar | `writing-plans` |
| Ejecutar un plan escrito | `executing-plans` o `subagent-driven-development` |
| Implementar código | `test-driven-development` |
| Un bug o comportamiento raro | `systematic-debugging` |
| Trabajo paralelo aislado | `using-git-worktrees`, `dispatching-parallel-agents` |
| Pedir / recibir revisión de código | `requesting-code-review`, `receiving-code-review` |
| Antes de decir "terminado" | `verification-before-completion` |
| Cerrar una rama de desarrollo | `finishing-a-development-branch` |
| Crear o mejorar skills | `writing-skills` |
| Superpowers no se comporta bien | `diagnosing-superpowers` |

Flujo por defecto: `brainstorming` → `writing-plans` → `executing-plans`/`subagent-driven-development` (con `test-driven-development`) → `verification-before-completion` → `finishing-a-development-branch`.

Origen: https://github.com/obra/superpowers (MIT). Para instalar el plugin oficial con sus hooks en Claude Code local: `/plugin install superpowers@claude-plugins-official`.
