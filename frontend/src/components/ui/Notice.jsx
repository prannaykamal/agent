import React from "react";

export default function Notice({ kind = "info", children }) {
  if (!children) return null;
  const cls = kind === "ok" ? "notice-ok" : kind === "error" ? "notice-error" : kind === "warn" ? "notice-warn" : "";
  return <div className={`notice ${cls}`}>{children}</div>;
}
