import { create } from "zustand";

type Theme = "light" | "dark";

interface ThemeState {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
}

const STORAGE_KEY = "boulder-theme";

function detectSystemTheme(): Theme {
  if (typeof window === "undefined") return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

function loadTheme(): Theme {
  if (typeof window === "undefined") return "light";
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored === "light" || stored === "dark") {
    return stored;
  }
  return detectSystemTheme();
}

function saveTheme(theme: Theme) {
  if (typeof window === "undefined") return;
  localStorage.setItem(STORAGE_KEY, theme);
}

function publishTheme(theme: Theme) {
  // Publish to the backend (fire-and-forget) so external local tools — e.g. the
  // Trajectory Dashboard — can mirror the GUI's current light/dark setting.
  if (typeof fetch === "undefined") return;
  void fetch("/api/ui/theme", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ theme }),
  }).catch(() => {});
}

function applyTheme(theme: Theme) {
  if (typeof document === "undefined") return;
  document.documentElement.classList.toggle("dark", theme === "dark");
}

export const useThemeStore = create<ThemeState>((set) => {
  const initial = loadTheme();
  // Apply + publish on creation.
  applyTheme(initial);
  publishTheme(initial);

  return {
    theme: initial,
    setTheme: (theme) => {
      applyTheme(theme);
      saveTheme(theme);
      publishTheme(theme);
      set({ theme });
    },
    toggleTheme: () =>
      set((state) => {
        const next: Theme = state.theme === "light" ? "dark" : "light";
        applyTheme(next);
        saveTheme(next);
        publishTheme(next);
        return { theme: next };
      }),
  };
});
