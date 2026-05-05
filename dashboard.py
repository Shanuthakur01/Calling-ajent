"""
Dashboard HTML — embedded as a Python string so no separate .html file is needed.
Served by main.py at GET /.
"""

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Saanvi AI — Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:ital,opsz,wght@0,14..32,300;0,14..32,400;0,14..32,500;0,14..32,600;0,14..32,700&display=swap" rel="stylesheet">
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg:        #070c18;
  --surface:   #0d1526;
  --surface2:  #111d33;
  --border:    #1a2a44;
  --border2:   #243352;
  --accent:    #3b82f6;
  --green:     #10b981;
  --amber:     #f59e0b;
  --red:       #ef4444;
  --blue:      #60a5fa;
  --purple:    #a78bfa;
  --text:      #e2e8f0;
  --muted:     #64748b;
  --dim:       #2d3f5c;
}

html, body {
  height: 100%;
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
  background: var(--bg);
  color: var(--text);
  font-size: 14px;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
}

::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border2); border-radius: 10px; }

/* ── Layout ── */
.app {
  display: grid;
  grid-template-rows: 60px 1fr;
  height: 100vh;
  overflow: hidden;
}

/* ── Header ── */
header {
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  padding: 0 28px;
  gap: 18px;
  z-index: 20;
}

.logo {
  display: flex;
  align-items: center;
  gap: 11px;
}

.logo-icon {
  width: 34px;
  height: 34px;
  background: linear-gradient(135deg, #3b82f6 0%, #8b5cf6 100%);
  border-radius: 9px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  box-shadow: 0 0 18px rgba(59,130,246,0.35);
}

.logo-name {
  font-size: 15px;
  font-weight: 700;
  color: var(--text);
  letter-spacing: -0.4px;
}

.logo-sub {
  font-size: 10.5px;
  color: var(--muted);
  font-weight: 400;
  letter-spacing: 0.01em;
}

.h-spacer { flex: 1; }

.live-badge {
  display: flex;
  align-items: center;
  gap: 7px;
  background: rgba(16,185,129,0.08);
  border: 1px solid rgba(16,185,129,0.22);
  border-radius: 100px;
  padding: 5px 13px;
  font-size: 11.5px;
  font-weight: 600;
  color: var(--green);
  letter-spacing: 0.02em;
}

.pulse-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
  animation: pulse 2.2s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50%       { opacity: 0.45; transform: scale(0.75); }
}

.clock-wrap {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 1px;
}

.clock-time {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--text);
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.04em;
}

.clock-date {
  font-size: 10px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}

/* ── Main scroll area ── */
main {
  overflow-y: auto;
  padding: 24px 28px 32px;
  display: flex;
  flex-direction: column;
  gap: 22px;
}

/* ── Section label ── */
.section-label {
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--muted);
  margin-bottom: 13px;
}

/* ── Stat cards ── */
.stats-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}

.stat-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 20px 22px;
  position: relative;
  overflow: hidden;
  transition: border-color 0.2s, transform 0.2s;
  cursor: default;
}

.stat-card::after {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: 14px;
  background: radial-gradient(ellipse at 80% 0%, var(--glow, rgba(59,130,246,0.06)) 0%, transparent 70%);
  pointer-events: none;
}

.stat-card:hover {
  border-color: var(--card-accent, var(--accent));
  transform: translateY(-2px);
}

.stat-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 16px;
}

.stat-icon-box {
  width: 38px;
  height: 38px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--icon-bg, rgba(59,130,246,0.1));
  border: 1px solid var(--icon-border, rgba(59,130,246,0.2));
}

.stat-tag {
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--muted);
}

.stat-num {
  font-size: 40px;
  font-weight: 700;
  letter-spacing: -2px;
  line-height: 1;
  color: var(--text);
  font-variant-numeric: tabular-nums;
  margin-bottom: 5px;
}

.stat-desc {
  font-size: 11.5px;
  color: var(--muted);
}

/* ── Content grid ── */
.content-grid {
  display: grid;
  grid-template-columns: 390px 1fr;
  gap: 20px;
  align-items: start;
}

/* ── Card ── */
.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  overflow: hidden;
}

.card-head {
  padding: 15px 22px;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.card-title {
  display: flex;
  align-items: center;
  gap: 9px;
  font-size: 13.5px;
  font-weight: 600;
  color: var(--text);
}

.card-title svg { flex-shrink: 0; }

.card-body { padding: 22px; }

/* ── Form ── */
.form-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 15px;
}

