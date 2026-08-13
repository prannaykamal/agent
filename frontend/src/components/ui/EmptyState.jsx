import React from "react";

export default function EmptyState({ title, body }) {
  return (
    <div className="empty">
      {title ? <h3>{title}</h3> : null}
      <div>{body}</div>
    </div>
  );
}
