import { ApiClient } from "./api";
import { loadSettings } from "./auth";
import { getSharedLiveBus } from "./live";

export async function refreshButlerBadge(): Promise<void> {
  const badge = document.querySelector<HTMLSpanElement>("#butler-badge");
  if (!badge) return;
  const s = loadSettings();
  if (!s) {
    badge.textContent = "";
    return;
  }
  try {
    const list = await new ApiClient(s).listSuggestions("pending");
    badge.textContent = list.length > 0 ? String(list.length) : "";
  } catch {
    badge.textContent = "";
  }
}

export function startBadgePolling(intervalMs = 60_000): void {
  refreshButlerBadge();
  setInterval(refreshButlerBadge, intervalMs);
  const bus = getSharedLiveBus();
  bus?.on((e) => {
    if (e.kind.startsWith("suggestion.")) refreshButlerBadge();
  });
}
