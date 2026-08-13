import React from "react";

export default function Spinner({ label = "Loading…" }) {
  return (
    <div className="loading-block">
      <div className="spinner" />
      <span>{label}</span>
    </div>
  );
}
