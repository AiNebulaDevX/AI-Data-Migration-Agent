import { useCallback, useEffect, useMemo, useState } from "react";
import "./App.css";

const API = import.meta.env.VITE_API_URL || "http://localhost:8000/api";

type Migration = {
  id: string;
  status: string;
  stats: {
    files_ingested: number;
    total_source_rows: number;
    records_processed: number;
    records_cleaned: number;
    auto_mapped_fields: number;
    escalations_open: number;
    target_success: number;
    target_failed: number;
    progress_percent: number;
  };
};

type Escalation = {
  id: number;
  status: string;
  escalation_type: string;
  record_id?: string;
  field?: string;
  source_value?: string;
  reason: string;
  confidence: number;
  recommended_action: string;
  possible_consequences: string;
  candidates?: { target_field: string; confidence: number; reasons: string[] }[];
};

type RecordRow = {
  employee_id: string;
  data: {
    first_name?: string;
    last_name?: string;
    email?: string;
    department?: string;
    job_title?: string;
    hire_date?: string;
  };
  validation_status: string;
  target_status: string;
  retry_count: number;
};

type Activity = { timestamp: string; message: string; level: string };
type AuditEntry = {
  timestamp: string;
  action: string;
  actor: string;
  record_id?: string;
  details: Record<string, unknown>;
};
type SourceFile = { filename: string; row_count: number; columns: string[] };

const SOURCE_ACCEPT = ".csv,.xlsx,.xls";
const DEMO_SOURCE_FILES = ["employees_hr.csv", "employees_legacy.csv", "employees_compensation.csv"];

function isSourceExtension(name: string): boolean {
  const lower = name.toLowerCase();
  return lower.endsWith(".csv") || lower.endsWith(".xlsx") || lower.endsWith(".xls");
}

const NAV = [
  { id: "Dashboard", icon: "▦", label: "Dashboard" },
  { id: "Files", icon: "📁", label: "Source Files" },
  { id: "Agent Activity", icon: "⚡", label: "Agent Activity" },
  { id: "Escalations", icon: "⚠", label: "Escalations" },
  { id: "Records", icon: "👥", label: "Records" },
  { id: "Audit Log", icon: "📋", label: "Audit Log" },
] as const;

type Tab = (typeof NAV)[number]["id"];

function statusBadgeClass(status: string): string {
  const s = status.toLowerCase();
  if (s === "completed") return "badge-completed";
  if (s === "waiting_human") return "badge-waiting";
  if (s === "rolled_back" || s === "failed") return "badge-failed";
  if (s === "idle" || s === "created") return "badge-idle";
  return "badge-running";
}

function targetBadgeClass(status: string): string {
  const s = status.toLowerCase();
  if (s === "success") return "badge-success";
  if (s === "failed") return "badge-invalid";
  if (s === "retrying") return "badge-retrying";
  return "badge-pending";
}

function escTypeClass(type: string): string {
  if (type.includes("MAPPING")) return "mapping";
  if (type.includes("VALIDATION")) return "validation";
  if (type.includes("CONFLICT")) return "conflict";
  return "";
}

function escCardClass(type: string): string {
  if (type.includes("MAPPING")) return "type-mapping";
  if (type.includes("VALIDATION")) return "type-validation";
  if (type.includes("CONFLICT")) return "type-conflict";
  if (type.includes("TARGET")) return "type-target";
  return "";
}

function fmtStatus(s: string) {
  return s.replace(/_/g, " ");
}

