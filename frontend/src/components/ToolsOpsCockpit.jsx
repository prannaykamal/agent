import React, { useEffect, useState } from "react";
import { api } from "../api/client.js";
import PageHeader from "./ui/PageHeader.jsx";
import Notice from "./ui/Notice.jsx";
import Spinner from "./ui/Spinner.jsx";
import Badge from "./ui/Badge.jsx";
import { statusTone } from "../lib/format.js";

function Empty({ children }) {
  return <div className="lede">{children}</div>;
}

export default function ToolsOpsCockpit() {
  const [toolsStatus, setToolsStatus] = useState(null);
  const [overview, setOverview] = useState(null);
  const [providers, setProviders] = useState([]);
  const [externalProviders, setExternalProviders] = useState([]);
  const [providerConfigs, setProviderConfigs] = useState([]);
  const [configDrafts, setConfigDrafts] = useState({});
  const [configBusyProviderId, setConfigBusyProviderId] = useState(null);
  const [personalStatus, setPersonalStatus] = useState(null);
  const [personalActions, setPersonalActions] = useState([]);
  const [personalAudit, setPersonalAudit] = useState([]);
  const [cronSchedules, setCronSchedules] = useState([]);
  const [cronRuns, setCronRuns] = useState([]);
  const [selectedProviderDetail, setSelectedProviderDetail] = useState(null);
  const [refreshingProviderId, setRefreshingProviderId] = useState(null);
  const [notice, setNotice] = useState(null);
  const [activeSubTab, setActiveSubTab] = useState("overview");
  const [callsList, setCallsList] = useState([]);
  const [resultsList, setResultsList] = useState([]);
  const [auditList, setAuditList] = useState([]);
  const [blockedList, setBlockedList] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const [
        statusData,
        overviewData,
        providersData,
        externalProvidersData,
        providerConfigsData,
        personalStatusData,
        personalActionsData,
        personalAuditData,
        schedulesData,
        runsData,
      ] = await Promise.all([
        api.get("/api/tools/status"),
        api.get("/api/tools/observability/overview"),
        api.get("/api/tools/mcp/providers"),
        api.get("/api/tools/external/providers"),
        api.get("/api/config/providers"),
        api.get("/api/tools/personal-os/status"),
        api.get("/api/tools/personal-os/actions"),
        api.get("/api/tools/personal-os/audit"),
        api.get("/api/tools/cron/schedules"),
        api.get("/api/tools/cron/runs?limit=20"),
      ]);
      setToolsStatus(statusData);
      setOverview(overviewData);
      setProviders((providersData.providers || []).map((p) => ({ ...p, provider_layer: "mcp" })));
      setExternalProviders((externalProvidersData.providers || []).map((p) => ({ ...p, provider_layer: "external_api" })));
      setProviderConfigs(providerConfigsData.providers || []);
      setPersonalStatus(personalStatusData);
      setPersonalActions(personalActionsData.actions || []);
      setPersonalAudit(personalAuditData.audit_events || []);
      setCronSchedules(schedulesData.schedules || []);
      setCronRuns(runsData.runs || []);
    } catch (e) {
      setError(e.message || "Failed to load Tools Ops");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const loadStandaloneObservability = async (tab) => {
    setActiveSubTab(tab);
    setError(null);
    try {
      if (tab === "calls") {
        const data = await api.get("/api/tools/observability/calls?limit=50");
        setCallsList(data.tool_calls || []);
      } else if (tab === "results") {
        const data = await api.get("/api/tools/observability/results?limit=50");
        setResultsList(data.tool_results || []);
      } else if (tab === "audit") {
        const data = await api.get("/api/tools/observability/audit?limit=50");
        setAuditList(data.audit_events || []);
      } else if (tab === "blocked") {
        const data = await api.get("/api/tools/observability/blocked?limit=50");
        setBlockedList(data.blocked_attempts || []);
      }
    } catch (e) {
      setError(`Failed to fetch ${tab}: ${e.message}`);
    }
  };

  const handleInspectProvider = async (providerId, providerLayer = "mcp") => {
    setError(null);
    try {
      const endpoint = providerLayer === "external_api"
        ? `/api/tools/external/providers/${providerId}`
        : `/api/tools/mcp/providers/${providerId}`;
      const data = await api.get(endpoint);
      setSelectedProviderDetail({ ...data, provider_layer: providerLayer });
    } catch (e) {
      setError(`Failed to inspect provider '${providerId}': ${e.message}`);
    }
  };

  const handleSafeDiscoverRefresh = async (providerId) => {
    if (providerId === "whatsapp_api" || providerId === "telegram_bot_api") {
      setNotice(`'${providerId}' is a direct API provider; MCP discovery is not applicable.`);
      return;
    }
    setRefreshingProviderId(providerId);
    setError(null);
    setNotice(null);
    try {
      const data = await api.post(`/api/tools/mcp/providers/${providerId}/discover`);
      setNotice(`Metadata discovery refreshed for '${providerId}'. Status: ${data.availability_status}`);
      if (selectedProviderDetail && selectedProviderDetail.provider_id === providerId) {
        setSelectedProviderDetail(data);
      }
      load();
    } catch (e) {
      setError(`Discovery refresh failed for '${providerId}': ${e.message}`);
    } finally {
      setRefreshingProviderId(null);
    }
  };

  const handleValidateProviderStatus = async (providerId) => {
    setRefreshingProviderId(providerId);
    setError(null);
    setNotice(null);
    try {
      const data = await api.get(`/api/tools/external/providers/${providerId}`);
      setSelectedProviderDetail({ ...data, provider_layer: "external_api" });
      setNotice(`Status validated for '${providerId}'. Availability: ${data.availability_status}`);
      load();
    } catch (e) {
      setError(`Status validation failed for '${providerId}': ${e.message}`);
    } finally {
      setRefreshingProviderId(null);
    }
  };

  const updateConfigDraft = (providerId, field, value) => {
    setConfigDrafts((prev) => ({
      ...prev,
      [providerId]: {
        ...(prev[providerId] || {}),
        [field.name]: field.type === "boolean" ? Boolean(value) : value,
      },
    }));
  };

  const configValueForSubmit = (field, value) => {
    if (field.type === "array") {
      return String(value || "").split(",").map((item) => item.trim()).filter(Boolean);
    }
    return field.type === "boolean" ? Boolean(value) : value;
  };

  const handleSaveProviderConfig = async (provider) => {
    setConfigBusyProviderId(provider.provider_id);
    setError(null);
    setNotice(null);
    try {
      const draft = configDrafts[provider.provider_id] || {};
      const values = {};
      (provider.fields || []).forEach((field) => {
        if (Object.prototype.hasOwnProperty.call(draft, field.name)) {
          values[field.name] = configValueForSubmit(field, draft[field.name]);
        }
      });
      const data = await api.post(`/api/config/providers/${provider.provider_id}`, { values });
      setProviderConfigs((prev) => prev.map((item) => (item.provider_id === provider.provider_id ? data : item)));
      setConfigDrafts((prev) => ({ ...prev, [provider.provider_id]: {} }));
      setNotice(`Configuration saved for '${provider.provider_id}'. Secrets remain hidden.`);
      load();
    } catch (e) {
      setError(`Configuration save failed for '${provider.provider_id}': ${e.message}`);
    } finally {
      setConfigBusyProviderId(null);
    }
  };

  const handleValidateProviderConfig = async (providerId) => {
    setConfigBusyProviderId(providerId);
    setError(null);
    setNotice(null);
    try {
      const data = await api.post(`/api/config/providers/${providerId}/validate`);
      setProviderConfigs((prev) => prev.map((item) => (item.provider_id === providerId ? data : item)));
      setNotice(`Validation completed for '${providerId}'. Status: ${data.validation_status}`);
      load();
    } catch (e) {
      setError(`Validation failed for '${providerId}': ${e.message}`);
    } finally {
      setConfigBusyProviderId(null);
    }
  };

  const handleClearProviderSecret = async (providerId) => {
    setConfigBusyProviderId(providerId);
    setError(null);
    setNotice(null);
    try {
      const data = await api.delete(`/api/config/providers/${providerId}/secret`);
      setProviderConfigs((prev) => prev.map((item) => (item.provider_id === providerId ? data : item)));
      setNotice(`Stored secret fields cleared for '${providerId}'.`);
      load();
    } catch (e) {
      setError(`Clear secret failed for '${providerId}': ${e.message}`);
    } finally {
      setConfigBusyProviderId(null);
    }
  };

  const allProviders = [...providers, ...externalProviders];
  const calls = overview?.tool_calls?.tool_calls || [];
  const results = overview?.tool_results?.tool_results || [];
  const blocked = overview?.blocked?.blocked_attempts || [];
  const policyEntries = overview?.policy?.entries || [];

  return (
    <div className="page">
      <PageHeader
        title="Tools Ops"
        subtitle={`Status: ${toolsStatus?.status || "OK"}`}
        actions={<button className="btn btn-primary" onClick={load}>Refresh</button>}
      />

      {notice ? <Notice kind="ok">{notice}</Notice> : null}
      {error ? <Notice kind="error">{error}</Notice> : null}

      {loading ? <Spinner label="Loading tools observability & provider registry..." /> : (
        <>
          <div className="metric-grid">
            <div className="metric-card">
              <h4>Bindable Tools</h4>
              <div className="metric-value">{toolsStatus?.registry?.total_bindable_tools || 0}</div>
              <div className="metric-meta">OS: {toolsStatus?.registry?.group_counts?.personal_os || 0} | MCP: {toolsStatus?.registry?.group_counts?.mcp || 0} | API: {toolsStatus?.registry?.group_counts?.external_api || 0}</div>
            </div>
            <div className="metric-card">
              <h4>Providers</h4>
              <div className="metric-value">{toolsStatus?.providers?.available_providers || 0}/{toolsStatus?.providers?.total_providers || 0}</div>
              <div className="metric-meta">Available</div>
            </div>
            <div className="metric-card">
              <h4>Policy Classifications</h4>
              <div className="metric-value">{policyEntries.length}</div>
              <div className="metric-meta">Classified Rules</div>
            </div>
            <div className="metric-card">
              <h4>Removed Tools</h4>
              <div className="metric-value">{toolsStatus?.removed_tools?.total || 0}</div>
              <div className="metric-meta">Active Blocked: {toolsStatus?.removed_tools?.active || 0}</div>
            </div>
          </div>

          {selectedProviderDetail ? (
            <section className="glass-card">
              <div className="card-head">
                <h3><code>{selectedProviderDetail.provider_id}</code></h3>
                <div className="actions">
                  <Badge value={selectedProviderDetail.availability_status} />
                  <button className="btn btn-ghost btn-sm" onClick={() => setSelectedProviderDetail(null)}>Close</button>
                </div>
              </div>
              <div className="provider-grid">
                <div>Display Name: <strong>{selectedProviderDetail.display_name || selectedProviderDetail.provider_id}</strong></div>
                <div>Transport: <code>{selectedProviderDetail.transport_type || selectedProviderDetail.transport || "stdio"}</code></div>
                <div>Credential Status: <Badge value={selectedProviderDetail.credential_status} /></div>
                <div>Discovery Status: <Badge value={selectedProviderDetail.discovery_status} /></div>
                <div>Enabled: <strong>{selectedProviderDetail.enabled ? "Yes" : "No"}</strong></div>
                <div>Tool Count: <strong>{selectedProviderDetail.tool_count || 0}</strong></div>
              </div>
              {selectedProviderDetail.last_error ? <Notice kind="error"><strong>Last Error:</strong> {selectedProviderDetail.last_error}</Notice> : null}
              {selectedProviderDetail.tools?.length ? (
                <div style={{ marginTop: 12 }} className="provider-grid">
                  {selectedProviderDetail.tools.map((t) => (
                    <div key={t.tool_id} className="provider-card">
                      <code>{t.tool_id}</code>
                      <span className="lede">Provider Managed: {t.provider_managed ? "Yes" : "No"}</span>
                    </div>
                  ))}
                </div>
              ) : null}
              <div className="actions" style={{ marginTop: 14 }}>
                <span className="lede">Secrets and raw credentials are redacted in status inspection.</span>
                {selectedProviderDetail.provider_layer === "external_api" ? (
                  <button className="btn btn-primary btn-sm" disabled={refreshingProviderId === selectedProviderDetail.provider_id} onClick={() => handleValidateProviderStatus(selectedProviderDetail.provider_id)}>
                    {refreshingProviderId === selectedProviderDetail.provider_id ? "Validating..." : "Validate Status"}
                  </button>
                ) : (
                  <button className="btn btn-primary btn-sm" disabled={refreshingProviderId === selectedProviderDetail.provider_id} onClick={() => handleSafeDiscoverRefresh(selectedProviderDetail.provider_id)}>
                    {refreshingProviderId === selectedProviderDetail.provider_id ? "Refreshing..." : "Refresh Metadata"}
                  </button>
                )}
              </div>
            </section>
          ) : null}

          <section className="glass-card">
            <h3>Providers</h3>
            {allProviders.length === 0 ? <Empty>No provider status available.</Empty> : allProviders.map((provider) => (
              <div key={provider.provider_id} className={`row-card is-${statusTone(provider.availability_status)}`}>
                <div>
                  <strong>{provider.display_name}</strong> <code>({provider.provider_id})</code>
                  <div className="lede">
                    Layer: <code>{provider.provider_layer === "external_api" ? "Direct API" : "MCP"}</code> | Transport: <code>{provider.transport_type || "external_api"}</code> | Credentials: <Badge value={provider.credential_status} />
                  </div>
                  {provider.last_error ? <div className="notice notice-error">{provider.last_error}</div> : null}
                </div>
                <div className="actions">
                  <Badge value={provider.availability_status} />
                  {provider.discovery_status ? <Badge value={provider.discovery_status} /> : null}
                  <span className="lede">{provider.tool_count ?? (provider.capabilities?.length || 0)} tools</span>
                  <button className="btn btn-ghost btn-sm" onClick={() => handleInspectProvider(provider.provider_id, provider.provider_layer)}>Inspect</button>
                  {provider.provider_layer === "external_api" ? (
                    <button className="btn btn-primary btn-sm" disabled={refreshingProviderId === provider.provider_id} onClick={() => handleValidateProviderStatus(provider.provider_id)}>
                      {refreshingProviderId === provider.provider_id ? "Validating..." : "Validate Status"}
                    </button>
                  ) : (
                    <button className="btn btn-primary btn-sm" disabled={refreshingProviderId === provider.provider_id} onClick={() => handleSafeDiscoverRefresh(provider.provider_id)}>
                      {refreshingProviderId === provider.provider_id ? "Refreshing..." : "Refresh Metadata"}
                    </button>
                  )}
                </div>
              </div>
            ))}
          </section>

          <section className="glass-card">
            <h3>Configuration</h3>
            {providerConfigs.length === 0 ? <Empty>No provider configuration definitions available.</Empty> : providerConfigs.map((provider) => {
              const draft = configDrafts[provider.provider_id] || {};
              const busy = configBusyProviderId === provider.provider_id;
              return (
                <div key={provider.provider_id} className="row-card" style={{ flexDirection: "column", alignItems: "stretch" }}>
                  <div className="actions" style={{ justifyContent: "space-between" }}>
                    <div>
                      <strong>{provider.display_name}</strong> <code>({provider.provider_id})</code>
                      <div className="lede">Type: <code>{provider.provider_type}</code> | Configured: <Badge value={provider.configured ? "configured" : "missing_config"} /> | Validation: <Badge value={provider.validation_status} /></div>
                      {provider.validation_error ? <div className="notice notice-error">Validation error: {provider.validation_error}</div> : null}
                    </div>
                    <div className="actions">
                      <button className="btn btn-primary btn-sm" disabled={busy} onClick={() => handleSaveProviderConfig(provider)}>{busy ? "Saving..." : "Save"}</button>
                      <button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => handleValidateProviderConfig(provider.provider_id)}>Validate</button>
                      <button className="btn btn-danger btn-sm" disabled={busy} onClick={() => handleClearProviderSecret(provider.provider_id)}>Clear Secret</button>
                    </div>
                  </div>
                  <div className="form-grid">
                    {(provider.fields || []).map((field) => {
                      const savedValue = provider.saved_values?.[field.name];
                      const value = draft[field.name] ?? "";
                      if (field.type === "boolean") {
                        const checked = Object.prototype.hasOwnProperty.call(draft, field.name) ? Boolean(draft[field.name]) : Boolean(savedValue);
                        return (
                          <label key={field.name} className="chip-row">
                            <input type="checkbox" checked={checked} onChange={(e) => updateConfigDraft(provider.provider_id, field, e.target.checked)} />
                            {field.label}
                          </label>
                        );
                      }
                      return (
                        <label key={field.name} className="field">
                          <span>{field.label}{field.required ? " *" : ""}</span>
                          <input
                            type={field.secret ? "password" : "text"}
                            value={value}
                            placeholder={field.secret && savedValue ? "Stored secret hidden" : String(savedValue || "")}
                            onChange={(e) => updateConfigDraft(provider.provider_id, field, e.target.value)}
                          />
                          {savedValue ? <span className="lede">Saved: {String(savedValue)}</span> : null}
                        </label>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </section>

          <section className="glass-card">
            <div className="tabs">
              {[
                { id: "overview", label: "Overview" },
                { id: "calls", label: "Tool Calls" },
                { id: "results", label: "Tool Results" },
                { id: "audit", label: "Personal OS Audit" },
                { id: "blocked", label: "Blocked Attempts" },
              ].map((tab) => (
                <button
                  key={tab.id}
                  className={`tab ${activeSubTab === tab.id ? "active" : ""}`}
                  onClick={() => {
                    if (tab.id === "overview") setActiveSubTab("overview");
                    else loadStandaloneObservability(tab.id);
                  }}
                >
                  {tab.label}
                </button>
              ))}
            </div>

            {activeSubTab === "overview" && (
              <div className="provider-grid" style={{ marginTop: 12 }}>
                <div>
                  <h4>Recent Calls</h4>
                  {calls.length === 0 ? <Empty>No tool calls logged.</Empty> : calls.slice(0, 6).map((call) => <div key={call.id} className="row-card">{call.tool_name} <Badge value={call.status} /></div>)}
                </div>
                <div>
                  <h4>Recent Results</h4>
                  {results.length === 0 ? <Empty>No tool results logged.</Empty> : results.slice(0, 6).map((result) => <div key={result.id} className="row-card">{result.tool_name} <Badge value={result.status} /></div>)}
                </div>
                <div>
                  <h4>Blocked Attempts</h4>
                  {blocked.length === 0 ? <Empty>No blocked attempts logged.</Empty> : blocked.slice(0, 6).map((item) => <div key={item.id} className="row-card">{item.tool_name} <Badge value={item.action || item.risk_level} /></div>)}
                </div>
              </div>
            )}

            {activeSubTab === "calls" && (
              callsList.length === 0 ? <Empty>No standalone tool calls found.</Empty> : callsList.map((item) => (
                <div key={item.id} className="row-card"><div><strong>{item.tool_name}</strong> | Session: <code>{item.session_id}</code></div><Badge value={item.status} /></div>
              ))
            )}
            {activeSubTab === "results" && (
              resultsList.length === 0 ? <Empty>No standalone tool results found.</Empty> : resultsList.map((item) => (
                <div key={item.id} className="row-card"><div><strong>{item.tool_name}</strong> | Session: <code>{item.session_id}</code></div><Badge value={item.status} /></div>
              ))
            )}
            {activeSubTab === "audit" && (
              auditList.length === 0 ? <Empty>No audit events found.</Empty> : auditList.map((item) => (
                <div key={item.id} className="row-card"><div><strong>{item.action}</strong><div className="lede">{item.reason}</div></div><Badge value={item.outcome} /></div>
              ))
            )}
            {activeSubTab === "blocked" && (
              blockedList.length === 0 ? <Empty>No blocked attempts found.</Empty> : blockedList.map((item) => (
                <div key={item.id} className="row-card"><div><strong>{item.tool_name}</strong><div className="lede">{item.reason}</div></div><Badge value={item.action || item.risk_level} /></div>
              ))
            )}
          </section>

          <section className="glass-card">
            <h3>OS actions</h3>
            <div className="chip-row" style={{ marginBottom: 10 }}>
              <Badge value={personalStatus?.status} />
              <span>{personalActions.length} bounded actions</span>
              <span>{personalAudit.length} recent audit events</span>
              <span>{cronSchedules.length} schedules / {cronRuns.length} recent runs</span>
            </div>
            <div className="provider-grid">
              {personalActions.slice(0, 8).map((action) => (
                <div key={action.tool_id} className="provider-card">
                  <strong>{action.legacy_name}</strong>
                  <div className="lede">{action.category} | {action.approval_policy}</div>
                </div>
              ))}
            </div>
          </section>

          <section className="glass-card">
            <h3>Policy</h3>
            {policyEntries.length === 0 ? <Empty>No policy metadata available.</Empty> : policyEntries.slice(0, 16).map((entry) => (
              <div key={entry.tool_id} className="row-card">
                <strong>{entry.legacy_name}</strong>
                <span>{entry.provider}</span>
                <Badge value={entry.risk_class} />
                <Badge value={entry.policy_decision} />
              </div>
            ))}
          </section>
        </>
      )}
    </div>
  );
}

if (typeof window !== "undefined") {
  window.ToolsOpsCockpit = ToolsOpsCockpit;
}
