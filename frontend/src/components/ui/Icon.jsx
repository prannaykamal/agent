import React from "react";

function Svg({ children }) {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {children}
    </svg>
  );
}

const ICONS = {
  overview: (
    <>
      <rect x="3" y="3" width="8" height="8" rx="1.5" />
      <rect x="13" y="3" width="8" height="5" rx="1.5" />
      <rect x="13" y="12" width="8" height="9" rx="1.5" />
      <rect x="3" y="15" width="8" height="6" rx="1.5" />
    </>
  ),
  chat: (
    <>
      <path d="M4 6h16v10H8l-4 3V6z" />
      <path d="M8 10h8M8 13h5" />
    </>
  ),
  loop: (
    <>
      <path d="M4 12a8 8 0 1 1 2.3 5.6" />
      <path d="M4 16V12h4" />
    </>
  ),
  tasks: (
    <>
      <path d="M9 6h12M9 12h12M9 18h12" />
      <path d="M4 6h.01M4 12h.01M4 18h.01" />
    </>
  ),
  memory: (
    <>
      <rect x="5" y="4" width="14" height="16" rx="2" />
      <path d="M9 8h6M9 12h6M9 16h4" />
    </>
  ),
  approvals: (
    <>
      <path d="M12 3l8 4v6c0 5-3.4 7.4-8 9-4.6-1.6-8-4-8-9V7l8-4z" />
      <path d="M9 12l2.2 2.2L16 10" />
    </>
  ),
  tools: (
    <>
      <path d="M14.7 6.3a4 4 0 0 1 2.8 6.9L12 18.7 8.3 15l5.5-5.5a2 2 0 1 0-2.8-2.8L5.5 12.2 3 9.7l5.5-5.5a4 4 0 0 1 6.2 2.1z" />
    </>
  ),
  graph: (
    <>
      <circle cx="6" cy="6" r="2.4" />
      <circle cx="18" cy="8" r="2.4" />
      <circle cx="12" cy="18" r="2.4" />
      <path d="M8.2 7l7.5 0.6M7.3 8l3.5 7.7M16.8 10.1l-3.6 5.8" />
    </>
  ),
  ops: (
    <>
      <circle cx="12" cy="12" r="3.2" />
      <path d="M12 3v2.2M12 18.8V21M4.9 6.3l1.6 1.6M17.5 16.1l1.6 1.6M3 12h2.2M18.8 12H21M4.9 17.7l1.6-1.6M17.5 7.9l1.6-1.6" />
    </>
  ),
  scheduled: (
    <>
      <rect x="4" y="5" width="16" height="16" rx="2" />
      <path d="M8 3v4M16 3v4M4 10h16" />
    </>
  ),
  data: (
    <>
      <ellipse cx="12" cy="6" rx="7" ry="3" />
      <path d="M5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6" />
    </>
  ),
  workspace: (
    <>
      <rect x="3" y="4" width="8" height="16" rx="1.5" />
      <rect x="13" y="4" width="8" height="7" rx="1.5" />
      <rect x="13" y="13" width="8" height="7" rx="1.5" />
    </>
  ),
  spark: (
    <>
      <path d="M12 3v4M12 17v4M3 12h4M17 12h4" />
      <path d="M6.3 6.3l2.8 2.8M14.9 14.9l2.8 2.8M17.7 6.3l-2.8 2.8M9.1 14.9l-2.8 2.8" />
    </>
  ),
  sun: (
    <>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 3v1.5M12 19.5V21M4.9 4.9l1.1 1.1M18 18l1.1 1.1M3 12h1.5M19.5 12H21M4.9 19.1l1.1-1.1M18 6l1.1-1.1" />
    </>
  ),
  moon: (
    <>
      <path d="M18 14.5A7 7 0 1 1 9.5 6 5.5 5.5 0 0 0 18 14.5z" />
    </>
  ),
};

export default function Icon({ name }) {
  return <Svg>{ICONS[name] || ICONS.overview}</Svg>;
}
