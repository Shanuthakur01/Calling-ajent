"""
Dashboard HTML — three-page SPA shell with sidebar navigation.

render_dashboard() → GET /
render_calls()     → GET /calls
render_agent()     → GET /agent
DASHBOARD_HTML     → render_dashboard()  (backward-compat alias)
"""

# ---------------------------------------------------------------------------
# Shared layout template
# Placeholders:  DASHBRD_TITLE  DASHBRD_SUBTITLE
#                DASHBRD_NAV_HOME  DASHBRD_NAV_CALLS  DASHBRD_NAV_AGENT
#                DASHBRD_CONTENT
# ---------------------------------------------------------------------------

_LAYOUT = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DASHBRD_TITLE — IJF Calling Agent</title>
<style>
:root, [data-theme="dark"] {
  --bg:            #0a0e1a;
  --surface:       #111827;
  --surface-2:     #161e2e;
  --sidebar-bg:    #0d1322;
  --border:        #1f2937;
  --border-strong: #374151;
  --text-primary:  #f3f4f6;
  --text-secondary:#d1d5db;
  --text-muted:    #9ca3af;
  --text-dim:      #6b7280;
  --brand-blue:    #7eb3d9;
  --brand-yellow:  #f5d77a;
  --accent:        #3b82f6;
  --accent-hover:  #2563eb;
  --accent-soft:   rgba(59,130,246,0.15);
  --success:       #10b981;
  --success-soft:  rgba(16,185,129,0.15);
  --warning:       #f59e0b;
  --warning-soft:  rgba(245,158,11,0.15);
  --danger:        #ef4444;
  --danger-soft:   rgba(239,68,68,0.15);
  --shadow-sm:     0 1px 2px rgba(0,0,0,0.3);
  --shadow-md:     0 4px 12px rgba(0,0,0,0.4);
  --ring:          0 0 0 3px rgba(59,130,246,0.3);
}

[data-theme="light"] {
  --bg:            #ffffff;
  --surface:       #fafbfc;
  --surface-2:     #f4f5f7;
  --sidebar-bg:    #f9fafb;
  --border:        #e5e7eb;
  --border-strong: #d1d5db;
  --text-primary:  #111827;
  --text-secondary:#374151;
  --text-muted:    #6b7280;
  --text-dim:      #9ca3af;
  --brand-blue:    #5b9bd5;
  --brand-yellow:  #e8c558;
  --accent:        #2563eb;
  --accent-hover:  #1d4ed8;
  --accent-soft:   rgba(37,99,235,0.1);
  --success:       #059669;
  --success-soft:  rgba(5,150,105,0.12);
  --warning:       #d97706;
  --warning-soft:  rgba(217,119,6,0.12);
  --danger:        #dc2626;
  --danger-soft:   rgba(220,38,38,0.12);
  --shadow-sm:     0 1px 2px rgba(0,0,0,0.06);
  --shadow-md:     0 4px 12px rgba(0,0,0,0.08);
  --ring:          0 0 0 3px rgba(37,99,235,0.2);
}

*,*::before,*::after { box-sizing: border-box; margin: 0; padding: 0; }

html, body {
  height: 100%;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Inter", Roboto, sans-serif;
  background: var(--bg);
  color: var(--text-primary);
  font-size: 14px;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
}

::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border-strong); border-radius: 10px; }

/* ── App shell ── */
.app-shell {
  display: grid;
  grid-template-columns: 240px 1fr;
  min-height: 100vh;
}

/* ── Sidebar ── */
.ijf-sidebar {
  background: var(--sidebar-bg);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  padding: 24px 16px;
  position: sticky;
  top: 0;
  height: 100vh;
  overflow-y: auto;
}

.sidebar-brand {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-bottom: 32px;
  padding: 0 8px;
  gap: 0;
}

.sidebar-logo {
  width: 56px;
  height: 56px;
  object-fit: contain;
  margin-bottom: 12px;
  border-radius: 10px;
}

.sidebar-logo-fallback {
  width: 56px;
  height: 56px;
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
}
.sidebar-logo-fallback svg { width: 40px; height: 40px; }

.sidebar-wordmark {
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--text-primary);
  text-align: center;
  letter-spacing: -0.1px;
}

.sidebar-nav {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  color: var(--text-muted);
  text-decoration: none;
  border-radius: 6px;
  font-size: 0.875rem;
  font-weight: 500;
  transition: background-color 150ms, color 150ms;
}
.nav-item:hover  { background: var(--surface-2); color: var(--text-primary); }
.nav-item.active { background: var(--accent-soft); color: var(--accent); font-weight: 600; }
.nav-icon { width: 18px; height: 18px; flex-shrink: 0; }

.sidebar-footer { padding-top: 16px; border-top: 1px solid var(--border); }

.theme-toggle {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  background: transparent;
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 0.8125rem;
  font-family: inherit;
  transition: background-color 150ms, color 150ms, border-color 150ms;
}
.theme-toggle:hover { background: var(--surface-2); color: var(--text-primary); border-color: var(--border-strong); }
.theme-icon  { width: 16px; height: 16px; flex-shrink: 0; }
.theme-label { flex: 1; text-align: left; }

[data-theme="dark"]  .icon-sun  { display: inline-block; }
[data-theme="dark"]  .icon-moon { display: none; }
[data-theme="light"] .icon-sun  { display: none; }
[data-theme="light"] .icon-moon { display: inline-block; }

