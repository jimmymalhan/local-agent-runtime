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
        elif self.path == "/" or self.path == "/status.html":
            self.send_status_page()
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

    def send_status_page(self):
        """Send HTML status page."""
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
