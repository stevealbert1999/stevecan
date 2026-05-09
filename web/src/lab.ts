import { ApiClient, type JarvisEvent } from "./api";
import { bindSettingsDialog, loadSettings } from "./auth";
import { startBadgePolling } from "./badge";
import { LiveBus } from "./live";

const $ = <T extends Element>(s: string) => document.querySelector<T>(s)!;

let client: ApiClient | null = null;
let bus: LiveBus | null = null;

function setWsState(label: string, ok: boolean): void {
  const pill = $<HTMLSpanElement>("#ws-state");
  pill.textContent = label;
  pill.classList.toggle("ok", ok);
  pill.classList.toggle("bad", !ok);
}

async function refreshState(): Promise<void> {
  if (!client) return;
  const pre = $<HTMLPreElement>("#state-json");
  try {
    const s = await client.getState();
    pre.textContent = JSON.stringify(s, null, 2);
  } catch (err) {
    pre.textContent = "Error: " + (err instanceof Error ? err.message : String(err));
  }
}

function appendEvent(e: JarvisEvent): void {
  const ul = $<HTMLUListElement>("#event-stream");
  const li = document.createElement("li");
  li.className = "event-row";
  const time = new Date(e.created_at).toLocaleTimeString();
  const kind = document.createElement("code");
  kind.textContent = e.kind;
  const meta = document.createElement("span");
  meta.className = "event-meta";
  meta.textContent = `${time} · ${e.source}`;
  li.appendChild(kind);
  li.appendChild(meta);
  if (e.payload) {
    const payload = document.createElement("pre");
    payload.textContent = typeof e.payload === "string" ? e.payload : JSON.stringify(e.payload);
    li.appendChild(payload);
  }
  ul.prepend(li);
  while (ul.children.length > 80) ul.removeChild(ul.lastChild!);
}

async function runEndpoint(ev: SubmitEvent): Promise<void> {
  ev.preventDefault();
  if (!client) return;
  const method = $<HTMLSelectElement>("#runner-method").value;
  const path = $<HTMLInputElement>("#runner-path").value.trim();
  const body = $<HTMLTextAreaElement>("#runner-body").value.trim();
  if (!path) return;
  const out = $<HTMLPreElement>("#runner-output");
  out.textContent = "…";
  try {
    const r = await client.runRequest({ method, path, body });
    let pretty = r.body;
    try {
      pretty = JSON.stringify(JSON.parse(r.body), null, 2);
    } catch {
      // not JSON
    }
    out.textContent = `HTTP ${r.status}\n\n${pretty}`;
  } catch (err) {
    out.textContent = "Error: " + (err instanceof Error ? err.message : String(err));
  }
}

function init(): void {
  const openSettings = bindSettingsDialog((s) => {
    bus?.stop();
    client = new ApiClient(s);
    boot();
  });
  const s = loadSettings();
  if (!s) {
    openSettings();
    return;
  }
  client = new ApiClient(s);
  boot();
}

function boot(): void {
  if (!client) return;
  refreshState();
  startBadgePolling();
  $<HTMLButtonElement>("#refresh-state").addEventListener("click", () => refreshState());
  $<HTMLFormElement>("#runner").addEventListener("submit", runEndpoint);

  bus = new LiveBus(client);
  bus.on((e) => {
    appendEvent(e);
    // Suggestions and memory changes invalidate /state cheaply; re-poll lightly.
    if (e.kind.startsWith("suggestion.") || e.kind.startsWith("memory.")) {
      refreshState();
    }
  });
  bus.start();
  setWsState("conectado", true);
}

init();
