export function formatBytes(bytes) {
  const n = Number(bytes) || 0;
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatJson(value) {
  try {
    return JSON.stringify(value ?? {}, null, 2);
  } catch {
    return String(value ?? "");
  }
}

export function previewText(value, max = 160) {
  const text = typeof value === "string" ? value : formatJson(value);
  if (text.length <= max) return text;
  return `${text.slice(0, max)}…`;
}

export function asList(value, splitter = ",") {
  if (Array.isArray(value)) return value.filter(Boolean);
  if (typeof value === "string" && value.trim()) {
    return value.split(splitter).map((item) => item.trim()).filter(Boolean);
  }
  return [];
}

export function statusTone(status) {
  const s = String(status || "unknown").toLowerCase();
  if (["ok", "online", "healthy", "available", "mcp_available", "running", "succeeded", "active", "configured", "api_configured"].some((k) => s.includes(k))) {
    return "ok";
  }
  if (["pending", "paused", "waiting", "unavailable", "not_configured", "mcp_unavailable", "api_missing", "stale", "retry"].some((k) => s.includes(k))) {
    return "warn";
  }
  if (["fail", "error", "blocked", "cancelled", "expired", "danger", "discovery_failed"].some((k) => s.includes(k))) {
    return "danger";
  }
  return "idle";
}
