import React, { useEffect, useState } from "react";
import Icon from "./Icon.jsx";

const THEME_KEY = "ivo-theme";

function readTheme() {
  try {
    const saved = localStorage.getItem(THEME_KEY) || localStorage.getItem("astra-theme");
    if (saved === "light" || saved === "dark") return saved;
  } catch {
    /* ignore */
  }
  if (typeof window !== "undefined" && window.matchMedia?.("(prefers-color-scheme: light)").matches) {
    return "light";
  }
  return "dark";
}

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  document.documentElement.style.colorScheme = theme;
  try {
    localStorage.setItem(THEME_KEY, theme);
  } catch {
    /* ignore */
  }
}

export default function ThemeToggle() {
  const [theme, setTheme] = useState(() => document.documentElement.getAttribute("data-theme") || readTheme());

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  const next = theme === "dark" ? "light" : "dark";

  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={() => setTheme(next)}
      aria-label={`Switch to ${next} theme`}
      title={`Switch to ${next} theme`}
    >
      <Icon name={theme === "dark" ? "sun" : "moon"} />
    </button>
  );
}
