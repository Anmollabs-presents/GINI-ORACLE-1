#!/usr/bin/env python3
"""
GINI-AI Frontend Development Server
Serves frontend files on http://localhost:3000
Supports CORS for backend on http://localhost:8000
"""

import http.server
import socketserver
import os
import sys
from pathlib import Path

PORT = 3000
FRONTEND_DIR = Path(__file__).parent

class CORSRequestHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
        return super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        # Custom logging
        client_ip = self.client_address[0]
        print(f'[{client_ip}] {format%args}', file=sys.stderr)

if __name__ == '__main__':
    os.chdir(FRONTEND_DIR)
    
    try:
        with socketserver.TCPServer(("", PORT), CORSRequestHandler) as httpd:
            print(f"""
╔════════════════════════════════════════╗
║    GINI-AI Frontend Dev Server         ║
╚════════════════════════════════════════╝

🌐 Serving on:     http://localhost:{PORT}
📁 Directory:      {FRONTEND_DIR}
🔌 Backend:        http://localhost:8000
🛑 Stop with:      Ctrl+C

            """)
            httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n✓ Server stopped")
        sys.exit(0)
    except OSError as e:
        print(f"❌ Error: {e}")
        if "Address already in use" in str(e):
            print(f"   Port {PORT} is already in use. Try changing PORT in this script.")
        sys.exit(1)
