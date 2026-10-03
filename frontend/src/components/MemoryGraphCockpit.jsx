import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client.js";
import PageHeader from "./ui/PageHeader.jsx";
import Notice from "./ui/Notice.jsx";
import Spinner from "./ui/Spinner.jsx";
import EmptyState from "./ui/EmptyState.jsx";

// Bookkeeping nodes cognee keeps alongside the knowledge itself.
const DOCUMENT_TYPES = new Set(["TextDocument", "Document", "DocumentChunk", "TextSummary", "Data", "NodeSet", "SessionQA", "SessionQAVector"]);
const TYPE_COLORS = {
  Entity: "var(--accent)",
  EntityType: "var(--accent-amber)",
  TextSummary: "var(--accent-emerald)",
};
const FALLBACK_COLORS = ["var(--accent-emerald)", "var(--accent-rose)", "var(--info)", "var(--accent-amber)"];
const WIDTH = 1000;
const HEIGHT = 640;

function colorFor(type) {
  if (TYPE_COLORS[type]) return TYPE_COLORS[type];
  if (DOCUMENT_TYPES.has(type)) return "var(--text-muted)";
  let hash = 0;
  for (const ch of type) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  return FALLBACK_COLORS[hash % FALLBACK_COLORS.length];
}

function radiusFor(node) {
  return (DOCUMENT_TYPES.has(node.type) ? 5 : 7) + Math.min(10, Math.sqrt(node.degree || 0) * 2.2);
}

function humanize(text) {
  return String(text || "").replace(/_/g, " ");
}

// Fruchterman–Reingold style layout, advanced a few steps per animation frame.
function useForceLayout(nodes, links) {
  const [positions, setPositions] = useState({});
  const pinned = useRef({});
  const stateRef = useRef(null);

  useEffect(() => {
    const n = nodes.length;
    if (!n) {
      setPositions({});
      return undefined;
    }
    const pos = {};
    nodes.forEach((node, i) => {
      const angle = (2 * Math.PI * i) / n;
      const ring = 120 + 160 * ((i % 3) / 2);
      pos[node.id] = { x: WIDTH / 2 + ring * Math.cos(angle), y: HEIGHT / 2 + ring * Math.sin(angle), vx: 0, vy: 0 };
    });
    const k = Math.sqrt((WIDTH * HEIGHT) / Math.max(n, 1)) * 0.75;
    const totalSteps = n <= 150 ? 300 : n <= 400 ? 180 : 90;
    stateRef.current = { pos, step: 0 };
    let frame;

    const tick = () => {
      const state = stateRef.current;
      if (!state) return;
      const temperature = 40 * (1 - state.step / totalSteps) + 1;
      for (let iter = 0; iter < 4 && state.step < totalSteps; iter += 1, state.step += 1) {
        const disp = {};
        nodes.forEach((a) => {
          disp[a.id] = { x: 0, y: 0 };
        });
        for (let i = 0; i < n; i += 1) {
          const a = state.pos[nodes[i].id];
          for (let j = i + 1; j < n; j += 1) {
            const b = state.pos[nodes[j].id];
            let dx = a.x - b.x;
            let dy = a.y - b.y;
            let dist = Math.sqrt(dx * dx + dy * dy) || 0.01;
            const force = (k * k) / dist;
            dx /= dist;
            dy /= dist;
            disp[nodes[i].id].x += dx * force;
            disp[nodes[i].id].y += dy * force;
            disp[nodes[j].id].x -= dx * force;
            disp[nodes[j].id].y -= dy * force;
          }
        }
        links.forEach((link) => {
          const a = state.pos[link.source];
          const b = state.pos[link.target];
          if (!a || !b) return;
          const dx = a.x - b.x;
          const dy = a.y - b.y;
          const dist = Math.sqrt(dx * dx + dy * dy) || 0.01;
          const force = (dist * dist) / k;
          disp[link.source].x -= (dx / dist) * force;
          disp[link.source].y -= (dy / dist) * force;
          disp[link.target].x += (dx / dist) * force;
          disp[link.target].y += (dy / dist) * force;
        });
        nodes.forEach((node) => {
          if (pinned.current[node.id]) return;
          const p = state.pos[node.id];
          const d = disp[node.id];
          // Gentle pull to the centre keeps disconnected pieces on screen.
          d.x += (WIDTH / 2 - p.x) * 0.02 * k / 10;
          d.y += (HEIGHT / 2 - p.y) * 0.02 * k / 10;
          const len = Math.sqrt(d.x * d.x + d.y * d.y) || 0.01;
          p.x += (d.x / len) * Math.min(len, temperature);
          p.y += (d.y / len) * Math.min(len, temperature);
        });
      }
      setPositions({ ...state.pos });
      if (state.step < totalSteps) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(frame);
      stateRef.current = null;
    };
  }, [nodes, links]);

  const moveNode = useCallback((id, x, y) => {
    pinned.current[id] = true;
    setPositions((current) => ({ ...current, [id]: { ...(current[id] || {}), x, y } }));
    if (stateRef.current?.pos[id]) {
      stateRef.current.pos[id].x = x;
      stateRef.current.pos[id].y = y;
    }
  }, []);

  return [positions, moveNode];
}

