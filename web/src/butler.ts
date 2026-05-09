import { ApiClient, type Suggestion, type SuggestionStatus } from "./api";
import { bindSettingsDialog, loadSettings } from "./auth";
import { LiveBus } from "./live";

const $ = <T extends Element>(s: string) => document.querySelector<T>(s)!;

let client: ApiClient | null = null;

function priorityLabel(p: number): string {
  if (p >= 5) return "alta";
  if (p >= 4) return "alta";
  if (p === 3) return "media";
  return "baja";
}

function renderSuggestion(sug: Suggestion): HTMLLIElement {
  const li = document.createElement("li");
  li.className = `suggestion priority-${sug.priority}`;
  li.dataset.id = sug.id;

  const header = document.createElement("div");
  header.className = "suggestion-head";
  const title = document.createElement("strong");
  title.textContent = sug.title;
  header.appendChild(title);

  const meta = document.createElement("span");
  meta.className = "meta";
  meta.textContent = `prio ${sug.priority} · ${priorityLabel(sug.priority)}`;
  header.appendChild(meta);
  li.appendChild(header);

  if (sug.reason) {
    const reason = document.createElement("p");
    reason.className = "reason";
    reason.textContent = sug.reason;
    li.appendChild(reason);
  }

  const actions = document.createElement("div");
  actions.className = "suggestion-actions";

  if (sug.status === "pending") {
    const accept = document.createElement("button");
    accept.textContent = "Aceptar";
    accept.addEventListener("click", () => mutate(sug.id, "accepted"));
    const dismiss = document.createElement("button");
    dismiss.textContent = "Descartar";
    dismiss.className = "danger";
    dismiss.addEventListener("click", () => mutate(sug.id, "dismissed"));
    actions.appendChild(accept);
    actions.appendChild(dismiss);
  } else {
    const reopen = document.createElement("button");
    reopen.textContent = "Reabrir";
    reopen.addEventListener("click", () => mutate(sug.id, "pending"));
    const del = document.createElement("button");
    del.textContent = "Borrar";
    del.className = "danger";
    del.addEventListener("click", () => remove(sug.id));
    actions.appendChild(reopen);
    actions.appendChild(del);
  }

  li.appendChild(actions);
  return li;
}

async function mutate(id: string, status: SuggestionStatus) {
  if (!client) return;
  try {
    await client.updateSuggestion(id, { status });
    await refresh();
  } catch (err) {
    console.error(err);
    alert(err instanceof Error ? err.message : String(err));
  }
}

async function remove(id: string) {
  if (!client) return;
  if (!confirm("¿Borrar esta sugerencia?")) return;
  try {
    await client.deleteSuggestion(id);
    await refresh();
  } catch (err) {
    console.error(err);
  }
}

function fillSection(targetId: string, items: Suggestion[]) {
  const ul = $<HTMLUListElement>(`#${targetId}`);
  ul.innerHTML = "";
  if (items.length === 0) {
    const empty = document.createElement("li");
    empty.className = "empty";
    empty.textContent = "—";
    ul.appendChild(empty);
    return;
  }
  for (const s of items) ul.appendChild(renderSuggestion(s));
}

async function refresh() {
  if (!client) return;
  try {
    const [pending, accepted, dismissed] = await Promise.all([
      client.listSuggestions("pending"),
      client.listSuggestions("accepted"),
      client.listSuggestions("dismissed"),
    ]);
    fillSection("pending", pending);
    fillSection("accepted", accepted);
    fillSection("dismissed", dismissed);
    const badge = document.querySelector<HTMLSpanElement>("#butler-badge");
    if (badge) badge.textContent = pending.length > 0 ? String(pending.length) : "";
  } catch (err) {
    console.error(err);
  }
}

function init() {
  const openSettings = bindSettingsDialog((s) => {
    client = new ApiClient(s);
    refresh();
  });
  const s = loadSettings();
  if (!s) {
    openSettings();
    return;
  }
  client = new ApiClient(s);
  refresh();

  const bus = new LiveBus(client);
  bus.on((e) => {
    if (e.kind.startsWith("suggestion.")) refresh();
  });
  bus.start();
}

init();