function fmtTime(ts: string) {
  return new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function App() {
  const [tab, setTab] = useState<Tab>("Dashboard");
  const [migrationId, setMigrationId] = useState<string | null>(localStorage.getItem("migrationId"));
  const [migration, setMigration] = useState<Migration | null>(null);
  const [activity, setActivity] = useState<Activity[]>([]);
  const [escalations, setEscalations] = useState<Escalation[]>([]);
  const [records, setRecords] = useState<RecordRow[]>([]);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [files, setFiles] = useState<SourceFile[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);

  const showToast = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 3500);
  };

  const refresh = useCallback(async () => {
    if (!migrationId) return;
    try {
      const [m, a, e, r, au, f] = await Promise.all([
        fetch(`${API}/migrations/${migrationId}`).then((x) => {
          if (!x.ok) throw new Error(`Migration not found: ${x.status}`);
          return x.json();
        }),
        fetch(`${API}/migrations/${migrationId}/activity`).then((x) => x.json()),
        fetch(`${API}/migrations/${migrationId}/escalations`).then((x) => x.json()),
        fetch(`${API}/migrations/${migrationId}/records`).then((x) => x.json()),
        fetch(`${API}/migrations/${migrationId}/audit`).then((x) => x.json()),
        fetch(`${API}/migrations/${migrationId}/files`).then((x) => x.json()),
      ]);
      setMigration(m);
      setActivity(a);
      setEscalations(e);
      setRecords(r);
      setAudit(au);
      setFiles(f);
      setError(null);
    } catch (err) {
      if (String(err).includes("404") || String(err).includes("not found")) {
        localStorage.removeItem("migrationId");
        setMigrationId(null);
        setError(null);
      } else {
        setError(String(err));
      }
    }
  }, [migrationId]);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 2000);
    return () => clearInterval(t);
  }, [refresh]);

  useEffect(() => {
    if (!migrationId) return;
    const es = new EventSource(`${API}/migrations/${migrationId}/activity/stream`);
    es.onmessage = (ev) => {
      try {
        const item = JSON.parse(ev.data) as Activity;
        setActivity((prev) => [...prev.slice(-100), item]);
      } catch {
        /* ignore parse errors */
      }
    };
    es.onerror = () => es.close();
    return () => es.close();
  }, [migrationId]);

  const uploadSourceFiles = async (files: File[]): Promise<string[]> => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    const res = await fetch(`${API}/upload`, { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(typeof data.detail === "string" ? data.detail : data.message || "Upload failed");
    }
    return data.filenames as string[];
  };

  const beginMigration = async (body: {
    demo_mode?: boolean;
    uploaded_files?: string[];
    filenames?: string[];
  }) => {
    const res = await fetch(`${API}/migrations`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(typeof data.detail === "string" ? data.detail : "Failed to start migration");
    }
    setMigrationId(data.migration_id);
    localStorage.setItem("migrationId", data.migration_id);
    showToast("Migration started — agent is analyzing source files");
  };

  const onSelectSourceFiles = (fileList: FileList | null) => {
    const picked = Array.from(fileList || []);
    const valid = picked.filter((f) => isSourceExtension(f.name));
    const rejected = picked.length - valid.length;
    if (rejected > 0) {
      showToast("Only CSV and Excel files (.csv, .xlsx, .xls) are supported");
    }
    setSelectedFiles(valid);
  };

  const startMigration = async () => {
    setLoading(true);
    setError(null);
    try {
      await beginMigration({ demo_mode: true, filenames: DEMO_SOURCE_FILES });
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  const startMigrationWithUpload = async () => {
    if (selectedFiles.length === 0) {
      showToast("Choose at least one CSV or Excel file");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const uploaded = await uploadSourceFiles(selectedFiles);
      await beginMigration({ demo_mode: true, uploaded_files: uploaded });
      setSelectedFiles([]);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  const resolve = async (id: number, decision: string, corrected_target_field?: string, corrected_value?: string) => {
    await fetch(`${API}/migrations/${migrationId}/escalations/${id}/resolve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision, corrected_target_field, corrected_value }),
    });
    showToast(`Escalation #${id} resolved — agent continuing`);
    refresh();
  };

  const rollback = async () => {
    if (!confirm("Rollback all records pushed to the target system for this migration?")) return;
    setLoading(true);
    try {
      const res = await fetch(`${API}/migrations/${migrationId}/rollback`, { method: "POST" });
      const data = await res.json();
      if (res.ok) {
        showToast(`Rollback complete — ${data.removed ?? 0} records removed from target`);
        refresh();
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  const resetAll = async () => {
    if (!confirm("Clear all migration data and start fresh?")) return;
    setLoading(true);
    try {
      await fetch(`${API}/reset-all`, { method: "POST" }).catch(() => undefined);
      localStorage.removeItem("migrationId");
      setMigrationId(null);
      setMigration(null);
      setActivity([]);
      setEscalations([]);
      setRecords([]);
      setAudit([]);
      setFiles([]);
      setSelectedFiles([]);
      setError(null);
      setTab("Dashboard");
      showToast("Workspace reset");
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  };

  const openEscalations = useMemo(() => escalations.filter((e) => e.status === "OPEN"), [escalations]);
  const agentStatus = migration?.status || "IDLE";
  const needsAttention = openEscalations.length > 0;

  const currentNav = NAV.find((n) => n.id === tab)!;

  return (
    <div className="app-shell">
      {/* ── Sidebar ── */}
      <aside className="sidebar">
        <div className="sidebar-brand">
          <div className="brand-icon">⬡</div>
          <div className="brand-text">
            <h1>DataMigrate AI</h1>
            <p>Enterprise Migration Platform</p>
          </div>
        </div>

        <nav className="sidebar-nav">
          {NAV.map((n) => (
            <button
              key={n.id}
              className={`nav-item${tab === n.id ? " active" : ""}${!migrationId && n.id !== "Dashboard" ? " disabled" : ""}`}
              onClick={() => migrationId && setTab(n.id)}
              disabled={!migrationId && n.id !== "Dashboard"}
            >
              <span className="nav-icon">{n.icon}</span>
              {n.label}
              {n.id === "Escalations" && openEscalations.length > 0 && (
                <span className="nav-badge">{openEscalations.length}</span>
              )}
            </button>
          ))}
        </nav>

        <div className="sidebar-footer">
          Autonomous agent with<br />human-in-the-loop escalation
        </div>
      </aside>

      {/* ── Main ── */}
      <div className="main-area">
        <header className="topbar">
          <div className="topbar-left">
            <h2>{currentNav.label}</h2>
            <p>
              {migrationId
                ? `Migration ${migrationId.slice(0, 16)}…`
                : "No active migration — start a demo to begin"}
            </p>
          </div>
          <div className="topbar-actions">
            {migrationId && (
              <span className="migration-chip">
                <span className="dot" />
                {migrationId.slice(0, 12)}
              </span>
            )}
            {!migrationId ? (
              <button className="btn btn-primary" onClick={startMigration} disabled={loading}>
                {loading ? "Starting…" : "Start Demo Migration"}
              </button>
            ) : (
              <>
                {needsAttention && (
                  <button className="btn btn-secondary" onClick={() => setTab("Escalations")}>
                    ⚠ {openEscalations.length} need review
                  </button>
                )}
                <button className="btn btn-danger btn-sm" onClick={rollback} disabled={loading}>
                  Rollback Target
                </button>
                <button className="btn btn-ghost btn-sm" onClick={resetAll} disabled={loading}>
                  Reset
                </button>
              </>
            )}
          </div>
        </header>

        <main className="content">
          {error && (
            <div className="alert alert-error">
              <span className="alert-icon">✕</span>
              <div>{error}</div>
            </div>
          )}

          {needsAttention && tab !== "Escalations" && migrationId && (
            <div className="attention-banner">
              <span>⚠</span>
              <span>
                <strong>{openEscalations.length} escalation{openEscalations.length > 1 ? "s" : ""}</strong> require your decision before the agent can continue.
              </span>
              <button className="btn btn-secondary btn-sm" onClick={() => setTab("Escalations")}>
                Review now
              </button>
            </div>
          )}

          {/* ── Welcome ── */}
          {!migrationId && (
            <div className="welcome">
              <div className="welcome-icon">⬡</div>
              <h2>Employee Data Migration</h2>
              <p>
                Autonomous AI agent that ingests HR, CRM, and legacy exports — maps schemas,
                cleans data, and pushes to your target system. You only intervene when confidence is low.
              </p>
              <div className="welcome-steps">
                <div className="step-card">
                  <div className="step-num">1</div>
                  <strong>Agent analyzes</strong>
                  <span>Ingests 3 source files and infers field mappings automatically</span>
                </div>
                <div className="step-card">
                  <div className="step-num">2</div>
                  <strong>You decide when needed</strong>
                  <span>Review escalations for ambiguous mappings or conflicting data</span>
                </div>
                <div className="step-card">
                  <div className="step-num">3</div>
                  <strong>Records pushed</strong>
                  <span>Validated employees sent to target API with full audit trail</span>
                </div>
              </div>
              <div className="upload-panel">
                <h3>Upload source files</h3>
                <p className="upload-hint">Select one or more CSV or Excel files — same as placing them in the backend <code>data/source</code> folder.</p>
                <label className="upload-drop">
                  <input
                    type="file"
                    multiple
                    accept={SOURCE_ACCEPT}
                    className="upload-input"
                    onChange={(e) => onSelectSourceFiles(e.target.files)}
                  />
                  <span className="upload-drop-title">Choose files or drag into the file picker</span>
                  <span className="upload-drop-sub">.csv · .xlsx · .xls</span>
                </label>
                {selectedFiles.length > 0 && (
                  <ul className="upload-file-list">
                    {selectedFiles.map((f) => (
                      <li key={`${f.name}-${f.size}`}>
                        <span>{f.name.endsWith(".xlsx") || f.name.endsWith(".xls") ? "📊" : "📄"}</span>
                        <span>{f.name}</span>
                        <span className="upload-file-size">{(f.size / 1024).toFixed(1)} KB</span>
                      </li>
                    ))}
                  </ul>
                )}
                <div className="welcome-actions">
                  <button
                    className="btn btn-primary"
                    onClick={startMigrationWithUpload}
                    disabled={loading || selectedFiles.length === 0}
                    style={{ padding: "12px 24px", fontSize: "14px" }}
                  >
                    {loading ? "Uploading & starting…" : "Start migration with uploads →"}
                  </button>
                  <button
                    className="btn btn-secondary"
                    onClick={startMigration}
                    disabled={loading}
                    style={{ padding: "12px 24px", fontSize: "14px" }}
                  >
                    Use bundled demo CSVs
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* ── Dashboard ── */}
          {migrationId && tab === "Dashboard" && migration && (
            <>
              <div className="kpi-grid">
                <div className="kpi-card">
                  <div className="kpi-label">Source Rows</div>
                  <div className="kpi-value">{migration.stats.total_source_rows}</div>
                  <div className="kpi-sub">{migration.stats.files_ingested} files ingested</div>
                </div>
                <div className="kpi-card">
                  <div className="kpi-label">Auto-Processed</div>
                  <div className="kpi-value accent">{migration.stats.records_processed}</div>
                  <div className="kpi-sub">{migration.stats.auto_mapped_fields} columns mapped</div>
                </div>
                <div className="kpi-card">
                  <div className="kpi-label">Needs Review</div>
                  <div className={`kpi-value${openEscalations.length ? " warning" : ""}`}>{openEscalations.length}</div>
                  <div className="kpi-sub">{openEscalations.length ? "Awaiting consultant" : "Agent autonomous"}</div>
                </div>
                <div className="kpi-card">
                  <div className="kpi-label">Target Pushed</div>
                  <div className="kpi-value success">{migration.stats.target_success}</div>
                  <div className="kpi-sub">{migration.stats.target_failed} failed</div>
                </div>
              </div>

              <div className="dashboard-grid">
                <div className="card">
                  <div className="card-header">
                    <div>
                      <h3>Migration Progress</h3>
                      <p className="card-subtitle">{migration.stats.records_cleaned} records cleaned · {migration.stats.records_processed} processed</p>
                    </div>
                    <span className={`badge ${statusBadgeClass(agentStatus)}`}>{fmtStatus(agentStatus)}</span>
                  </div>
                  <div className="card-body">
                    <div className="progress-section">
                      <div className="progress-meta">
                        <span>Overall completion</span>
                        <span>{migration.stats.progress_percent}%</span>
                      </div>
                      <div className="progress-track">
                        <div className="progress-fill" style={{ width: `${migration.stats.progress_percent}%` }} />
                      </div>
                    </div>
                    {agentStatus === "ROLLED_BACK" && (
                      <div className="alert alert-warning" style={{ marginTop: 16, marginBottom: 0 }}>
                        <span className="alert-icon">↩</span>
                        <div>Target records rolled back. Canonical data preserved for audit.</div>
                      </div>
                    )}
                  </div>
                </div>

                <div className="card">
                  <div className="card-header">
                    <h3>Agent Status</h3>
                  </div>
                  <div className="card-body agent-status-panel">
                    <div className="live-indicator">
                      <span className={`live-dot${needsAttention ? " waiting" : agentStatus === "IDLE" ? " idle" : ""}`} />
                      {needsAttention ? "Waiting for human decision" : "Running autonomously"}
                    </div>
                    <div className="current-activity">
                      {activity[activity.length - 1]?.message || "Waiting for agent events…"}
                    </div>
                    {openEscalations.length > 0 && (
                      <button className="btn btn-secondary" onClick={() => setTab("Escalations")} style={{ alignSelf: "flex-start" }}>
                        Review {openEscalations.length} escalation{openEscalations.length > 1 ? "s" : ""}
                      </button>
                    )}
                  </div>
                </div>
              </div>
            </>
          )}

          {/* ── Files ── */}
          {migrationId && tab === "Files" && (
            <div className="card">
              <div className="card-header">
                <div>
                  <h3>Source Files</h3>
                  <p className="card-subtitle">{files.length} files ingested for this migration</p>
                </div>
              </div>
              <div className="card-body">
                {files.length === 0 ? (
                  <div className="empty-state"><div className="empty-state-icon">📁</div><p>Files are being ingested…</p></div>
                ) : (
                  <div className="file-list">
                    {files.map((f) => (
                      <div key={f.filename} className="file-item">
                        <div className="file-icon">{f.filename.endsWith(".xlsx") ? "📊" : "📄"}</div>
                        <div className="file-info">
                          <strong>{f.filename}</strong>
                          <span>{f.row_count} rows · {f.columns.length} columns</span>
                        </div>
                        <div className="file-cols">{f.columns.join(", ")}</div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* ── Agent Activity ── */}
          {migrationId && tab === "Agent Activity" && (
            <div className="card">
              <div className="card-header">
                <div>
                  <h3>Live Agent Activity</h3>
                  <p className="card-subtitle">Real-time stream of agent decisions and actions</p>
                </div>
                <span className="badge badge-running">Live</span>
              </div>
              <div className="card-body timeline">
                {activity.length === 0 ? (
                  <div className="empty-state"><div className="empty-state-icon">⚡</div><p>Waiting for agent events…</p></div>
                ) : (
                  [...activity].reverse().map((a, i) => (
                    <div key={i} className={`timeline-item ${a.level}`}>
                      <span className="timeline-time">{fmtTime(a.timestamp)}</span>
                      <span className="timeline-dot" />
                      <span className="timeline-msg">{a.message}</span>
                    </div>
                  ))
                )}
              </div>
            </div>
          )}

          {/* ── Escalations ── */}
          {migrationId && tab === "Escalations" && (
            <div className="escalation-list">
              {openEscalations.length === 0 ? (
                <div className="card">
                  <div className="empty-state">
                    <div className="empty-state-icon">✓</div>
                    <p>No open escalations — the agent is running autonomously.</p>
                  </div>
                </div>
              ) : (
                openEscalations.map((e) => (
                  <EscalationCard key={e.id} e={e} onResolve={resolve} />
                ))
              )}
            </div>
          )}

          {/* ── Records ── */}
          {migrationId && tab === "Records" && (
            <div className="card">
              <div className="card-header">
                <div>
                  <h3>Canonical Employee Records</h3>
                  <p className="card-subtitle">{records.length} records reconciled from all source files</p>
                </div>
              </div>
              <div className="card-body table-wrap">
                {records.length === 0 ? (
                  <div className="empty-state"><div className="empty-state-icon">👥</div><p>Records will appear once the agent processes source data.</p></div>
                ) : (
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Employee ID</th>
                        <th>Name</th>
                        <th>Email</th>
                        <th>Department</th>
                        <th>Job Title</th>
                        <th>Validation</th>
                        <th>Target Status</th>
                        <th>Retries</th>
                      </tr>
                    </thead>
                    <tbody>
                      {records.map((r) => {
                        const d = r.data || {};
                        return (
                          <tr key={r.employee_id}>
                            <td className="td-mono">{r.employee_id}</td>
                            <td>{d.first_name} {d.last_name}</td>
                            <td className="td-muted">{d.email}</td>
                            <td>{d.department || "—"}</td>
                            <td>{d.job_title || "—"}</td>
                            <td><span className={`badge ${r.validation_status === "VALID" ? "badge-valid" : "badge-invalid"}`}>{r.validation_status}</span></td>
                            <td><span className={`badge ${targetBadgeClass(r.target_status)}`}>{r.target_status}</span></td>
                            <td className="td-muted">{r.retry_count || "—"}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                )}
              </div>
            </div>
          )}

          {/* ── Audit Log ── */}
          {migrationId && tab === "Audit Log" && (
            <div className="card">
              <div className="card-header">
                <div>
                  <h3>Audit Trail</h3>
                  <p className="card-subtitle">Complete record of agent and human decisions</p>
                </div>
              </div>
              <div className="card-body audit-list">
                {audit.length === 0 ? (
                  <div className="empty-state"><div className="empty-state-icon">📋</div><p>Audit events will appear as the agent runs.</p></div>
                ) : (
                  [...audit].reverse().map((a, i) => (
                    <div key={i} className="audit-item">
                      <span className="audit-time">{fmtTime(a.timestamp)}</span>
                      <span className={`audit-action${a.actor === "human" ? " human" : ""}`}>
                        {a.action}
                        {a.record_id && <span style={{ fontWeight: 400, color: "var(--text-muted)" }}> · {a.record_id}</span>}
                      </span>
                      <div className="audit-detail-formatted">
                        {a.action === "FIELD_MAPPING" ? (
                          <div className="field-mapping-detail">
                            <div className="mapping-row">
                              <span className="mapping-label">Source:</span>
                              <span className="mapping-value">{String(a.details.source_file || "")}::{String(a.details.source_field || "")}</span>
                            </div>
                            <div className="mapping-row">
                              <span className="mapping-label">Target:</span>
                              <span className="mapping-value">{String(a.details.target_field || "")}</span>
                            </div>
                            <div className="mapping-row">
                              <span className="mapping-label">Confidence:</span>
                              <span className="mapping-value">{typeof a.details.confidence === 'number' ? (a.details.confidence * 100).toFixed(0) + '%' : 'N/A'}</span>
                            </div>
                            <div className="mapping-row">
                              <span className="mapping-label">Decision:</span>
                              <span className={`mapping-value mapping-${String(a.details.decision || "").toLowerCase()}`}>{String(a.details.decision || "")}</span>
                            </div>
                            {a.details.reason && typeof a.details.reason === 'string' && (
                              <div className="mapping-row">
                                <span className="mapping-label">Reason:</span>
                                <span className="mapping-value">{String(a.details.reason)}</span>
                              </div>
                            )}
                          </div>
                        ) : a.action === "ESCALATION_CREATED" ? (
                          <div className="escalation-detail">
                            <div className="escalation-row">
                              <span className="escalation-label">Type:</span>
                              <span className="escalation-value">{String(a.details.type || "")}</span>
                            </div>
                            {a.details.field && typeof a.details.field === 'string' && (
                              <div className="escalation-row">
                                <span className="escalation-label">Field:</span>
                                <span className="escalation-value">{String(a.details.field)}</span>
                              </div>
                            )}
                            {a.details.reason && typeof a.details.reason === 'string' && (
                              <div className="escalation-row">
                                <span className="escalation-label">Reason:</span>
                                <span className="escalation-value">{String(a.details.reason)}</span>
                              </div>
                            )}
                            {typeof a.details.confidence === 'number' && (
                              <div className="escalation-row">
                                <span className="escalation-label">Confidence:</span>
                                <span className="escalation-value">{(a.details.confidence * 100).toFixed(0)}%</span>
                              </div>
                            )}
                          </div>
                        ) : a.action === "ESCALATION_RESOLVED" ? (
                          <div className="escalation-detail">
                            <div className="escalation-row">
                              <span className="escalation-label">Decision:</span>
                              <span className={`escalation-value escalation-${String(a.decision || "").toLowerCase()}`}>{String(a.decision || "")}</span>
                            </div>
                            {a.details.corrected_target_field && typeof a.details.corrected_target_field === 'string' && (
                              <div className="escalation-row">
                                <span className="escalation-label">Corrected Field:</span>
                                <span className="escalation-value">{String(a.details.corrected_target_field)}</span>
                              </div>
                            )}
                            {a.details.corrected_value && typeof a.details.corrected_value === 'string' && (
                              <div className="escalation-row">
                                <span className="escalation-label">Corrected Value:</span>
                                <span className="escalation-value">{String(a.details.corrected_value)}</span>
                              </div>
                            )}
                          </div>
                        ) : a.action === "TARGET_PUSH" ? (
                          <div className="target-push-detail">
                            <div className="target-row">
                              <span className="target-label">Status:</span>
                              <span className={`target-value target-${String(a.details.status || "").toLowerCase()}`}>{String(a.details.status || "")}</span>
                            </div>
                            {a.details.attempt !== undefined && (
                              <div className="target-row">
                                <span className="target-label">Attempt:</span>
                                <span className="target-value">{String(a.details.attempt)}</span>
                              </div>
                            )}
                            {a.details.message && typeof a.details.message === 'string' && (
                              <div className="target-row">
                                <span className="target-label">Message:</span>
                                <span className="target-value">{String(a.details.message)}</span>
                              </div>
                            )}
                          </div>
                        ) : (
                          <span className="audit-detail-raw">
                            {a.actor !== "agent" ? `[${a.actor}] ` : ""}{JSON.stringify(a.details, null, 2)}
                          </span>
                        )}
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          )}
        </main>
      </div>

      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}

function EscalationCard({
  e,
  onResolve,
}: {
  e: Escalation;
  onResolve: (id: number, decision: string, field?: string, value?: string) => void;
}) {
  const defaultField =
    e.candidates?.[0]?.target_field ||
    (e.escalation_type === "VALIDATION_FAILURE" ? "email" : e.field || "full_name");
  const defaultValue =
    e.escalation_type === "UNCLEANABLE_VALUE" && e.field === "date_of_birth"
      ? "1995-02-01"
      : e.escalation_type === "VALIDATION_FAILURE"
        ? "valid.user@acme.com"
        : "";
  const [correctField, setCorrectField] = useState(defaultField);
  const [correctValue, setCorrectValue] = useState(defaultValue);

  const needsValue = e.escalation_type === "UNCLEANABLE_VALUE" || e.escalation_type === "VALIDATION_FAILURE";
  const needsField = e.escalation_type === "AMBIGUOUS_MAPPING";
  const confPct = Math.round(e.confidence * 100);
  const confClass = confPct >= 85 ? "high" : confPct >= 60 ? "" : "low";

  return (
    <div className={`card escalation-card ${escCardClass(e.escalation_type)}`}>
      <div className="card-body">
        <div className="esc-header">
          <div>
            <p className="esc-title">Escalation #{e.id}</p>
            <p className="esc-meta">
              {e.record_id && <>Employee <strong>{e.record_id}</strong> · </>}
              {e.field && <>Field <strong>{e.field}</strong></>}
            </p>
          </div>
          <span className={`esc-type-badge ${escTypeClass(e.escalation_type)}`}>
            {e.escalation_type.replace(/_/g, " ")}
          </span>
        </div>

        <div className="esc-grid">
          {e.source_value && (
            <div className="esc-field">
              <div className="esc-field-label">Source Value</div>
              <div className="esc-field-value"><code>{e.source_value}</code></div>
            </div>
          )}
          <div className="esc-field">
            <div className="esc-field-label">Reason</div>
            <div className="esc-field-value">{e.reason}</div>
          </div>
        </div>

        <div className="confidence-bar-wrap">
          <div className="confidence-label">
            <span>Agent confidence</span>
            <span>{confPct}%</span>
          </div>
          <div className="confidence-track">
            <div className={`confidence-fill ${confClass}`} style={{ width: `${confPct}%` }} />
          </div>
        </div>

        {e.candidates && e.candidates.length > 0 && (
          <ul className="candidates-list">
            {e.candidates.map((c) => (
              <li key={c.target_field} className="candidate-item">
                <div>
                  <div className="candidate-name">{c.target_field}</div>
                  <div className="candidate-reasons">{c.reasons.slice(0, 2).join(" · ")}</div>
                </div>
                <span className="candidate-pct">{(c.confidence * 100).toFixed(0)}%</span>
              </li>
            ))}
          </ul>
        )}

        <div className="recommendation">
          <strong>Recommended action</strong>
          {e.recommended_action}
          {e.possible_consequences && (
            <div style={{ marginTop: 6, fontSize: 12, color: "#0369a1" }}>⚠ {e.possible_consequences}</div>
          )}
        </div>

        {(needsField || needsValue) && (
          <div className="correct-row">
            {needsField && (
              <div className="form-group">
                <label className="form-label">Target field</label>
                <input className="form-input" value={correctField} onChange={(ev) => setCorrectField(ev.target.value)} />
              </div>
            )}
            {needsValue && (
              <div className="form-group">
                <label className="form-label">Corrected value</label>
                <input className="form-input" value={correctValue} onChange={(ev) => setCorrectValue(ev.target.value)} />
              </div>
            )}
          </div>
        )}

        <div className="esc-actions">
          <button className="btn btn-primary" onClick={() => onResolve(e.id, "APPROVE")}>
            ✓ Approve recommendation
          </button>
          {(needsField || needsValue) && (
            <button className="btn btn-secondary" onClick={() => onResolve(e.id, "CORRECT", correctField, correctValue)}>
              ✎ Apply correction
            </button>
          )}
          <button className="btn btn-danger" onClick={() => onResolve(e.id, "REJECT")}>
            ✕ Reject
          </button>
        </div>
      </div>
    </div>
  );
}

export default App;