.form-field label {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.07em;
  text-transform: uppercase;
  color: var(--muted);
}

input[type=text], input[type=tel] {
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 9px;
  padding: 10px 14px;
  color: var(--text);
  font-family: inherit;
  font-size: 13.5px;
  outline: none;
  transition: border-color 0.18s, box-shadow 0.18s;
  width: 100%;
}

input[type=text]:focus, input[type=tel]:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px rgba(59,130,246,0.14);
}

input::placeholder { color: var(--dim); }

.hint-text {
  font-size: 11px;
  color: var(--muted);
  margin-top: 3px;
}

/* ── Call button ── */
.call-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 9px;
  width: 100%;
  padding: 13px;
  background: var(--accent);
  color: #fff;
  border: none;
  border-radius: 10px;
  font-family: inherit;
  font-size: 14.5px;
  font-weight: 600;
  cursor: pointer;
  letter-spacing: 0.01em;
  transition: background 0.15s, transform 0.15s, box-shadow 0.15s;
  margin-top: 4px;
  position: relative;
  overflow: hidden;
}

.call-btn::before {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(135deg, rgba(255,255,255,0.1) 0%, transparent 60%);
  pointer-events: none;
}

.call-btn:hover:not(:disabled) {
  background: #2563eb;
  transform: translateY(-1px);
  box-shadow: 0 6px 24px rgba(59,130,246,0.38);
}

.call-btn:active:not(:disabled) { transform: translateY(0); box-shadow: none; }

.call-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
  transform: none;
  box-shadow: none;
}

.call-btn .btn-label { display: flex; align-items: center; gap: 8px; }

.call-btn .btn-spinner {
  display: none;
  width: 18px;
  height: 18px;
  border: 2.5px solid rgba(255,255,255,0.35);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.65s linear infinite;
}

@keyframes spin { to { transform: rotate(360deg); } }

.call-btn.loading .btn-label   { display: none; }
.call-btn.loading .btn-spinner { display: block; }

/* ── Divider ── */
.divider {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 20px 0;
  color: var(--dim);
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.07em;
  text-transform: uppercase;
}

.divider::before, .divider::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--border);
}

/* ── How it works steps ── */
.steps { display: flex; flex-direction: column; gap: 11px; }

.step {
  display: flex;
  gap: 13px;
  align-items: flex-start;
}

.step-num {
  width: 24px;
  height: 24px;
  border-radius: 7px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 10.5px;
  font-weight: 700;
  flex-shrink: 0;
  margin-top: 1px;
}

.step-title  { font-size: 12.5px; font-weight: 500; color: var(--text); }
.step-detail { font-size: 11px; color: var(--muted); margin-top: 2px; }

/* ── Table search/actions ── */
.tbl-actions {
  display: flex;
  align-items: center;
  gap: 9px;
}

.search-box {
  position: relative;
}

.search-box svg {
  position: absolute;
  left: 10px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--muted);
  pointer-events: none;
  flex-shrink: 0;
}

.search-box input {
  padding: 7px 12px 7px 32px;
  height: 33px;
  font-size: 12.5px;
  border-radius: 8px;
  width: 195px;
}

.icon-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: rgba(255,255,255,0.04);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--muted);
  font-size: 12.5px;
  font-weight: 500;
  cursor: pointer;
  font-family: inherit;
  transition: background 0.15s, color 0.15s;
  white-space: nowrap;
}

.icon-btn:hover { background: rgba(255,255,255,0.08); color: var(--text); }

/* ── Table ── */
.tbl-wrap { overflow-x: auto; }

table { width: 100%; border-collapse: collapse; }

thead th {
  padding: 10px 18px;
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--muted);
  text-align: left;
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
  background: rgba(0,0,0,0.15);
}

tbody tr {
  border-bottom: 1px solid rgba(255,255,255,0.035);
  transition: background 0.13s;
}

tbody tr:last-child { border-bottom: none; }
tbody tr:hover { background: rgba(255,255,255,0.025); }

tbody td {
  padding: 13px 18px;
  font-size: 13px;
  vertical-align: middle;
}

.name-cell {
  display: flex;
  align-items: center;
  gap: 11px;
}

.avatar {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: var(--surface2);
  border: 1px solid var(--border2);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11.5px;
  font-weight: 700;
  color: var(--muted);
  text-transform: uppercase;
  flex-shrink: 0;
  letter-spacing: 0.5px;
}

.name-text { font-weight: 500; color: var(--text); }