export default function MemoryGraphCockpit() {
  const [graph, setGraph] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showDocuments, setShowDocuments] = useState(true);
  const [maxNodes, setMaxNodes] = useState(300);
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState(null);
  const [hoverId, setHoverId] = useState(null);
  const [userView, setUserView] = useState(null); // null = auto-fit the graph
  const [unitsPerPx, setUnitsPerPx] = useState(1);
  const svgRef = useRef(null);
  const dragRef = useRef(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.get(`/api/memory/graph?include_documents=true&max_nodes=${maxNodes}`);
      setGraph(data);
      if (data.error) setError(data.error);
      setSelectedId(null);
    } catch (e) {
      setError(e.message || "Failed to load the memory graph");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    setUserView(null);
  }, [maxNodes]);

  const { nodes, links } = useMemo(() => {
    const all = graph?.nodes || [];
    const kept = showDocuments ? all : all.filter((node) => !DOCUMENT_TYPES.has(node.type));
    const ids = new Set(kept.map((node) => node.id));
    const keptLinks = (graph?.links || []).filter((link) => ids.has(link.source) && ids.has(link.target));
    const degree = {};
    keptLinks.forEach((link) => {
      degree[link.source] = (degree[link.source] || 0) + 1;
      degree[link.target] = (degree[link.target] || 0) + 1;
    });
    return { nodes: kept.map((node) => ({ ...node, degree: degree[node.id] || 0 })), links: keptLinks };
  }, [graph, showDocuments]);

  const [positions, moveNode] = useForceLayout(nodes, links);

  // Fit the whole graph in the canvas until the user zooms or pans.
  const fitView = useMemo(() => {
    const points = Object.values(positions);
    if (!points.length) return { x: 0, y: 0, scale: 1 };
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    points.forEach((p) => {
      minX = Math.min(minX, p.x); maxX = Math.max(maxX, p.x);
      minY = Math.min(minY, p.y); maxY = Math.max(maxY, p.y);
    });
    const pad = 60;
    const scale = Math.min(2.2, WIDTH / (maxX - minX + pad * 2), HEIGHT / (maxY - minY + pad * 2));
    return { scale, x: WIDTH / 2 - ((minX + maxX) / 2) * scale, y: HEIGHT / 2 - ((minY + maxY) / 2) * scale };
  }, [positions]);
  const view = userView || fitView;
  const setView = (next) => setUserView(typeof next === "function" ? next(view) : next);
  // Keep text and dots a constant on-screen size regardless of zoom and panel width.
  const screen = unitsPerPx / view.scale;

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg || typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(() => {
      const width = svg.getBoundingClientRect().width;
      if (width) setUnitsPerPx(WIDTH / width);
    });
    observer.observe(svg);
    return () => observer.disconnect();
  });
  const nodesById = useMemo(() => Object.fromEntries(nodes.map((node) => [node.id, node])), [nodes]);
  const typeCounts = useMemo(() => {
    const counts = {};
    nodes.forEach((node) => {
      counts[node.type] = (counts[node.type] || 0) + 1;
    });
    return Object.entries(counts).sort((a, b) => b[1] - a[1]);
  }, [nodes]);

  const needle = search.trim().toLowerCase();
  const matches = useMemo(
    () => (needle ? new Set(nodes.filter((node) => node.name.toLowerCase().includes(needle)).map((node) => node.id)) : null),
    [nodes, needle]
  );
  const focusId = hoverId || selectedId;
  const neighbors = useMemo(() => {
    if (!focusId) return null;
    const set = new Set([focusId]);
    links.forEach((link) => {
      if (link.source === focusId) set.add(link.target);
      if (link.target === focusId) set.add(link.source);
    });
    return set;
  }, [focusId, links]);
  const selected = selectedId ? nodesById[selectedId] : null;
  const connections = useMemo(
    () =>
      selected
        ? links
            .filter((link) => link.source === selected.id || link.target === selected.id)
            .map((link) => {
              const outgoing = link.source === selected.id;
              return { relation: humanize(link.relation), outgoing, other: nodesById[outgoing ? link.target : link.source] };
            })
            .filter((item) => item.other)
        : [],
    [selected, links, nodesById]
  );

  const toGraphPoint = (event) => {
    const rect = svgRef.current.getBoundingClientRect();
    const sx = ((event.clientX - rect.left) / rect.width) * WIDTH;
    const sy = ((event.clientY - rect.top) / rect.height) * HEIGHT;
    return { x: (sx - view.x) / view.scale, y: (sy - view.y) / view.scale, sx, sy };
  };

  const onWheel = (event) => {
    event.preventDefault();
    const { sx, sy } = toGraphPoint(event);
    const factor = event.deltaY < 0 ? 1.12 : 1 / 1.12;
    setView((v) => {
      const scale = Math.min(4, Math.max(0.25, v.scale * factor));
      return { scale, x: sx - ((sx - v.x) * scale) / v.scale, y: sy - ((sy - v.y) * scale) / v.scale };
    });
  };

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return undefined;
    svg.addEventListener("wheel", onWheel, { passive: false });
    return () => svg.removeEventListener("wheel", onWheel);
  });

  const onPointerDown = (event, nodeId = null) => {
    event.stopPropagation();
    const point = toGraphPoint(event);
    dragRef.current = { nodeId, start: point, view: { ...view }, moved: false };
    svgRef.current.setPointerCapture?.(event.pointerId);
  };

  const onPointerMove = (event) => {
    const drag = dragRef.current;
    if (!drag) return;
    const point = toGraphPoint(event);
    if (Math.abs(point.sx - drag.start.sx) + Math.abs(point.sy - drag.start.sy) > 3) drag.moved = true;
    if (drag.nodeId) {
      moveNode(drag.nodeId, point.x, point.y);
    } else {
      setView({ ...drag.view, x: drag.view.x + (point.sx - drag.start.sx), y: drag.view.y + (point.sy - drag.start.sy) });
    }
  };

  const onPointerUp = () => {
    const drag = dragRef.current;
    dragRef.current = null;
    if (!drag || drag.moved) return;
    setSelectedId(drag.nodeId);
  };

  const showAllLabels = nodes.length <= 40;

  return (
    <div className="page">
      <PageHeader
        title="Memory Graph"
        subtitle="The main cognee knowledge graph. Sessions appear here after they merge."
        actions={<button className="btn btn-primary" onClick={load} disabled={loading}>{loading ? "Loading…" : "Refresh"}</button>}
      />

      {error ? <Notice kind="error">{error}</Notice> : null}

      <section className="glass-card">
        <div className="actions graph-controls">
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Find a node…" />
          <label className="chip-row">
            <input type="checkbox" checked={showDocuments} onChange={(e) => setShowDocuments(e.target.checked)} />
            Show documents, chunks &amp; summaries
          </label>
          <label className="graph-inline-field">
            Max nodes
            <select value={maxNodes} onChange={(e) => setMaxNodes(Number(e.target.value))}>
              {[100, 300, 1000].map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
          </label>
          <button className="btn btn-ghost btn-sm" onClick={() => setUserView(null)} disabled={!userView}>Fit to view</button>
          <span className="lede">{nodes.length} nodes · {links.length} links{graph?.dataset_name ? ` · dataset ${graph.dataset_name}` : ""}</span>
        </div>
        <div className="chip-row graph-legend">
          {typeCounts.map(([type, count]) => (
            <span key={type} className="graph-legend-item">
              <span className="graph-legend-dot" style={{ background: colorFor(type) }} />
              {humanize(type)} ({count})
            </span>
          ))}
        </div>
      </section>

      {loading && !graph ? (
        <Spinner label="Loading the memory graph..." />
      ) : graph && graph.available === false ? (
        <Notice kind="error">Long-term memory is unavailable: {graph.error || "cognee is not available"}</Notice>
      ) : nodes.length === 0 ? (
        <EmptyState
          title="The main graph is empty"
          body="Chat with the assistant about things worth remembering, then use Save to memory now in Chat (or wait for the chat to go idle)."
        />
      ) : (
        <div className="graph-layout">
          <section className="glass-card graph-canvas">
            <svg
              ref={svgRef}
              viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
              role="img"
              aria-label="Memory knowledge graph"
              onPointerDown={(e) => onPointerDown(e, null)}
              onPointerMove={onPointerMove}
              onPointerUp={onPointerUp}
              onPointerLeave={() => { dragRef.current = null; }}
            >
              <g transform={`translate(${view.x} ${view.y}) scale(${view.scale})`}>
                {links.map((link, index) => {
                  const a = positions[link.source];
                  const b = positions[link.target];
                  if (!a || !b) return null;
                  const active = focusId && (link.source === focusId || link.target === focusId);
                  const dimmed = focusId && !active;
                  return (
                    <g key={`${link.source}-${link.target}-${index}`} opacity={dimmed ? 0.12 : 1}>
                      <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} strokeWidth={(active ? 2 : 1.2) * screen} className={`graph-link ${active ? "active" : ""}`} />
                      {active ? (
                        <text
                          x={(a.x + b.x) / 2}
                          y={(a.y + b.y) / 2 - 4 * screen}
                          fontSize={11 * screen}
                          strokeWidth={3 * screen}
                          className="graph-link-label"
                          textAnchor="middle"
                        >
                          {humanize(link.relation)}
                        </text>
                      ) : null}
                    </g>
                  );
                })}
                {nodes.map((node) => {
                  const p = positions[node.id];
                  if (!p) return null;
                  const r = radiusFor(node) * screen;
                  const dimmed = (neighbors && !neighbors.has(node.id)) || (matches && !matches.has(node.id));
                  const emphasised = node.id === selectedId || (matches && matches.has(node.id));
                  const showLabel = showAllLabels || node.degree >= 3 || (neighbors && neighbors.has(node.id)) || (matches && matches.has(node.id));
                  return (
                    <g
                      key={node.id}
                      transform={`translate(${p.x} ${p.y})`}
                      opacity={dimmed ? 0.18 : 1}
                      className="graph-node"
                      onPointerDown={(e) => onPointerDown(e, node.id)}
                      onPointerEnter={() => setHoverId(node.id)}
                      onPointerLeave={() => setHoverId(null)}
                    >
                      <circle r={r} fill={colorFor(node.type)} strokeWidth={(emphasised ? 2.5 : 1.5) * screen} className={emphasised ? "selected" : ""} />
                      {showLabel ? (
                        <text
                          y={r + 13 * screen}
                          textAnchor="middle"
                          fontSize={12 * screen}
                          strokeWidth={3 * screen}
                          className={`graph-node-label ${DOCUMENT_TYPES.has(node.type) ? "muted" : ""}`}
                        >
                          {node.name.length > 32 ? `${node.name.slice(0, 30)}…` : node.name}
                        </text>
                      ) : null}
                      <title>{`${node.name} (${humanize(node.type)})`}</title>
                    </g>
                  );
                })}
              </g>
            </svg>
            <div className="lede graph-hint">Scroll to zoom · drag the background to pan · drag a node to move it · click a node for details</div>
          </section>

          <aside className="glass-card graph-details">
            {selected ? (
              <>
                <div className="graph-details-type">
                  <span className="graph-legend-dot" style={{ background: colorFor(selected.type) }} />
                  {humanize(selected.type)}
                </div>
                <h3>{selected.name}</h3>
                {selected.detail ? <p className="lede">{selected.detail}</p> : null}
                <h4>Connections ({connections.length})</h4>
                {connections.length === 0 ? <div className="lede">No connections in this view.</div> : null}
                <ul className="graph-connections">
                  {connections.map((item, index) => (
                    <li key={index}>
                      <span className="lede">{item.outgoing ? item.relation : `← ${item.relation}`}</span>{" "}
                      <button className="btn btn-ghost btn-sm" onClick={() => setSelectedId(item.other.id)}>{item.other.name}</button>
                    </li>
                  ))}
                </ul>
                <button className="btn btn-ghost btn-sm" onClick={() => setSelectedId(null)}>Clear selection</button>
              </>
            ) : (
              <div className="lede">Click a node to see what the assistant knows about it and how it connects to the rest of the graph.</div>
            )}
          </aside>
        </div>
      )}
    </div>
  );
}

if (typeof window !== "undefined") {
  window.MemoryGraphCockpit = MemoryGraphCockpit;
}
