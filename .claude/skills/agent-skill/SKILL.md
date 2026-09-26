---
name: agent-skill
description: Índice de los Agent Skills públicos de Anthropic (anthropics/skills) vendorizados en este repo. Úsalo para elegir el skill adecuado de diseño, frontend, MCP, pruebas web, comunicación o creación de skills.
---

# Agent Skills de Anthropic (vendorizados)

Skills disponibles en `.claude/skills/<nombre>/`; invócalos con la herramienta Skill por su nombre:

- `academy-guide` — >
- `algorithmic-art` — Creating algorithmic art using p5.js with seeded randomness and interactive parameter exploration. Use this when users request creating art using code, generati
- `brand-guidelines` — Applies Anthropic's official brand colors and typography to any sort of artifact that may benefit from having Anthropic's look-and-feel. Use it when brand color
- `canvas-design` — Create beautiful visual art in .png and .pdf documents using design philosophy. You should use this skill when the user asks to create a poster, piece of art, d
- `claude-api` — |-
- `discernment-nudge` — >
- `doc-coauthoring` — Guide users through a structured workflow for co-authoring documentation. Use when user wants to write documentation, proposals, technical specs, decision docs,
- `frontend-design` — Guidance for distinctive, intentional visual design when building new UI or reshaping an existing one. Helps with aesthetic direction, typography, and making ch
- `internal-comms` — A set of resources to help me write all kinds of internal communications, using the formats that my company likes to use. Claude should use this skill whenever 
- `mcp-builder` — Guide for creating high-quality MCP (Model Context Protocol) servers that enable LLMs to interact with external services through well-designed tools. Use when b
- `skill-creator` — Create new skills, modify and improve existing skills, and measure skill performance. Use when users want to create a skill from scratch, edit, or optimize an e
- `slack-gif-creator` — Knowledge and utilities for creating animated GIFs optimized for Slack. Provides constraints, validation tools, and animation concepts. Use when users request a
- `theme-factory` — Toolkit for styling artifacts with a theme. These artifacts can be slides, docs, reportings, HTML landing pages, etc. There are 10 pre-set themes with colors/fo
- `web-artifacts-builder` — Suite of tools for creating elaborate, multi-component claude.ai HTML artifacts using modern frontend web technologies (React, Tailwind CSS, shadcn/ui). Use for
- `webapp-testing` — Toolkit for interacting with and testing local web applications using Playwright. Supports verifying frontend functionality, debugging UI behavior, capturing br

No incluidos por licencia (source-available, no redistribuible): docx pdf pptx xlsx. Esos ya vienen integrados en Claude Code web / Cowork (`anthropic-skills:docx`, `pdf`, `pptx`, `xlsx`) o se instalan con `/plugin install document-skills@anthropic-agent-skills`.

Especificación del formato: https://agentskills.io · Origen: https://github.com/anthropics/skills (Apache 2.0).
