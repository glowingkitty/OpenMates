// frontend/packages/ui/src/utils/themeDetection.ts
// Shared DOM theme helpers for browser-only components that cannot rely on
// CSS variable theming alone, such as third-party canvases or map tile layers.
// The resolved OpenMates UI theme lives on <html data-theme>, and that manual
// override must take precedence over OS prefers-color-scheme.
// Architecture: frontend/packages/ui/src/stores/theme.ts

const DARK_MEDIA_QUERY = "(prefers-color-scheme: dark)";

type ResolvedTheme = "light" | "dark";

function getDocumentTheme(): ResolvedTheme | null {
  if (typeof document === "undefined") return null;

  const root = document.documentElement;
  const dataTheme = root.getAttribute("data-theme");
  if (dataTheme === "light" || dataTheme === "dark") return dataTheme;

  const cssValue = getComputedStyle(root)
    .getPropertyValue("--is-dark-mode")
    .trim()
    .toLowerCase();
  if (cssValue === "true" || cssValue === "1") return "dark";
  if (cssValue === "false" || cssValue === "0") return "light";

  return null;
}

export function isDarkThemeActive(): boolean {
  const documentTheme = getDocumentTheme();
  if (documentTheme) return documentTheme === "dark";
  if (typeof window === "undefined") return false;

  return window.matchMedia?.(DARK_MEDIA_QUERY).matches ?? false;
}

export function watchDarkThemeActive(onChange: (isDark: boolean) => void): () => void {
  if (typeof window === "undefined" || typeof document === "undefined") return () => undefined;

  let disposed = false;
  const notify = () => {
    if (!disposed) onChange(isDarkThemeActive());
  };

  const observer = typeof MutationObserver !== "undefined" ? new MutationObserver(notify) : null;
  observer?.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["data-theme", "style"],
  });

  const mediaQuery = window.matchMedia?.(DARK_MEDIA_QUERY);
  mediaQuery?.addEventListener?.("change", notify);
  notify();

  return () => {
    disposed = true;
    observer?.disconnect();
    mediaQuery?.removeEventListener?.("change", notify);
  };
}