.phone-val {
  font-family: 'SF Mono', 'Fira Code', 'Cascadia Code', monospace;
  font-size: 12px;
  color: var(--muted);
  letter-spacing: 0.04em;
}

.td-muted { color: var(--muted); font-size: 12.5px; }

/* ── Status badges ── */
.badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px 3px 8px;
  border-radius: 100px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  white-space: nowrap;
  border: 1px solid transparent;
}

.badge-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  flex-shrink: 0;
}

.b-active    { background: rgba(16,185,129,0.1);  color: #10b981; border-color: rgba(16,185,129,0.22); }
.b-calling   { background: rgba(245,158,11,0.1);  color: #f59e0b; border-color: rgba(245,158,11,0.22); }
.b-ringing   { background: rgba(96,165,250,0.1);  color: #60a5fa; border-color: rgba(96,165,250,0.22); }
.b-completed { background: rgba(100,116,139,0.08);color: #94a3b8; border-color: rgba(100,116,139,0.2); }
.b-failed    { background: rgba(239,68,68,0.1);   color: #ef4444; border-color: rgba(239,68,68,0.22); }

.b-active .badge-dot,
.b-calling .badge-dot,
.b-ringing .badge-dot { animation: pulse 1.6s ease-in-out infinite; }

/* ── Empty state ── */
.empty-state {
  padding: 64px 20px;
  text-align: center;
  color: var(--muted);
}

.empty-icon {
  width: 48px;
  height: 48px;
  border-radius: 14px;
  background: var(--surface2);
  border: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 14px;
}

.empty-state p { font-size: 13px; }
.empty-state span { font-size: 11.5px; color: var(--dim); display: block; margin-top: 4px; }

/* ── Auto-refresh pill ── */
.refresh-pill {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11.5px;
  color: var(--muted);
}

.refresh-pill .pulse-dot { color: var(--green); }

/* ── Toast ── */
#toasts {
  position: fixed;
  top: 18px;
  right: 20px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  z-index: 999;
  pointer-events: none;
}

.toast {
  pointer-events: all;
  display: flex;
  gap: 12px;
  align-items: flex-start;
  background: var(--surface2);
  border: 1px solid var(--border2);
  border-radius: 11px;
  padding: 13px 16px;
  min-width: 275px;
  max-width: 355px;
  box-shadow: 0 12px 40px rgba(0,0,0,0.5);
  animation: toastIn 0.22s cubic-bezier(.16,1,.3,1);
}

@keyframes toastIn  { from { transform: translateX(115%); opacity: 0; } }
@keyframes toastOut { to   { transform: translateX(115%); opacity: 0; } }

.toast.out { animation: toastOut 0.22s cubic-bezier(.7,0,.84,0) forwards; }

.toast-icon { flex-shrink: 0; margin-top: 1px; }
.toast-body { flex: 1; min-width: 0; }
.toast-title { font-size: 13px; font-weight: 600; margin-bottom: 2px; }
.toast-msg   { font-size: 12px; color: var(--muted); line-height: 1.45; }

.t-success { border-left: 3px solid var(--green); }
.t-error   { border-left: 3px solid var(--red); }
.t-info    { border-left: 3px solid var(--accent); }

/* ── Responsive ── */
@media (max-width: 1100px) {
  .content-grid { grid-template-columns: 340px 1fr; }
}

@media (max-width: 860px) {
  .stats-row { grid-template-columns: 1fr 1fr; }
  .content-grid { grid-template-columns: 1fr; }
}

@media (max-width: 480px) {
  main { padding: 16px; }
  header { padding: 0 16px; }
  .clock-wrap { display: none; }
}
</style>
</head>
<body>
<div class="app">

<!-- ═══════════════════════════ HEADER ═══════════════════════════ -->
<header>
  <div class="logo">
    <div class="logo-icon">
      <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round">
        <rect x="9" y="2" width="6" height="11" rx="3"/>
        <path d="M5 10a7 7 0 0 0 14 0"/>
        <line x1="12" y1="19" x2="12" y2="22"/>
        <line x1="8"  y1="22" x2="16" y2="22"/>
      </svg>
    </div>
    <div>
      <div class="logo-name">Saanvi AI</div>
      <div class="logo-sub">HR Voice Interview Agent</div>
    </div>
  </div>

  <div class="h-spacer"></div>

  <div class="refresh-pill">
    <div class="pulse-dot"></div>
    Auto&#8209;refresh 5s
  </div>

  <div class="live-badge">
    <div class="pulse-dot"></div>
    Server Online
  </div>

  <div class="clock-wrap">
    <div class="clock-time" id="clock-time">--:--:--</div>
    <div class="clock-date" id="clock-date">--- --, ----</div>
  </div>
</header>

<!-- ═══════════════════════════ MAIN ════════════════════════════ -->
<main>

  <!-- Stats -->
  <div>
    <p class="section-label">Overview</p>
    <div class="stats-row">

      <div class="stat-card" style="--card-accent:#3b82f6;--glow:rgba(59,130,246,0.08)">
        <div class="stat-top">
          <span class="stat-tag">Total Calls</span>
          <div class="stat-icon-box" style="--icon-bg:rgba(59,130,246,0.1);--icon-border:rgba(59,130,246,0.2)">
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07A19.5 19.5 0 0 1 4.69 13.4 19.79 19.79 0 0 1 1.62 4.76 2 2 0 0 1 3.59 2.58h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L7.91 10.1a16 16 0 0 0 6 6l.91-.91a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 21.5 17.5z"/>
            </svg>
          </div>
        </div>
        <div class="stat-num" id="s-total">—</div>
        <div class="stat-desc">All sessions initiated</div>
      </div>

      <div class="stat-card" style="--card-accent:#10b981;--glow:rgba(16,185,129,0.08)">
        <div class="stat-top">
          <span class="stat-tag">Active Now</span>
          <div class="stat-icon-box" style="--icon-bg:rgba(16,185,129,0.1);--icon-border:rgba(16,185,129,0.2)">
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>
            </svg>
          </div>
        </div>
        <div class="stat-num" id="s-active">—</div>
        <div class="stat-desc">Live interviews ongoing</div>
      </div>

      <div class="stat-card" style="--card-accent:#f59e0b;--glow:rgba(245,158,11,0.08)">
        <div class="stat-top">
          <span class="stat-tag">In Progress</span>
          <div class="stat-icon-box" style="--icon-bg:rgba(245,158,11,0.1);--icon-border:rgba(245,158,11,0.2)">
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="10"/>
              <polyline points="12 6 12 12 16 14"/>
            </svg>
          </div>
        </div>
        <div class="stat-num" id="s-progress">—</div>
        <div class="stat-desc">Calling + ringing</div>
      </div>

      <div class="stat-card" style="--card-accent:#64748b;--glow:rgba(100,116,139,0.06)">
        <div class="stat-top">
          <span class="stat-tag">Completed</span>
          <div class="stat-icon-box" style="--icon-bg:rgba(100,116,139,0.1);--icon-border:rgba(100,116,139,0.18)">
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="#64748b" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="20 6 9 17 4 12"/>
            </svg>
          </div>
        </div>
        <div class="stat-num" id="s-done">—</div>
        <div class="stat-desc">Finished interviews</div>
      </div>

    </div>
  </div>

  <!-- Content grid -->
  <div class="content-grid">

    <!-- ── New Call form ── -->
    <div class="card">
      <div class="card-head">
        <div class="card-title">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07A19.5 19.5 0 0 1 4.69 13.4 19.79 19.79 0 0 1 1.62 4.76 2 2 0 0 1 3.59 2.58h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L7.91 10.1a16 16 0 0 0 6 6l.91-.91a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 21.5 17.5z"/>
          </svg>
          Place New Call
        </div>
      </div>
      <div class="card-body">

        <div class="form-field">
          <label for="inp-phone">Phone Number</label>
          <input type="tel" id="inp-phone" placeholder="9876543210 or +919876543210" autocomplete="off">
          <p class="hint-text">10-digit number is auto-formatted to +91</p>
        </div>

        <div class="form-field">
          <label for="inp-name">Student Name</label>
          <input type="text" id="inp-name" placeholder="Full name (optional)" autocomplete="off">
        </div>

        <button class="call-btn" id="call-btn" onclick="placeCall()">
          <span class="btn-label">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07A19.5 19.5 0 0 1 4.69 13.4 19.79 19.79 0 0 1 1.62 4.76 2 2 0 0 1 3.59 2.58h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L7.91 10.1a16 16 0 0 0 6 6l.91-.91a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 21.5 17.5z"/>
            </svg>
            Call Student Now
          </span>
          <div class="btn-spinner"></div>
        </button>

        <div class="divider">How It Works</div>

        <div class="steps">
          <div class="step">
            <div class="step-num" style="background:rgba(59,130,246,0.1);border:1px solid rgba(59,130,246,0.22);color:#3b82f6">1</div>
            <div>
              <div class="step-title">Call Initiated</div>
              <div class="step-detail">Plivo dials the student's number via our number</div>
            </div>
          </div>
          <div class="step">
            <div class="step-num" style="background:rgba(245,158,11,0.1);border:1px solid rgba(245,158,11,0.22);color:#f59e0b">2</div>
            <div>
              <div class="step-title">Student Answers</div>
              <div class="step-detail">Saanvi greets them and begins the session</div>
            </div>
          </div>
          <div class="step">
            <div class="step-num" style="background:rgba(16,185,129,0.1);border:1px solid rgba(16,185,129,0.22);color:#10b981">3</div>
            <div>
              <div class="step-title">Live HR Interview</div>
              <div class="step-detail">AI-powered real-time practice interview begins</div>
            </div>
          </div>
          <div class="step">
            <div class="step-num" style="background:rgba(100,116,139,0.1);border:1px solid rgba(100,116,139,0.2);color:#94a3b8">4</div>
            <div>
              <div class="step-title">Session Complete</div>
              <div class="step-detail">Call ends, status updates automatically here</div>
            </div>
          </div>
        </div>

      </div>
    </div>

    <!-- ── Recent Calls table ── -->
    <div class="card">
      <div class="card-head">
        <div class="card-title">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>
            <circle cx="9" cy="7" r="4"/>
            <path d="M23 21v-2a4 4 0 0 0-3-3.87"/>
            <path d="M16 3.13a4 4 0 0 1 0 7.75"/>
          </svg>
          Recent Calls
        </div>
        <div class="tbl-actions">
          <div class="search-box">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
            </svg>
            <input type="text" id="search" placeholder="Search name or phone…" oninput="filterTable()">
          </div>
          <button class="icon-btn" onclick="loadData()">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
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
              <th>Student</th>
              <th>Phone</th>
              <th>Status</th>
              <th>Started</th>
              <th>Duration</th>
            </tr>
          </thead>
          <tbody id="tbl-body">
            <tr><td colspan="5"><div class="empty-state">
              <div class="empty-icon">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07A19.5 19.5 0 0 1 4.69 13.4 19.79 19.79 0 0 1 1.62 4.76 2 2 0 0 1 3.59 2.58h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L7.91 10.1a16 16 0 0 0 6 6l.91-.91a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 21.5 17.5z"/>
                </svg>
              </div>
              <p>No calls yet</p>
              <span>Place your first call using the form on the left</span>
            </div></td></tr>
          </tbody>
        </table>
      </div>
    </div>

  </div>
</main>
</div>

<!-- Toasts -->
<div id="toasts"></div>

<script>
// ── Clock ────────────────────────────────────────────────────────────
(function clockTick() {
  const now = new Date();
  document.getElementById('clock-time').textContent =
    now.toLocaleTimeString('en-IN', { hour12: false });
  document.getElementById('clock-date').textContent =
    now.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' });
  setTimeout(clockTick, 1000);
})();

// ── Data store ───────────────────────────────────────────────────────
let _allCalls = [];

// ── Fetch ────────────────────────────────────────────────────────────
async function loadData() {
  try {
    const [sRes, cRes] = await Promise.all([
      fetch('/api/stats'), fetch('/api/calls')
    ]);
    const stats = await sRes.json();
    const data  = await cRes.json();
    _allCalls   = data.calls || [];
    renderStats(stats);
    renderTable(_allCalls);
  } catch (e) {
    console.error('loadData:', e);
  }
}

// ── Render stats ─────────────────────────────────────────────────────
function renderStats(s) {
  setText('s-total',    s.total     ?? 0);
  setText('s-active',   s.active    ?? 0);
  setText('s-progress', (s.calling ?? 0) + (s.ringing ?? 0));
  setText('s-done',     s.completed ?? 0);
}

// ── Render table ─────────────────────────────────────────────────────
function renderTable(calls) {
  const q = (document.getElementById('search').value || '').trim().toLowerCase();
  const rows = q
    ? calls.filter(c => (c.name  || '').toLowerCase().includes(q)
                     || (c.phone || '').includes(q))
    : calls;

  const tbody = document.getElementById('tbl-body');

  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="5"><div class="empty-state">
      <div class="empty-icon">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07A19.5 19.5 0 0 1 4.69 13.4 19.79 19.79 0 0 1 1.62 4.76 2 2 0 0 1 3.59 2.58h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L7.91 10.1a16 16 0 0 0 6 6l.91-.91a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 21.5 17.5z"/>
        </svg>
      </div>
      <p>${q ? 'No results for "' + esc(q) + '"' : 'No calls yet'}</p>
      <span>${q ? 'Try a different search term' : 'Place your first call using the form on the left'}</span>
    </div></td></tr>`;
    return;
  }

  tbody.innerHTML = rows.map(c => {
    const initials = (c.name || 'S')
      .split(/\\s+/).map(w => w[0] || '').join('').slice(0, 2).toUpperCase();
    return `<tr>
      <td>
        <div class="name-cell">
          <div class="avatar">${esc(initials)}</div>
          <span class="name-text">${esc(c.name || 'Student')}</span>
        </div>
      </td>
      <td><span class="phone-val">${esc(c.phone || '—')}</span></td>
      <td>${badge(c.status)}</td>
      <td class="td-muted">${fmtTime(c.started_at)}</td>
      <td class="td-muted">${duration(c)}</td>
    </tr>`;
  }).join('');
}

function filterTable() { renderTable(_allCalls); }

// ── Place call ───────────────────────────────────────────────────────
async function placeCall() {
  const phone = (document.getElementById('inp-phone').value || '').trim();
  const name  = (document.getElementById('inp-name').value  || '').trim();

  if (!phone) {
    toast('error', 'Missing Phone', 'Enter a phone number before calling.');
    document.getElementById('inp-phone').focus();
    return;
  }

  const btn = document.getElementById('call-btn');
  btn.disabled = true;
  btn.classList.add('loading');

  try {
    const res  = await fetch('/make-call', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ phone, name }),
    });
    const data = await res.json();
    if (data.success) {
      toast('success', 'Call Placed', 'Dialing ' + (name || phone) + '…');
      document.getElementById('inp-phone').value = '';
      document.getElementById('inp-name').value  = '';
      setTimeout(loadData, 1800);
    } else {
      toast('error', 'Call Failed', data.error || 'Plivo returned an error.');
    }
  } catch (e) {
    toast('error', 'Network Error', e.message || 'Could not reach server.');
  } finally {
    btn.disabled = false;
    btn.classList.remove('loading');
  }
}

// Enter key on either input triggers call
['inp-phone', 'inp-name'].forEach(id => {
  document.getElementById(id).addEventListener('keydown', e => {
    if (e.key === 'Enter') placeCall();
  });
});

// ── Helpers ──────────────────────────────────────────────────────────
function setText(id, val) {
  document.getElementById(id).textContent = val;
}

function esc(s) {
  return String(s)
    .replace(/&/g,  '&amp;')
    .replace(/</g,  '&lt;')
    .replace(/>/g,  '&gt;')
    .replace(/"/g,  '&quot;');
}

function badge(status) {
  const map = {
    active:    ['b-active',    'Active'],
    calling:   ['b-calling',   'Calling'],
    ringing:   ['b-ringing',   'Ringing'],
    completed: ['b-completed', 'Completed'],
    failed:    ['b-failed',    'Failed'],
  };
  const [cls, label] = map[status] || ['b-completed', status || '—'];
  return `<span class="badge ${cls}"><span class="badge-dot"></span>${label}</span>`;
}

function fmtTime(ts) {
  if (!ts) return '—';
  return new Date(ts * 1000).toLocaleTimeString('en-IN', {
    hour: '2-digit', minute: '2-digit', hour12: true
  });
}

function duration(c) {
  if (!c.answered_at) return '—';
  const end  = c.ended_at || (Date.now() / 1000);
  const secs = Math.max(0, Math.floor(end - c.answered_at));
  if (secs < 60) return secs + 's';
  const m = Math.floor(secs / 60), s = secs % 60;
  return m + 'm ' + String(s).padStart(2, '0') + 's';
}

function toast(type, title, msg) {
  const icons = {
    success: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>`,
    error:   `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>`,
    info:    `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#60a5fa" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>`,
  };
  const el = document.createElement('div');
  el.className = `toast t-${type}`;
  el.innerHTML = `<div class="toast-icon">${icons[type] || ''}</div>
    <div class="toast-body">
      <div class="toast-title">${esc(title)}</div>
      <div class="toast-msg">${esc(msg)}</div>
    </div>`;
  document.getElementById('toasts').appendChild(el);
  setTimeout(() => {
    el.classList.add('out');
    el.addEventListener('animationend', () => el.remove());
  }, 4500);
}

// ── Auto-refresh ─────────────────────────────────────────────────────
loadData();
setInterval(loadData, 5000);
</script>
</body>
</html>"""