/* ── Main area ── */
.app-main {
  padding: 24px 32px 48px;
  max-width: 1400px;
  width: 100%;
  overflow-y: auto;
  min-height: 100vh;
}

.app-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  margin-bottom: 32px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border);
}

.header-left { display: flex; flex-direction: column; gap: 4px; }
.page-title  { font-size: 1.5rem; font-weight: 600; margin: 0; color: var(--text-primary); }
.page-subtitle { font-size: 0.875rem; color: var(--text-muted); margin: 0; }
.header-right { display: flex; align-items: center; gap: 16px; }

.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  background: var(--success-soft);
  color: var(--success);
  border-radius: 12px;
  font-size: 0.75rem;
  font-weight: 600;
}
.status-dot  { width: 6px; height: 6px; background: var(--success); border-radius: 50%; }
.header-time { font-size: 0.8125rem; color: var(--text-muted); font-variant-numeric: tabular-nums; }

/* ── Section label ── */
.section-label {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-muted);
  margin-bottom: 16px;
}

/* ── KPI tiles ── */
.stats-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 32px;
}

.stat-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 24px;
}

.stat-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 12px;
}

.stat-icon  { width: 20px; height: 20px; flex-shrink: 0; }
.stat-label {
  font-size: 11px; font-weight: 600;
  letter-spacing: 0.08em; text-transform: uppercase;
  color: var(--text-muted); margin-bottom: 8px;
}
.stat-num {
  font-size: 48px; font-weight: 600; line-height: 1;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
  margin-bottom: 8px;
}
.stat-sub { font-size: 12px; color: var(--text-muted); }

/* ── Content grid ── */
.content-grid {
  display: grid;
  grid-template-columns: 360px 1fr;
  gap: 24px;
  align-items: start;
}

/* ── Card ── */
.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
}

.card-head {
  padding: 16px 24px;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.card-body { padding: 24px; }

/* ── Form ── */
.form-group { margin-bottom: 16px; }

.form-label {
  display: block;
  font-size: 11px; font-weight: 600;
  letter-spacing: 0.08em; text-transform: uppercase;
  color: var(--text-muted); margin-bottom: 6px;
}

input[type=text], input[type=tel] {
  display: block; width: 100%; height: 40px; padding: 0 12px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text-primary);
  font-family: inherit; font-size: 14px;
  outline: none;
  transition: border-color 0.15s, box-shadow 0.15s;
}
input[type=text]:focus, input[type=tel]:focus {
  border-color: var(--accent);
  box-shadow: var(--ring);
}
input::placeholder { color: var(--text-dim); }
.form-hint { font-size: 12px; color: var(--text-muted); margin-top: 6px; }

/* ── Call button ── */
.call-btn {
  display: flex; align-items: center; justify-content: center; gap: 8px;
  width: 100%; height: 44px;
  background: var(--accent); color: #fff;
  border: none; border-radius: 8px;
  font-family: inherit; font-size: 14px; font-weight: 600;
  cursor: pointer;
  transition: background 0.15s, transform 0.1s;
  margin-top: 8px;
}
.call-btn:hover:not(:disabled) { background: var(--accent-hover); }
.call-btn:active:not(:disabled) { transform: translateY(1px); }
.call-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.call-btn .btn-label   { display: flex; align-items: center; gap: 8px; }
.call-btn .btn-spinner {
  display: none; width: 18px; height: 18px;
  border: 2px solid rgba(255,255,255,0.3);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
.call-btn.loading .btn-label   { display: none; }
.call-btn.loading .btn-spinner { display: block; }

/* ── Divider ── */
.divider {
  display: flex; align-items: center; gap: 10px;
  margin: 24px 0 16px;
  color: var(--text-dim); font-size: 11px; font-weight: 600;
  letter-spacing: 0.08em; text-transform: uppercase;
}
.divider::before, .divider::after { content: ''; flex: 1; height: 1px; background: var(--border); }

/* ── Steps ── */
.steps { display: flex; flex-direction: column; gap: 12px; }
.step  { display: flex; gap: 12px; align-items: flex-start; }
.step-num {
  width: 28px; height: 28px; border-radius: 50%;
  background: var(--accent); color: #fff;
  display: flex; align-items: center; justify-content: center;
  font-size: 13px; font-weight: 600;
  flex-shrink: 0; margin-top: 1px;
}
.step-title  { font-size: 13px; font-weight: 500; color: var(--text-primary); }
.step-detail { font-size: 12px; color: var(--text-muted); margin-top: 2px; }

/* ── Table toolbar ── */
.tbl-toolbar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }

.search-wrap { position: relative; }
.search-wrap svg {
  position: absolute; left: 10px; top: 50%; transform: translateY(-50%);
  color: var(--text-muted); pointer-events: none;
}
.search-wrap input {
  height: 32px; padding: 0 10px 0 30px; font-size: 13px; width: 220px;
  background: var(--surface-2); border: 1px solid var(--border);
  border-radius: 6px; color: var(--text-primary);
  outline: none; transition: border-color 0.15s;
}
.search-wrap input:focus { border-color: var(--accent); }

