import { ApiClient, type ThreadDetail, type ThreadMeta } from "./api";
import { bindSettingsDialog, loadSettings } from "./auth";
import { refreshButlerBadge, startBadgePolling } from "./badge";

interface State {
  client: ApiClient | null;
  threads: ThreadMeta[];
  current: ThreadDetail | null;
  streamingBubble: HTMLDivElement | null;
}

const state: State = {
  client: null,
  threads: [],
  current: null,
  streamingBubble: null,
};

const $ = <T extends Element>(s: string) => document.querySelector<T>(s)!;

function ensureClient(openSettings: () => void): ApiClient | null {
  const s = loadSettings();
  if (!s) {
    openSettings();
    return null;
  }
  state.client = new ApiClient(s);
  return state.client;
}

async function refreshThreads() {
  if (!state.client) return;
  try {
    state.threads = await state.client.listThreads();
  } catch (err) {
    console.error(err);
    return;
  }
  const list = $<HTMLUListElement>("#thread-list");
  list.innerHTML = "";
  for (const t of state.threads) {
    const li = document.createElement("li");
    li.textContent = t.title ?? "(sin título)";
    li.dataset.id = t.id;
    if (state.current?.id === t.id) li.classList.add("active");
    li.addEventListener("click", () => loadThread(t.id));
    list.appendChild(li);
  }
}

function renderMessages() {
  const box = $<HTMLDivElement>("#messages");
  box.innerHTML = "";
  if (!state.current) {
    const empty = document.createElement("div");
    empty.className = "bubble assistant";
    empty.textContent = "Empieza una conversación. Lo que escribas se persistirá.";
    box.appendChild(empty);
    return;
  }
  for (const m of state.current.messages) {
    if (m.role === "system") continue;
    const b = document.createElement("div");
    b.className = `bubble ${m.role}`;
    b.textContent = m.content;
    box.appendChild(b);
  }
  box.scrollTop = box.scrollHeight;
}

async function loadThread(id: string) {
  if (!state.client) return;
  state.current = await state.client.getThread(id);
  renderMessages();
  await refreshThreads();
}

function newThread() {
  state.current = null;
  state.streamingBubble = null;
  renderMessages();
  document
    .querySelectorAll<HTMLLIElement>("#thread-list li")
    .forEach((li) => li.classList.remove("active"));
}

async function send(text: string) {
  if (!state.client) return;
  const box = $<HTMLDivElement>("#messages");

  const userBubble = document.createElement("div");
  userBubble.className = "bubble user";
  userBubble.textContent = text;
  box.appendChild(userBubble);

  const assistantBubble = document.createElement("div");
  assistantBubble.className = "bubble assistant streaming";
  assistantBubble.textContent = "";
  box.appendChild(assistantBubble);
  state.streamingBubble = assistantBubble;
  box.scrollTop = box.scrollHeight;

  let threadId = state.current?.id;
  let acc = "";

  try {
    await state.client.chatStream(
      { thread_id: threadId, message: text },
      (e) => {
        if (e.type === "thread") {
          threadId = e.thread_id;
        } else if (e.type === "delta") {
          acc += e.delta;
          assistantBubble.textContent = acc;
          box.scrollTop = box.scrollHeight;
        } else if (e.type === "done") {
          threadId = e.thread_id;
          assistantBubble.classList.remove("streaming");
        } else if (e.type === "error") {
          assistantBubble.classList.remove("streaming");
          assistantBubble.classList.add("danger");
          assistantBubble.textContent = `Error: ${e.message}`;
        }
      },
    );
  } catch (err) {
    assistantBubble.classList.remove("streaming");
    assistantBubble.textContent =
      "Error: " + (err instanceof Error ? err.message : String(err));
  }

  if (threadId) {
    await loadThread(threadId);
  }

  // Butler runs server-side after the response; refresh the badge a few times.
  setTimeout(() => refreshButlerBadge(), 1500);
  setTimeout(() => refreshButlerBadge(), 5000);
}

function bindComposer() {
  const form = $<HTMLFormElement>("#composer");
  const input = $<HTMLTextAreaElement>("#input");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    await send(text);
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      form.requestSubmit();
    }
  });
}

function init() {
  const openSettings = bindSettingsDialog((s) => {
    state.client = new ApiClient(s);
    refreshThreads();
  });
  $<HTMLButtonElement>("#new-thread").addEventListener("click", newThread);
  bindComposer();
  renderMessages();

  if (!ensureClient(openSettings)) return;
  refreshThreads();
  startBadgePolling();
}

init();
