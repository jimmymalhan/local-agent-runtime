#!/usr/bin/env python3
"""
Status Server — Simple HTTP server to display live status
Serves status.html which displays LIVE_STATUS.json and LIVE_STATUS.txt
"""

import json
import os
import sys
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
from datetime import datetime

BASE_DIR = str(Path(__file__).parent.parent)
STATUS_DIR = os.path.join(BASE_DIR, "state")
DASHBOARD_DIR = os.path.join(BASE_DIR, "dashboard")

PORT = 9999


class StatusHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        """Handle GET requests."""
        if self.path == "/api/status":
            self.send_status_json()
        elif self.path == "/api/status.txt":
            self.send_status_text()
        elif self.path == "/api/dashboard":
            self.send_comprehensive_json()
        elif self.path == "/" or self.path == "/status.html" or self.path == "/dashboard":
            self.send_comprehensive_page()
        else:
            self.send_error(404)

    def send_status_json(self):
        """Send JSON status."""
        try:
            status_file = os.path.join(STATUS_DIR, "LIVE_STATUS.json")
            with open(status_file) as f:
                data = json.load(f)

            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())
        except Exception as e:
            self.send_error(500, str(e))

    def send_status_text(self):
        """Send text status."""
        try:
            status_file = os.path.join(STATUS_DIR, "LIVE_STATUS.txt")
            with open(status_file) as f:
                content = f.read()

            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(content.encode())
        except Exception as e:
            self.send_error(500, str(e))

    def send_comprehensive_json(self):
        """Send comprehensive dashboard JSON."""
        try:
            dashboard_file = os.path.join(STATUS_DIR, "COMPREHENSIVE_DASHBOARD.json")
            with open(dashboard_file) as f:
                data = json.load(f)

            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())
        except Exception as e:
            self.send_error(500, str(e))

    def send_comprehensive_page(self):
        """Send comprehensive unified dashboard HTML."""
        html = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>🚀 Local Agent Runtime — Live Status</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            background: linear-gradient(135deg, #0f1419 0%, #1a2332 100%);
            color: #e1e8ed;
            padding: 20px;
            min-height: 100vh;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        header {
            text-align: center;
            margin-bottom: 40px;
            padding-bottom: 20px;
            border-bottom: 2px solid #00ff88;
        }
        h1 {
            font-size: 32px;
            color: #00ff88;
            margin-bottom: 5px;
        }
        .subtitle {
            color: #94a3b8;
            font-size: 14px;
        }
        .status-container {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin-bottom: 30px;
        }
        .status-box {
            background: #1e293b;
            border: 1px solid #334155;
            border-radius: 8px;
            padding: 20px;
            transition: all 0.3s ease;
        }
        .status-box:hover {
            border-color: #00ff88;
            box-shadow: 0 4px 12px rgba(0, 255, 136, 0.2);
        }
        .status-title {
            font-size: 14px;
            font-weight: 600;
            color: #cbd5e1;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 12px;
        }
        .status-value {
            font-size: 28px;
            font-weight: 700;
            color: #00ff88;
            margin-bottom: 8px;
        }
        .status-detail {
            font-size: 13px;
            color: #94a3b8;
            line-height: 1.6;
        }
        .blockers {
            background: #1e293b;
            border: 1px solid #334155;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 20px;
        }
        .blockers-title {
            font-size: 14px;
            font-weight: 600;
            color: #cbd5e1;
            text-transform: uppercase;
            margin-bottom: 12px;
        }
        .blocker-item {
            padding: 10px;
            margin-bottom: 8px;
            border-radius: 6px;
            font-size: 13px;
            border-left: 4px solid #00ff88;
            background: #0f1419;
        }
        .blocker-item.error {
            border-left-color: #ff3333;
            color: #fca5a5;
        }
        .blocker-item.warning {
            border-left-color: #ffaa00;
            color: #fed7aa;
        }
        .live-text {
            background: #0f1419;
            border: 1px solid #334155;
            border-radius: 8px;
            padding: 20px;
            font-family: 'Courier New', monospace;
            font-size: 11px;
            color: #00ff88;
            white-space: pre-wrap;
            word-wrap: break-word;
            max-height: 600px;
            overflow-y: auto;
            line-height: 1.5;
        }
        .footer {
            text-align: center;
            color: #64748b;
            font-size: 12px;
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid #334155;
        }
        .refresh-info {
            text-align: center;
            color: #94a3b8;
            font-size: 12px;
            margin-bottom: 20px;
        }
        @media (max-width: 768px) {
            .status-container {
                grid-template-columns: 1fr;
            }
            h1 { font-size: 24px; }
            .status-value { font-size: 22px; }
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🚀 Local Agent Runtime</h1>
            <p class="subtitle">Beating Opus 4.6 • 24/7 Operations • Live Status</p>
        </header>

        <div class="refresh-info">
            Auto-updating every 5 seconds • Last update: <span id="last-update">loading...</span>
        </div>

        <div class="status-container">
            <div class="status-box">
                <div class="status-title">📊 Primary Agents</div>
                <div class="status-value" id="agents">10/10</div>
                <div class="status-detail" id="agents-detail">Loading...</div>
            </div>

            <div class="status-box">
                <div class="status-title">🤖 Sub-Agents</div>
                <div class="status-value" id="sub-agents">2</div>
                <div class="status-detail" id="sub-agents-detail">Dynamic spawning</div>
            </div>

            <div class="status-box">
                <div class="status-title">⏰ 24/7 Operations</div>
                <div class="status-value">✓</div>
                <div class="status-detail">Orchestrator ✓<br>Task intake ✓<br>Auto-restart ✓</div>
            </div>

            <div class="status-box">
                <div class="status-title">📈 Progress</div>
                <div class="status-value" id="progress">v5</div>
                <div class="status-detail" id="progress-detail">5% complete</div>
            </div>
        </div>

        <div class="blockers">
            <div class="blockers-title">🚫 Blockers & Status</div>
            <div id="blockers-list"></div>
        </div>

        <div>
            <h2 style="color: #cbd5e1; margin-bottom: 15px; font-size: 16px;">📜 Full Status Report</h2>
            <div class="live-text" id="status-text">Loading status...</div>
        </div>

        <div class="footer">
            <p>System monitoring • Health checks every 30 minutes • Auto-healing enabled</p>
            <p style="margin-top: 8px; color: #475569;">Running from: /Users/jimmymalhan/Documents/local-agent-runtime</p>
        </div>
    </div>

    <script>
        async function updateStatus() {
            try {
                const response = await fetch('/api/status');
                const data = await response.json();

                // Update timestamp
                document.getElementById('last-update').textContent =
                    new Date(data.timestamp).toLocaleTimeString();

                // Update agents
                const agents = data.agents;
                document.getElementById('agents').textContent = `${agents.primary_count}/10`;
                document.getElementById('agents-detail').textContent =
                    `Active: ${agents.active.join(', ') || 'none'}`;

                // Update sub-agents
                document.getElementById('sub-agents').textContent = agents.sub_agents_count;
                document.getElementById('sub-agents-detail').textContent =
                    `Spawned and running (max 250+)`;

                // Update progress
                const progress = data.progress;
                document.getElementById('progress').textContent =
                    `v${progress.current_version}`;
                document.getElementById('progress-detail').textContent =
                    `${progress.pct_complete}% complete • ETA: v${progress.target_version}`;

                // Update blockers
                const blockersList = document.getElementById('blockers-list');
                blockersList.innerHTML = '';
                if (data.blockers.length === 0) {
                    const item = document.createElement('div');
                    item.className = 'blocker-item';
                    item.textContent = '✅ NONE — System operating normally';
                    blockersList.appendChild(item);
                } else {
                    data.blockers.forEach(blocker => {
                        const item = document.createElement('div');
                        item.className = 'blocker-item ' +
                            (blocker.includes('❌') ? 'error' : 'warning');
                        item.textContent = blocker;
                        blockersList.appendChild(item);
                    });
                }

                // Update full status text
                const textResponse = await fetch('/api/status.txt');
                const text = await textResponse.text();
                document.getElementById('status-text').textContent = text;

            } catch (error) {
                console.error('Update error:', error);
                document.getElementById('status-text').textContent =
                    'Error loading status: ' + error.message;
            }
        }

        // Initial update
        updateStatus();

        // Auto-update every 5 seconds
        setInterval(updateStatus, 5000);
    </script>
</body>
</html>
        """
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(html.encode())


def run_server():
    """Run the status server."""
    server_address = ("", PORT)
    httpd = HTTPServer(server_address, StatusHandler)
    print(f"🚀 Status Server running on http://localhost:{PORT}")
    print(f"📊 View live status at: http://localhost:{PORT}/")
    print(f"📜 Text status at: http://localhost:{PORT}/api/status.txt")
    print(f"📋 JSON status at: http://localhost:{PORT}/api/status")
    print("")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 Server stopped")
        sys.exit(0)


if __name__ == "__main__":
    run_server()

        html_comprehensive = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>🚀 Agent Runtime — Unified Dashboard</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        html { scroll-behavior: smooth; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            background: linear-gradient(135deg, #0f1419 0%, #1a2332 100%);
            color: #e1e8ed;
            padding: 20px;
            min-height: 100vh;
        }
        .container { max-width: 1400px; margin: 0 auto; }
        header {
            text-align: center;
            margin-bottom: 40px;
            padding: 30px;
            background: linear-gradient(90deg, #00ff88 0%, #00ccff 100%);
            background-clip: text;
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            border-bottom: 2px solid #00ff88;
        }
        h1 { font-size: 36px; margin-bottom: 5px; }
        .subtitle { color: #94a3b8; font-size: 14px; margin-top: 10px; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; margin-bottom: 30px; }
        .card {
            background: #1e293b;
            border: 1px solid #334155;
            border-radius: 8px;
            padding: 20px;
            transition: all 0.3s ease;
        }
        .card:hover { border-color: #00ff88; box-shadow: 0 4px 12px rgba(0, 255, 136, 0.2); }
        .card-title { font-size: 12px; font-weight: 600; color: #cbd5e1; text-transform: uppercase; margin-bottom: 12px; letter-spacing: 0.5px; }
        .card-value { font-size: 28px; font-weight: 700; color: #00ff88; margin-bottom: 8px; }
        .card-detail { font-size: 13px; color: #94a3b8; line-height: 1.6; }
        .full-width { grid-column: 1 / -1; }
        .tabs {
            display: flex;
            gap: 10px;
            margin-bottom: 30px;
            border-bottom: 1px solid #334155;
            overflow-x: auto;
        }
        .tab {
            padding: 12px 20px;
            border: none;
            background: none;
            color: #94a3b8;
            cursor: pointer;
            border-bottom: 2px solid transparent;
            transition: all 0.3s ease;
            font-weight: 600;
            text-transform: uppercase;
            font-size: 12px;
        }
        .tab.active {
            color: #00ff88;
            border-bottom-color: #00ff88;
        }
        .tab-content { display: none; }
        .tab-content.active { display: block; }
        .section {
            background: #1e293b;
            border: 1px solid #334155;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 20px;
        }
        .section-title { font-size: 16px; font-weight: 600; color: #00ff88; margin-bottom: 15px; }
        .item-list { list-style: none; }
        .item {
            padding: 12px;
            background: #0f1419;
            border-left: 4px solid #334155;
            margin-bottom: 10px;
            border-radius: 4px;
            font-size: 13px;
        }
        .item.success { border-left-color: #00ff88; }
        .item.warning { border-left-color: #ffaa00; }
        .item.error { border-left-color: #ff3333; }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 12px;
            margin-top: 15px;
        }
        th, td {
            padding: 10px;
            text-align: left;
            border-bottom: 1px solid #334155;
        }
        th {
            background: #0f1419;
            font-weight: 600;
            color: #cbd5e1;
        }
        .priority { display: inline-block; padding: 2px 8px; border-radius: 3px; font-size: 10px; font-weight: 600; }
        .p0 { background: #7f1d1d; color: #fca5a5; }
        .p1 { background: #78350f; color: #fed7aa; }
        .status-badge {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 11px;
            font-weight: 600;
        }
        .status-running { background: #064e3b; color: #86efac; }
        .status-pending { background: #1e3a8a; color: #93c5fd; }
        .footer { text-align: center; color: #64748b; font-size: 12px; margin-top: 40px; padding-top: 20px; border-top: 1px solid #334155; }
        .last-updated { color: #64748b; font-size: 11px; margin-top: 5px; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🚀 LOCAL AGENT RUNTIME</h1>
            <p class="subtitle">Unified Comprehensive Dashboard • All Information in One Place</p>
            <p class="last-updated">Last updated: <span id="last-update">—</span> • Auto-refreshing every 5 seconds</p>
        </header>

        <div class="grid">
            <div class="card">
                <div class="card-title">🏃 Primary Agents</div>
                <div class="card-value" id="agent-count">10/10</div>
                <div class="card-detail" id="agents-running">Loading...</div>
            </div>
            <div class="card">
                <div class="card-title">🤖 Sub-Agents</div>
                <div class="card-value" id="sub-agent-count">2</div>
                <div class="card-detail" id="sub-agent-detail">Dynamically spawned</div>
            </div>
            <div class="card">
                <div class="card-title">📁 Projects</div>
                <div class="card-value" id="project-count">5</div>
                <div class="card-detail" id="project-detail">Tasks tracked</div>
            </div>
            <div class="card">
                <div class="card-title">📋 Tasks</div>
                <div class="card-value" id="task-count">5</div>
                <div class="card-detail" id="task-detail">In progress</div>
            </div>
            <div class="card">
                <div class="card-title">📈 Version</div>
                <div class="card-value" id="version">v5</div>
                <div class="card-detail" id="version-detail">5% → v106</div>
            </div>
            <div class="card">
                <div class="card-title">⏰ 24/7 Status</div>
                <div class="card-value">✓</div>
                <div class="card-detail">Fully operational & autonomous</div>
            </div>
        </div>

        <div class="tabs">
            <button class="tab active" data-tab="overview">Overview</button>
            <button class="tab" data-tab="agents">Agents</button>
            <button class="tab" data-tab="projects">Projects & Tasks</button>
            <button class="tab" data-tab="version">Version & Progress</button>
            <button class="tab" data-tab="blockers">Blockers & Improvements</button>
        </div>

        <!-- Overview Tab -->
        <div id="overview" class="tab-content active">
            <div class="section">
                <div class="section-title">⏰ 24/7 Operations Status</div>
                <div class="grid" style="grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));  gap: 15px;">
                    <div class="item success">
                        <strong>✅ Orchestrator</strong><br>
                        <span id="orch-status">Running (2 processes)</span>
                    </div>
                    <div class="item success">
                        <strong>✅ Task Intake</strong><br>
                        <span>Continuous mode active</span>
                    </div>
                    <div class="item success">
                        <strong>✅ Health Monitor</strong><br>
                        <span>Every 30 minutes</span>
                    </div>
                    <div class="item success">
                        <strong>✅ Auto-Restart</strong><br>
                        <span>Enabled via launchd</span>
                    </div>
                </div>
            </div>

            <div class="section">
                <div class="section-title">🚫 Current Blockers & Improvements</div>
                <div id="blockers-improvements"></div>
            </div>
        </div>

        <!-- Agents Tab -->
        <div id="agents" class="tab-content">
            <div class="section">
                <div class="section-title">👥 Primary Agents (10 Total)</div>
                <table>
                    <thead>
                        <tr>
                            <th>Agent</th>
                            <th>Status</th>
                            <th>Current Task</th>
                            <th>Quality</th>
                            <th>Sub-Agents</th>
                        </tr>
                    </thead>
                    <tbody id="agents-table"></tbody>
                </table>
            </div>

            <div class="section">
                <div class="section-title">🤖 Sub-Agents Details</div>
                <div id="sub-agents-detail"></div>
            </div>
        </div>

        <!-- Projects & Tasks Tab -->
        <div id="projects" class="tab-content">
            <div id="projects-sections"></div>
        </div>

        <!-- Version & Progress Tab -->
        <div id="version" class="tab-content">
            <div class="section">
                <div class="section-title">📊 Version & Progress Tracking</div>
                <div class="grid" style="grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 20px;">
                    <div>
                        <strong style="color: #00ff88;">Current Version</strong>
                        <div style="font-size: 24px; color: #00ff88; margin-top: 8px;" id="version-current">v5</div>
                    </div>
                    <div>
                        <strong style="color: #00ff88;">Progress</strong>
                        <div style="font-size: 24px; color: #00ff88; margin-top: 8px;" id="version-progress">5%</div>
                    </div>
                    <div>
                        <strong style="color: #00ff88;">Target</strong>
                        <div style="font-size: 24px; color: #00ff88; margin-top: 8px;" id="version-target">v106</div>
                    </div>
                    <div>
                        <strong style="color: #00ff88;">ETA</strong>
                        <div style="font-size: 24px; color: #00ff88; margin-top: 8px;" id="version-eta">~100h</div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Blockers Tab -->
        <div id="blockers" class="tab-content">
            <div class="section">
                <div class="section-title">🚫 Blockers</div>
                <div id="blockers-list"></div>
            </div>
            <div class="section">
                <div class="section-title">💡 Improvements to Implement</div>
                <div id="improvements-list"></div>
            </div>
        </div>

        <div class="footer">
            <p>🚀 Fully autonomous system • Running 24/7 • Target: Beat Opus 4.6 by v106</p>
            <p>Status updated every 5 seconds • Health checks every 30 minutes • Reports auto-generated</p>
        </div>
    </div>

    <script>
        const API_URL = '/api/dashboard';
        
        // Tab switching
        document.querySelectorAll('.tab').forEach(tab => {
            tab.addEventListener('click', () => {
                document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
                document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
                tab.classList.add('active');
                const tabId = tab.dataset.tab;
                document.getElementById(tabId)?.classList.add('active');
            });
        });

        async function updateDashboard() {
            try {
                const response = await fetch(API_URL);
                const data = await response.json();

                // Update timestamp
                document.getElementById('last-update').textContent = 
                    new Date(data.timestamp).toLocaleTimeString();

                // Update agent counts
                const agents = data.agents || {};
                document.getElementById('agent-count').textContent = 
                    `${agents.total || 0}/10`;
                document.getElementById('agents-running').textContent = 
                    agents.primary_agents?.slice(0, 3).map(a => a.name).join(', ') + (agents.total > 3 ? '...' : '');

                // Update sub-agents
                const subAgents = data.sub_agents || {};
                document.getElementById('sub-agent-count').textContent = subAgents.total || 0;

                // Update projects & tasks
                const projects = data.projects || {};
                document.getElementById('project-count').textContent = projects.total || 0;
                const taskCount = projects.projects?.reduce((sum, p) => sum + (p.tasks?.length || 0), 0) || 0;
                document.getElementById('task-count').textContent = taskCount;

                // Update version
                const version = data.version || {};
                document.getElementById('version').textContent = `v${version.current || '?'}`;
                document.getElementById('version-detail').textContent = 
                    `${version.pct_complete || 0}% → v${version.target || '?'}`;

                // Populate Agents Table
                const agentsTable = document.getElementById('agents-table');
                agentsTable.innerHTML = '';
                agents.primary_agents?.forEach(agent => {
                    const row = document.createElement('tr');
                    row.innerHTML = `
                        <td><strong>${agent.name}</strong></td>
                        <td><span class="status-badge status-${agent.status}">${agent.status}</span></td>
                        <td>${agent.current_task?.substring(0, 40) || '-'}</td>
                        <td>${agent.quality_score || 0}</td>
                        <td>${agent.sub_agents || 0}</td>
                    `;
                    agentsTable.appendChild(row);
                });

                // Populate Projects
                const projectsSections = document.getElementById('projects-sections');
                projectsSections.innerHTML = '';
                projects.projects?.forEach(project => {
                    const section = document.createElement('div');
                    section.className = 'section';
                    section.innerHTML = `
                        <div class="section-title">${project.name}</div>
                        <p style="color: #94a3b8; margin-bottom: 15px;">${project.description}</p>
                        <table>
                            <thead>
                                <tr>
                                    <th>Task</th>
                                    <th>Status</th>
                                    <th>Priority</th>
                                    <th>Agent</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${project.tasks?.map(task => `
                                    <tr>
                                        <td><strong>${task.title?.substring(0, 50)}</strong></td>
                                        <td><span class="status-badge status-${task.status}">${task.status}</span></td>
                                        <td><span class="priority ${task.priority?.toLowerCase()}">${task.priority}</span></td>
                                        <td>${task.agent}</td>
                                    </tr>
                                `).join('') || '<tr><td colspan="4">No tasks</td></tr>'}
                            </tbody>
                        </table>
                    `;
                    projectsSections.appendChild(section);
                });

                // Populate Version info
                document.getElementById('version-current').textContent = `v${version.current || '?'}`;
                document.getElementById('version-progress').textContent = `${version.pct_complete || 0}%`;
                document.getElementById('version-target').textContent = `v${version.target || '?'}`;
                document.getElementById('version-eta').textContent = `${version.hours_remaining || 0}h`;

                // Populate Blockers & Improvements
                const bi = data.blockers_and_improvements || {};
                const blockersHTML = bi.blockers?.length > 0 && bi.blockers[0] !== 'NONE'
                    ? bi.blockers.map(b => `<div class="item error">❌ ${b}</div>`).join('')
                    : '<div class="item success">✅ NONE — System operating normally</div>';
                document.getElementById('blockers-list').innerHTML = blockersHTML;

                const improvementsHTML = bi.improvements?.length > 0
                    ? bi.improvements.map(i => `<div class="item warning">💡 ${i}</div>`).join('')
                    : '<div class="item success">✅ System optimized</div>';
                document.getElementById('improvements-list').innerHTML = improvementsHTML;

                // Populate blockers in overview
                const blockersImprovementsHTML = `
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px;">
                        <div>
                            <strong style="color: #ff3333; display: block; margin-bottom: 10px;">Blockers</strong>
                            ${blockersHTML}
                        </div>
                        <div>
                            <strong style="color: #ffaa00; display: block; margin-bottom: 10px;">Improvements</strong>
                            ${improvementsHTML}
                        </div>
                    </div>
                `;
                document.getElementById('blockers-improvements').innerHTML = blockersImprovementsHTML;

            } catch (error) {
                console.error('Update error:', error);
            }
        }

        updateDashboard();
        setInterval(updateDashboard, 5000); // Update every 5 seconds
    </script>
</body>
</html>
        """
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(html_comprehensive.encode())