.filter-select {
  height: 32px; padding: 0 8px;
  background: var(--surface-2); border: 1px solid var(--border);
  border-radius: 6px; color: var(--text-primary);
  font-family: inherit; font-size: 13px;
  outline: none; cursor: pointer;
  transition: border-color 0.15s;
}
.filter-select:focus { border-color: var(--accent); }

.icon-btn {
  display: flex; align-items: center; gap: 6px;
  height: 32px; padding: 0 12px;
  background: transparent; border: 1px solid var(--border);
  border-radius: 6px; color: var(--text-muted);
  font-family: inherit; font-size: 13px; font-weight: 500;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
  white-space: nowrap;
}
.icon-btn:hover { background: var(--surface-2); color: var(--text-primary); }

/* ── Table ── */
.tbl-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; }

thead th {
  padding: 0 16px 12px;
  font-size: 11px; font-weight: 600;
  letter-spacing: 0.08em; text-transform: uppercase;
  color: var(--text-muted);
  text-align: left;
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}
thead th:last-child { text-align: right; }

tbody tr {
  border-bottom: 1px solid rgba(255,255,255,0.03);
  transition: background 0.1s;
}
[data-theme="light"] tbody tr { border-bottom: 1px solid var(--border); }
tbody tr:last-child { border-bottom: none; }
tbody tr:hover { background: var(--surface-2); }

tbody td {
  padding: 14px 16px; font-size: 14px;
  vertical-align: middle;
  font-variant-numeric: tabular-nums;
}
tbody td:last-child { text-align: right; }

.name-cell { display: flex; align-items: center; gap: 10px; }
.avatar {
  width: 30px; height: 30px; border-radius: 6px;
  background: var(--surface-2); border: 1px solid var(--border);
  display: flex; align-items: center; justify-content: center;
  font-size: 11px; font-weight: 700; color: var(--text-muted);
  text-transform: uppercase; flex-shrink: 0;
}
.name-text { font-weight: 500; color: var(--text-primary); }
.phone-val {
  font-family: "SF Mono", ui-monospace, Menlo, "Cascadia Code", Consolas, monospace;
  font-size: 13px; color: var(--text-muted);
}
.td-muted { color: var(--text-muted); font-size: 13px; }

