import {
  ApiClient,
  type MemoryItem,
  type MemoryKind,
  type MemorySnapshot,
} from "./api";
import { bindSettingsDialog, loadSettings } from "./auth";
import { startBadgePolling } from "./badge";

const $ = <T extends Element>(s: string) => document.querySelector<T>(s)!;
const $$ = <T extends Element>(s: string) => Array.from(document.querySelectorAll<T>(s));

let client: ApiClient | null = null;

const FIELDS: Record<MemoryKind, Array<{ name: string; placeholder: string; type?: "date" | "text" }>> = {
  facts: [{ name: "content", placeholder: "Hecho" }],
  preferences: [
    { name: "category", placeholder: "Categoría" },
    { name: "content", placeholder: "Preferencia" },
  ],
  commitments: [
    { name: "content", placeholder: "Compromiso" },
    { name: "due_at", placeholder: "Fecha límite", type: "date" },
  ],
  projects: [
    { name: "name", placeholder: "Nombre" },
    { name: "description", placeholder: "Descripción" },
  ],
  episodes: [
    { name: "title", placeholder: "Título" },
    { name: "summary", placeholder: "Resumen" },
    { name: "occurred_at", placeholder: "Fecha", type: "date" },
  ],
};

function dateToTs(input: string | null | undefined): number | null {
  if (!input) return null;
  const t = Date.parse(input);
  return Number.isFinite(t) ? t : null;
}

function tsToDateInput(ts: unknown): string {
  if (typeof ts !== "number") return "";
  return new Date(ts).toISOString().slice(0, 10);
}

function renderItem(kind: MemoryKind, item: MemoryItem): HTMLLIElement {
  const li = document.createElement("li");
  li.dataset.id = item.id;

  const fields = FIELDS[kind];
  for (const f of fields) {
    const input = document.createElement("input");
    input.type = f.type === "date" ? "date" : "text";
    input.name = f.name;
    input.placeholder = f.placeholder;
    if (f.type === "date") {
      input.value = tsToDateInput(item[f.name]);
    } else {
      input.value = (item[f.name] as string | null | undefined) ?? "";
    }
    input.className = "text";
    input.addEventListener("change", async () => {
      if (!client) return;
      const patch: Record<string, unknown> = {};
      patch[f.name] =
        f.type === "date" ? dateToTs(input.value || null) : input.value || null;
      try {
        await client.updateMemory(kind, item.id, patch);
      } catch (err) {
        console.error(err);
        alert("No se pudo guardar el cambio.");
      }
    });
    li.appendChild(input);
  }

  if (kind === "commitments") {
    const sel = document.createElement("select");
    for (const opt of ["open", "done", "cancelled"]) {
      const o = document.createElement("option");
      o.value = opt;
      o.textContent = opt;
      if (item.status === opt) o.selected = true;
      sel.appendChild(o);
    }
    sel.addEventListener("change", async () => {
      if (!client) return;
      try {
        await client.updateMemory(kind, item.id, { status: sel.value });
      } catch (err) {
        console.error(err);
      }
    });
    li.appendChild(sel);
  }

  if (kind === "projects") {
    const sel = document.createElement("select");
    for (const opt of ["active", "paused", "done", "archived"]) {
      const o = document.createElement("option");
      o.value = opt;
      o.textContent = opt;
      if (item.status === opt) o.selected = true;
      sel.appendChild(o);
    }
    sel.addEventListener("change", async () => {
      if (!client) return;
      try {
        await client.updateMemory(kind, item.id, { status: sel.value });
      } catch (err) {
        console.error(err);
      }
    });
    li.appendChild(sel);
  }

  const del = document.createElement("button");
  del.type = "button";
  del.textContent = "✕";
  del.className = "danger";
  del.addEventListener("click", async () => {
    if (!client) return;
    if (!confirm("¿Borrar este elemento?")) return;
    try {
      await client.deleteMemory(kind, item.id);
      li.remove();
    } catch (err) {
      console.error(err);
    }
  });
  li.appendChild(del);

  return li;
}

function renderSection(kind: MemoryKind, items: MemoryItem[]): void {
  const section = document.querySelector<HTMLElement>(`section[data-kind="${kind}"]`);
  if (!section) return;
  const ul = section.querySelector<HTMLUListElement>(".items");
  if (!ul) return;
  ul.innerHTML = "";
  for (const item of items) ul.appendChild(renderItem(kind, item));
}

async function refresh() {
  if (!client) return;
  const snap: MemorySnapshot = await client.getMemory();
  renderSection("facts", snap.facts);
  renderSection("preferences", snap.preferences);
  renderSection("commitments", snap.commitments);
  renderSection("projects", snap.projects);
  renderSection("episodes", snap.episodes);
}

function bindAddForms() {
  $$<HTMLFormElement>("section .add-form").forEach((form) => {
    const section = form.closest<HTMLElement>("section[data-kind]");
    if (!section) return;
    const kind = section.dataset.kind as MemoryKind;
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (!client) return;
      const data = new FormData(form);
      const body: Record<string, unknown> = {};
      for (const [k, v] of data.entries()) {
        const value = typeof v === "string" ? v.trim() : "";
        if (!value) continue;
        if (k === "due_at" || k === "occurred_at") {
          body[k] = dateToTs(value);
        } else {
          body[k] = value;
        }
      }
      try {
        await client.createMemory(kind, body);
        form.reset();
        await refresh();
      } catch (err) {
        console.error(err);
        alert(err instanceof Error ? err.message : String(err));
      }
    });
  });
}

function init() {
  const openSettings = bindSettingsDialog((s) => {
    client = new ApiClient(s);
    refresh();
  });
  bindAddForms();
  const s = loadSettings();
  if (!s) {
    openSettings();
    return;
  }
  client = new ApiClient(s);
  refresh().catch((err) => console.error(err));
  startBadgePolling();
}

init();
