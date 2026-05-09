interface Settings {
  apiUrl: string;
  apiKey: string;
}

const KEY = "jarvis.settings.v1";

export function loadSettings(): Settings | null {
  const raw = localStorage.getItem(KEY);
  if (!raw) return null;
  try {
    const obj = JSON.parse(raw) as Partial<Settings>;
    if (typeof obj.apiUrl === "string" && typeof obj.apiKey === "string") {
      return { apiUrl: obj.apiUrl, apiKey: obj.apiKey };
    }
  } catch {
    // ignore
  }
  return null;
}

export function saveSettings(s: Settings): void {
  localStorage.setItem(KEY, JSON.stringify(s));
}

export function clearSettings(): void {
  localStorage.removeItem(KEY);
}

export function bindSettingsDialog(
  onSaved: (s: Settings) => void,
): () => void {
  const dialog = document.querySelector<HTMLDialogElement>("#settings-dialog");
  const form = document.querySelector<HTMLFormElement>("#settings-form");
  const apiUrl = document.querySelector<HTMLInputElement>("#api-url");
  const apiKey = document.querySelector<HTMLInputElement>("#api-key");
  const btn = document.querySelector<HTMLButtonElement>("#settings-btn");
  if (!dialog || !form || !apiUrl || !apiKey || !btn) {
    throw new Error("settings dialog markup missing");
  }

  const open = () => {
    const cur = loadSettings();
    apiUrl.value = cur?.apiUrl ?? "";
    apiKey.value = cur?.apiKey ?? "";
    dialog.showModal();
  };

  btn.addEventListener("click", open);

  form.addEventListener("submit", (e) => {
    const submitter = (e as SubmitEvent).submitter as HTMLButtonElement | null;
    if (submitter?.value === "save") {
      const s: Settings = { apiUrl: apiUrl.value.trim(), apiKey: apiKey.value.trim() };
      saveSettings(s);
      onSaved(s);
    }
  });

  return open;
}