/* ── Badges ── */
.badge {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 2px 10px; border-radius: 4px;
  font-size: 12px; font-weight: 600; white-space: nowrap;
}
.badge-dot { width: 5px; height: 5px; border-radius: 50%; background: currentColor; flex-shrink: 0; }
.b-active    { background: rgba(16,185,129,0.15); color: #10b981; }
.b-calling   { background: rgba(245,158,11,0.15);  color: #f59e0b; }
.b-ringing   { background: rgba(59,130,246,0.15);  color: #3b82f6; }
.b-completed { background: rgba(16,185,129,0.15); color: #10b981; }
.b-failed    { background: rgba(239,68,68,0.15);   color: #ef4444; }

/* ── Empty state ── */
.empty-state { padding: 80px 20px; text-align: center; }
.empty-state p    { font-size: 14px; color: var(--text-dim); }
.empty-state span { font-size: 12px; color: var(--text-dim); display: block; margin-top: 4px; }

/* ── Toast ── */
#toasts {
  position: fixed; top: 16px; right: 16px;
  display: flex; flex-direction: column; gap: 8px;
  z-index: 999; pointer-events: none;
}
.toast {
  pointer-events: all;
  display: flex; gap: 12px; align-items: flex-start;
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 8px; padding: 12px 16px;
  min-width: 270px; max-width: 340px;
  box-shadow: var(--shadow-md);
  animation: toastIn 0.2s ease-out;
}
@keyframes toastIn  { from { transform: translateX(110%); opacity: 0; } }
@keyframes toastOut { to   { transform: translateX(110%); opacity: 0; } }
.toast.out  { animation: toastOut 0.2s ease-in forwards; }
.toast-icon { flex-shrink: 0; margin-top: 1px; }
.toast-body { flex: 1; min-width: 0; }
.toast-title { font-size: 13px; font-weight: 600; color: var(--text-primary); margin-bottom: 2px; }
.toast-msg   { font-size: 12px; color: var(--text-muted); line-height: 1.4; }
.t-success   { border-left: 3px solid var(--success); }
.t-error     { border-left: 3px solid var(--danger); }
.t-info      { border-left: 3px solid var(--accent); }

/* ── Prompt editor ── */
.prompt-editor-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 24px;
}
.prompt-editor-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 16px;
  gap: 16px;
}
.prompt-editor-title    { font-size: 1rem; font-weight: 600; color: var(--text-primary); margin: 0; }
.prompt-editor-subtitle { font-size: 0.8125rem; color: var(--text-muted); margin: 4px 0 0 0; }
.prompt-editor-status   { font-size: 0.75rem; color: var(--text-muted); min-height: 20px; text-align: right; }
.prompt-editor-status.success { color: var(--success); }
.prompt-editor-status.error   { color: var(--danger); }
.prompt-textarea {
  width: 100%;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 12px;
  font-family: "SF Mono", ui-monospace, Menlo, Consolas, monospace;
  font-size: 0.8125rem; line-height: 1.6;
  color: var(--text-primary);
  resize: vertical; min-height: 320px;
  outline: none;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.prompt-textarea:focus { border-color: var(--accent); box-shadow: var(--ring); }
.prompt-editor-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 16px;
  gap: 16px;
}
.prompt-char-count { font-size: 0.75rem; color: var(--text-muted); font-variant-numeric: tabular-nums; }
.prompt-char-count.over-limit { color: var(--danger); }
.prompt-editor-actions { display: flex; gap: 8px; }

/* ── Buttons ── */
.btn {
  padding: 8px 16px; border-radius: 6px;
  font-size: 0.8125rem; font-weight: 600;
  cursor: pointer; border: 1px solid transparent;
  font-family: inherit; transition: background-color 0.15s;
}
.btn-primary { background: var(--accent); color: #fff; border-color: var(--accent); }
.btn-primary:hover:not(:disabled) { background: var(--accent-hover); border-color: var(--accent-hover); }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-secondary { background: transparent; color: var(--text-muted); border-color: var(--border); }
.btn-secondary:hover { background: var(--surface-2); color: var(--text-primary); }

/* ── View-all link ── */
.view-all-link { font-size: 0.8125rem; color: var(--accent); text-decoration: none; font-weight: 500; }
.view-all-link:hover { text-decoration: underline; }

/* ── Responsive ── */
@media (max-width: 1100px) {
  .content-grid { grid-template-columns: 300px 1fr; }
  .stats-row    { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 860px) {
  .content-grid { grid-template-columns: 1fr; }
}
@media (max-width: 768px) {
  .app-shell { grid-template-columns: 1fr; }
  .ijf-sidebar { display: none; }
  .app-main { padding: 16px; }
}
</style>
</head>
<body>
<div class="app-shell">

<!-- ── Sidebar ── -->
<aside class="ijf-sidebar">
  <div class="sidebar-brand">
    <img src="/static/logo-icon.png" alt="IJF" class="sidebar-logo"
         onerror="this.style.display='none';document.getElementById('sb-fallback').style.display='flex';">
    <div id="sb-fallback" class="sidebar-logo-fallback" style="display:none;">
      <svg viewBox="0 0 48 48">
        <circle cx="24" cy="24" r="20" fill="none" stroke="var(--brand-blue)" stroke-width="2"/>
        <text x="24" y="29" text-anchor="middle" fill="var(--brand-blue)" font-size="14" font-weight="700">IJF</text>
      </svg>
    </div>
    <div class="sidebar-wordmark">IJF Calling Agent</div>
  </div>

  <nav class="sidebar-nav">
    <a href="/" class="nav-itemDASHBRD_NAV_HOME" data-route="/">
      <svg class="nav-icon" viewBox="0 0 20 20" fill="currentColor">
        <path d="M10.707 2.293a1 1 0 00-1.414 0l-7 7a1 1 0 001.414 1.414L4 10.414V17a1 1 0 001 1h2a1 1 0 001-1v-2a1 1 0 011-1h2a1 1 0 011 1v2a1 1 0 001 1h2a1 1 0 001-1v-6.586l.293.293a1 1 0 001.414-1.414l-7-7z"/>
      </svg>
      Dashboard
    </a>
    <a href="/calls" class="nav-itemDASHBRD_NAV_CALLS" data-route="/calls">
      <svg class="nav-icon" viewBox="0 0 20 20" fill="currentColor">
        <path d="M2 3a1 1 0 011-1h2.153a1 1 0 01.986.836l.74 4.435a1 1 0 01-.54 1.06l-1.548.773a11.037 11.037 0 006.105 6.105l.774-1.548a1 1 0 011.059-.54l4.435.74a1 1 0 01.836.986V17a1 1 0 01-1 1h-2C7.82 18 2 12.18 2 5V3z"/>
      </svg>
      Call History
    </a>
    <a href="/agent" class="nav-itemDASHBRD_NAV_AGENT" data-route="/agent">
      <svg class="nav-icon" viewBox="0 0 20 20" fill="currentColor">
        <path fill-rule="evenodd" d="M11.49 3.17c-.38-1.56-2.6-1.56-2.98 0a1.532 1.532 0 01-2.286.948c-1.372-.836-2.942.734-2.106 2.106.54.886.061 2.042-.947 2.287-1.561.379-1.561 2.6 0 2.978a1.532 1.532 0 01.947 2.287c-.836 1.372.734 2.942 2.106 2.106a1.532 1.532 0 012.287.947c.379 1.561 2.6 1.561 2.978 0a1.533 1.533 0 012.287-.947c1.372.836 2.942-.734 2.106-2.106a1.533 1.533 0 01.947-2.287c1.561-.379 1.561-2.6 0-2.978a1.532 1.532 0 01-.947-2.287c.836-1.372-.734-2.942-2.106-2.106a1.532 1.532 0 01-2.287-.947zM10 13a3 3 0 100-6 3 3 0 000 6z" clip-rule="evenodd"/>
      </svg>
      Agent
    </a>
  </nav>

  <div class="sidebar-footer">
    <button class="theme-toggle" id="themeToggle" aria-label="Toggle theme">
      <svg class="theme-icon icon-sun" viewBox="0 0 20 20" fill="currentColor">
        <path fill-rule="evenodd" d="M10 2a1 1 0 011 1v1a1 1 0 11-2 0V3a1 1 0 011-1zm4 8a4 4 0 11-8 0 4 4 0 018 0zm-.464 4.95l.707.707a1 1 0 001.414-1.414l-.707-.707a1 1 0 00-1.414 1.414zm2.12-10.607a1 1 0 010 1.414l-.706.707a1 1 0 11-1.414-1.414l.707-.707a1 1 0 011.414 0zM17 11a1 1 0 100-2h-1a1 1 0 100 2h1zm-7 4a1 1 0 011 1v1a1 1 0 11-2 0v-1a1 1 0 011-1zM5.05 6.464A1 1 0 106.465 5.05l-.708-.707a1 1 0 00-1.414 1.414l.707.707zm1.414 8.486l-.707.707a1 1 0 01-1.414-1.414l.707-.707a1 1 0 011.414 1.414zM4 11a1 1 0 100-2H3a1 1 0 000 2h1z" clip-rule="evenodd"/>
      </svg>
      <svg class="theme-icon icon-moon" viewBox="0 0 20 20" fill="currentColor">
        <path d="M17.293 13.293A8 8 0 016.707 2.707a8.001 8.001 0 1010.586 10.586z"/>
      </svg>
      <span class="theme-label" id="themeLabel">Light mode</span>
    </button>
  </div>
</aside>

<!-- ── Main content ── -->
<main class="app-main">
  <header class="app-header">
    <div class="header-left">
      <h1 class="page-title">DASHBRD_TITLE</h1>
      <p class="page-subtitle">DASHBRD_SUBTITLE</p>
    </div>
    <div class="header-right">
      <span class="status-pill"><span class="status-dot"></span>Server Online</span>
      <span class="header-time" id="header-clock-time"></span>
    </div>
  </header>

  <div class="page-content">
DASHBRD_CONTENT
  </div>
</main>

</div>

<div id="toasts"></div>

<script>
// Theme toggle — set before DOMContentLoaded to avoid flash
(function() {
  var stored  = localStorage.getItem('ijf-theme');
  var initial = stored || 'dark';
  document.documentElement.setAttribute('data-theme', initial);

  document.addEventListener('DOMContentLoaded', function() {
    var btn   = document.getElementById('themeToggle');
    var label = document.getElementById('themeLabel');
    if (!btn) return;

    function refreshLabel() {
      var cur = document.documentElement.getAttribute('data-theme');
      if (label) label.textContent = cur === 'dark' ? 'Light mode' : 'Dark mode';
    }
    refreshLabel();

    btn.addEventListener('click', function() {
      var cur  = document.documentElement.getAttribute('data-theme');
      var next = cur === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      localStorage.setItem('ijf-theme', next);
      refreshLabel();
    });
  });
})();

// Clock
(function clockTick() {
  var el = document.getElementById('header-clock-time');
  if (el) {
    var now = new Date();
    el.textContent = now.toLocaleTimeString('en-IN', { hour12: false });
  }
  setTimeout(clockTick, 1000);
})();

// Shared helpers
function esc(s) {
  return String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function badge(status) {
  var map = {
    active:    ['b-active',    'Active'],
    calling:   ['b-calling',   'Calling'],
    ringing:   ['b-ringing',   'Ringing'],
    completed: ['b-completed', 'Completed'],
    failed:    ['b-failed',    'Failed'],
  };
  var pair = map[status] || ['b-completed', status || '—'];
  return '<span class="badge ' + pair[0] + '"><span class="badge-dot"></span>' + pair[1] + '</span>';
}

function fmtTime(ts) {
  if (!ts) return '—';
  return new Date(ts * 1000).toLocaleTimeString('en-IN', {
    hour: '2-digit', minute: '2-digit', hour12: true
  });
}

function duration(c) {
  if (!c.answered_at) return '—';
  var end  = c.ended_at || (Date.now() / 1000);
  var secs = Math.max(0, Math.floor(end - c.answered_at));
  if (secs < 60) return secs + 's';
  var m = Math.floor(secs / 60), s = secs % 60;
  return m + 'm ' + String(s).padStart(2, '0') + 's';
}

function toast(type, title, msg) {
  var icons = {
    success: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>',
    error:   '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
    info:    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#60a5fa" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>',
  };
  var el = document.createElement('div');
  el.className = 'toast t-' + type;
  el.innerHTML = '<div class="toast-icon">' + (icons[type] || '') + '</div>'
    + '<div class="toast-body"><div class="toast-title">' + esc(title) + '</div>'
    + '<div class="toast-msg">' + esc(msg) + '</div></div>';
  document.getElementById('toasts').appendChild(el);
  setTimeout(function() {
    el.classList.add('out');
    el.addEventListener('animationend', function() { el.remove(); });
  }, 4500);
}
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# _shell — assemble a full page from the layout template
# ---------------------------------------------------------------------------

def _shell(page_title: str, page_subtitle: str, active_route: str, content: str) -> str:
    nav_home  = " active" if active_route == "/"      else ""
    nav_calls = " active" if active_route == "/calls" else ""
    nav_agent = " active" if active_route == "/agent" else ""
    return (
        _LAYOUT
        .replace("DASHBRD_TITLE",     page_title)
        .replace("DASHBRD_SUBTITLE",  page_subtitle)
        .replace("DASHBRD_NAV_HOME",  nav_home)
        .replace("DASHBRD_NAV_CALLS", nav_calls)
        .replace("DASHBRD_NAV_AGENT", nav_agent)
        .replace("DASHBRD_CONTENT",   content)
    )


# ---------------------------------------------------------------------------
# Dashboard page — KPI tiles + Place New Call + Recent Calls (last 5)
# ---------------------------------------------------------------------------

_DASHBOARD_CONTENT = """
<!-- KPI tiles -->
<div>
  <p class="section-label">Overview</p>
  <div class="stats-row">

    <div class="stat-card">
      <div class="stat-top">
        <span class="stat-label">Total Calls</span>
        <svg class="stat-icon" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07A19.5 19.5 0 0 1 4.69 13.4 19.79 19.79 0 0 1 1.62 4.76 2 2 0 0 1 3.59 2.58h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L7.91 10.1a16 16 0 0 0 6 6l.91-.91a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 21.5 17.5z"/>
        </svg>
      </div>
      <div class="stat-num" id="s-total">&#8212;</div>
      <div class="stat-sub">All sessions initiated</div>
    </div>

    <div class="stat-card">
      <div class="stat-top">
        <span class="stat-label">Active Now</span>
        <svg class="stat-icon" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>
        </svg>
      </div>
      <div class="stat-num" id="s-active">&#8212;</div>
      <div class="stat-sub">Live interviews ongoing</div>
    </div>

    <div class="stat-card">
      <div class="stat-top">
        <span class="stat-label">In Progress</span>
        <svg class="stat-icon" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
        </svg>
      </div>
      <div class="stat-num" id="s-progress">&#8212;</div>
      <div class="stat-sub">Calling + ringing</div>
    </div>

    <div class="stat-card">
      <div class="stat-top">
        <span class="stat-label">Completed</span>
        <svg class="stat-icon" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="20 6 9 17 4 12"/>
        </svg>
      </div>
      <div class="stat-num" id="s-done">&#8212;</div>
      <div class="stat-sub">Finished interviews</div>
    </div>

  </div>
</div>

<!-- Content grid: form + recent calls -->
<div class="content-grid">

  <!-- Place New Call -->
  <div class="card">
    <div class="card-head">
      <div class="card-title">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07A19.5 19.5 0 0 1 4.69 13.4 19.79 19.79 0 0 1 1.62 4.76 2 2 0 0 1 3.59 2.58h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L7.91 10.1a16 16 0 0 0 6 6l.91-.91a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 21.5 17.5z"/>
        </svg>
        Place New Call
      </div>
    </div>
    <div class="card-body">
      <div class="form-group">
        <label class="form-label" for="inp-phone">Phone Number</label>
        <input type="tel" id="inp-phone" placeholder="9876543210 or +919876543210" autocomplete="off">
        <p class="form-hint">10-digit number is auto-formatted to +91</p>
      </div>
      <div class="form-group">
        <label class="form-label" for="inp-name">Candidate Name</label>
        <input type="text" id="inp-name" placeholder="Full name (optional)" autocomplete="off">
      </div>
      <button class="call-btn" id="call-btn">
        <span class="btn-label">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07A19.5 19.5 0 0 1 4.69 13.4 19.79 19.79 0 0 1 1.62 4.76 2 2 0 0 1 3.59 2.58h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L7.91 10.1a16 16 0 0 0 6 6l.91-.91a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 21.5 17.5z"/>
          </svg>
          Call Candidate Now
        </span>
        <div class="btn-spinner"></div>
      </button>

      <div class="divider">How It Works</div>
      <div class="steps">
        <div class="step"><div class="step-num">1</div><div><div class="step-title">Call Initiated</div><div class="step-detail">Plivo dials the candidate's number via our line</div></div></div>
        <div class="step"><div class="step-num">2</div><div><div class="step-title">Candidate Answers</div><div class="step-detail">The agent greets them and begins the session</div></div></div>
        <div class="step"><div class="step-num">3</div><div><div class="step-title">Live HR Screening</div><div class="step-detail">AI-powered real-time screening interview begins</div></div></div>
        <div class="step"><div class="step-num">4</div><div><div class="step-title">Session Complete</div><div class="step-detail">Call ends, status updates here automatically</div></div></div>
      </div>
    </div>
  </div>

  <!-- Recent Calls (last 5) -->
  <div class="card">
    <div class="card-head">
      <div class="card-title">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>
          <circle cx="9" cy="7" r="4"/>
          <path d="M23 21v-2a4 4 0 0 0-3-3.87"/>
          <path d="M16 3.13a4 4 0 0 1 0 7.75"/>
        </svg>
        Recent Calls
      </div>
      <a href="/calls" class="view-all-link">View all &#8594;</a>
    </div>
    <div class="tbl-wrap">
      <table>
        <thead>
          <tr>
            <th>Candidate</th><th>Phone</th><th>Status</th><th>Started</th><th>Duration</th>
          </tr>
        </thead>
        <tbody id="tbl-body">
          <tr><td colspan="5"><div class="empty-state">
            <p>No calls yet</p>
            <span>Place your first call using the form on the left</span>
          </div></td></tr>
        </tbody>
      </table>
    </div>
  </div>

</div>

<script>
var _allCalls = [];

async function loadData() {
  try {
    const [sRes, cRes] = await Promise.all([fetch('/api/stats'), fetch('/api/calls')]);
    const stats = await sRes.json();
    const data  = await cRes.json();
    _allCalls   = data.calls || [];
    renderStats(stats);
    renderTable(_allCalls.slice(0, 5));
  } catch(e) { console.error('loadData:', e); }
}

function renderStats(s) {
  var set = function(id, val) { var el = document.getElementById(id); if (el) el.textContent = val; };
  set('s-total',    s.total     ?? 0);
  set('s-active',   s.active    ?? 0);
  set('s-progress', (s.calling  ?? 0) + (s.ringing ?? 0));
  set('s-done',     s.completed ?? 0);
}

function renderTable(calls) {
  var tbody = document.getElementById('tbl-body');
  if (!tbody) return;
  if (!calls.length) {
    tbody.innerHTML = '<tr><td colspan="5"><div class="empty-state"><p>No calls yet</p><span>Place your first call using the form on the left</span></div></td></tr>';
    return;
  }
  tbody.innerHTML = calls.map(function(c) {
    var initials = (c.name || 'C').split(/\\s+/).map(function(w) { return w[0] || ''; }).join('').slice(0, 2).toUpperCase();
    return '<tr>'
      + '<td><div class="name-cell"><div class="avatar">' + esc(initials) + '</div>'
      + '<span class="name-text">' + esc(c.name || 'Candidate') + '</span></div></td>'
      + '<td><span class="phone-val">' + esc(c.phone || '—') + '</span></td>'
      + '<td>' + badge(c.status) + '</td>'
      + '<td class="td-muted">' + fmtTime(c.started_at) + '</td>'
      + '<td class="td-muted">' + duration(c) + '</td>'
      + '</tr>';
  }).join('');
}

async function placeCall() {
  var phone = (document.getElementById('inp-phone').value || '').trim();
  var name  = (document.getElementById('inp-name').value  || '').trim();
  if (!phone) {
    toast('error', 'Missing Phone', 'Enter a phone number before calling.');
    document.getElementById('inp-phone').focus();
    return;
  }
  var btn = document.getElementById('call-btn');
  btn.disabled = true;
  btn.classList.add('loading');
  try {
    var res  = await fetch('/make-call', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ phone: phone, name: name }),
    });
    var data = await res.json();
    if (data.success) {
      toast('success', 'Call Placed', 'Dialing ' + (name || phone) + '…');
      document.getElementById('inp-phone').value = '';
      document.getElementById('inp-name').value  = '';
      setTimeout(loadData, 1800);
    } else {
      toast('error', 'Call Failed', data.error || 'Plivo returned an error.');
    }
  } catch(e) {
    toast('error', 'Network Error', e.message || 'Could not reach server.');
  } finally {
    btn.disabled = false;
    btn.classList.remove('loading');
  }
}

['inp-phone', 'inp-name'].forEach(function(id) {
  var el = document.getElementById(id);
  if (el) el.addEventListener('keydown', function(e) { if (e.key === 'Enter') placeCall(); });
});

document.getElementById('call-btn').addEventListener('click', placeCall);

loadData();
setInterval(loadData, 5000);
</script>
"""


# ---------------------------------------------------------------------------
# Calls page — full call history with search + status filter
# ---------------------------------------------------------------------------

_CALLS_CONTENT = """
<div class="card">
  <div class="card-head">
    <div class="card-title">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>
        <circle cx="9" cy="7" r="4"/>
        <path d="M23 21v-2a4 4 0 0 0-3-3.87"/>
        <path d="M16 3.13a4 4 0 0 1 0 7.75"/>
      </svg>
      All Calls
    </div>
    <div class="tbl-toolbar">
      <div class="search-wrap">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
        </svg>
        <input type="text" id="search" placeholder="Search name or phone&#8230;">
      </div>
      <select class="filter-select" id="status-filter">
        <option value="">All statuses</option>
        <option value="active">Active</option>
        <option value="completed">Completed</option>
        <option value="calling">Calling</option>
        <option value="ringing">Ringing</option>
        <option value="failed">Failed</option>
      </select>
      <button class="icon-btn" id="refresh-btn">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/>
          <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>
        </svg>
        Refresh
      </button>
    </div>
  </div>

  <div class="tbl-wrap">
    <table>
      <thead>
        <tr>
          <th>Candidate</th><th>Phone</th><th>Status</th><th>Started</th><th>Duration</th>
        </tr>
      </thead>
      <tbody id="tbl-body">
        <tr><td colspan="5"><div class="empty-state">
          <p>No calls yet</p>
          <span>Place your first call from the Dashboard</span>
        </div></td></tr>
      </tbody>
    </table>
  </div>
</div>

<script>
var _allCalls = [];

async function loadData() {
  try {
    var res  = await fetch('/api/calls');
    var data = await res.json();
    _allCalls = data.calls || [];
    renderTable();
  } catch(e) { console.error('loadData:', e); }
}

function renderTable() {
  var q  = (document.getElementById('search').value || '').trim().toLowerCase();
  var sf = (document.getElementById('status-filter').value || '').trim().toLowerCase();
  var rows = _allCalls;
  if (q)  rows = rows.filter(function(c) { return (c.name || '').toLowerCase().includes(q) || (c.phone || '').includes(q); });
  if (sf) rows = rows.filter(function(c) { return (c.status || '').toLowerCase() === sf; });

  var tbody = document.getElementById('tbl-body');
  if (!tbody) return;
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="5"><div class="empty-state"><p>No calls found</p><span>Try a different search term or filter</span></div></td></tr>';
    return;
  }
  tbody.innerHTML = rows.map(function(c) {
    var initials = (c.name || 'C').split(/\\s+/).map(function(w) { return w[0] || ''; }).join('').slice(0, 2).toUpperCase();
    return '<tr>'
      + '<td><div class="name-cell"><div class="avatar">' + esc(initials) + '</div>'
      + '<span class="name-text">' + esc(c.name || 'Candidate') + '</span></div></td>'
      + '<td><span class="phone-val">' + esc(c.phone || '—') + '</span></td>'
      + '<td>' + badge(c.status) + '</td>'
      + '<td class="td-muted">' + fmtTime(c.started_at) + '</td>'
      + '<td class="td-muted">' + duration(c) + '</td>'
      + '</tr>';
  }).join('');
}

document.getElementById('search').addEventListener('input', renderTable);
document.getElementById('status-filter').addEventListener('change', renderTable);
document.getElementById('refresh-btn').addEventListener('click', loadData);

loadData();
setInterval(loadData, 5000);
</script>
"""


# ---------------------------------------------------------------------------
# Agent page — prompt editor
# ---------------------------------------------------------------------------

_AGENT_CONTENT = """
<div class="prompt-editor-card">
  <div class="prompt-editor-header">
    <div>
      <h2 class="prompt-editor-title">Agent Prompt</h2>
      <p class="prompt-editor-subtitle">Edit the system prompt that drives the agent's behavior. Changes apply to the next call.</p>
    </div>
    <div class="prompt-editor-status" id="prompt-status"></div>
  </div>

  <textarea
    id="prompt-editor"
    class="prompt-textarea"
    rows="18"
    placeholder="Loading prompt&#8230;"
    maxlength="10000"
  ></textarea>

  <div class="prompt-editor-footer">
    <span class="prompt-char-count" id="prompt-char-count">0 / 10,000</span>
    <div class="prompt-editor-actions">
      <button class="btn btn-secondary" id="btn-reset-prompt">Reset to Default</button>
      <button class="btn btn-primary"   id="btn-save-prompt">Save Changes</button>
    </div>
  </div>
</div>

<script>
var promptEditor = document.getElementById('prompt-editor');
var charCount    = document.getElementById('prompt-char-count');
var statusEl     = document.getElementById('prompt-status');
var btnSave      = document.getElementById('btn-save-prompt');
var btnReset     = document.getElementById('btn-reset-prompt');

var originalPrompt = '';

async function loadPrompt() {
  try {
    var r    = await fetch('/api/prompt');
    var data = await r.json();
    promptEditor.value = data.content;
    originalPrompt = data.content;
    updateCharCount();
  } catch(e) { setPromptStatus('Failed to load prompt', 'error'); }
}

function updateCharCount() {
  var len = promptEditor.value.length;
  charCount.textContent = len.toLocaleString() + ' / 10,000';
  charCount.classList.toggle('over-limit', len > 10000);
  btnSave.disabled = len === 0 || len > 10000;
}

function setPromptStatus(msg, type) {
  statusEl.textContent = msg;
  statusEl.className   = 'prompt-editor-status' + (type ? ' ' + type : '');
  if (msg) setTimeout(function() {
    statusEl.textContent = '';
    statusEl.className   = 'prompt-editor-status';
  }, 4000);
}

async function savePrompt() {
  var content = promptEditor.value;
  if (!content.trim())        { setPromptStatus('Prompt cannot be empty', 'error');       return; }
  if (content.length > 10000) { setPromptStatus('Prompt exceeds 10,000 chars', 'error'); return; }
  btnSave.disabled = true;
  try {
    var r = await fetch('/api/prompt', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ content: content }),
    });
    if (!r.ok) {
      var err = await r.json();
      throw new Error(err.detail || 'Save failed');
    }
    originalPrompt = content;
    setPromptStatus('Saved. Next call will use the new prompt.', 'success');
  } catch(e) { setPromptStatus(e.message, 'error'); }
  finally { btnSave.disabled = false; updateCharCount(); }
}

async function resetPrompt() {
  if (!confirm('Reset prompt to default? Current changes will be lost.')) return;
  try {
    var r = await fetch('/api/prompt/reset', { method: 'POST' });
    if (!r.ok) throw new Error('Reset failed');
    await loadPrompt();
    setPromptStatus('Reset to default.', 'success');
  } catch(e) { setPromptStatus(e.message, 'error'); }
}

promptEditor.addEventListener('input', updateCharCount);
btnSave.addEventListener('click', savePrompt);
btnReset.addEventListener('click', resetPrompt);

loadPrompt();
</script>
"""


# ---------------------------------------------------------------------------
# Public render functions
# ---------------------------------------------------------------------------

def render_dashboard() -> str:
    return _shell("Dashboard", "Place calls and monitor sessions", "/", _DASHBOARD_CONTENT)


def render_calls() -> str:
    return _shell("Call History", "Browse and filter all call sessions", "/calls", _CALLS_CONTENT)


def render_agent() -> str:
    return _shell("Agent Setup", "Configure the AI agent's behavior", "/agent", _AGENT_CONTENT)


# Backward-compat alias used by tests/test_dashboard_no_cost_column.py
DASHBOARD_HTML = render_dashboard()
