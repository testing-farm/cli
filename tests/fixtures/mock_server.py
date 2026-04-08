# Copyright Contributors to the Testing Farm project.
# SPDX-License-Identifier: Apache-2.0

"""
Generic mock HTTP server for Testing Farm API tests.

Usage: python3 mock_server.py <port>

Fixtures are loaded from the same directory as this script:

    <script_dir>/<REQUEST_ID>/<HTTP_METHOD>.json   - GET /v0.1/requests/<REQUEST_ID>
    <script_dir>/<REQUEST_ID>/<FILE_NAME>          - GET /artifacts/<REQUEST_ID>/<FILE_NAME>

The run.artifacts URL in get.json is automatically rewritten to point to
http://localhost:<port>/<REQUEST_ID> so artifact fetches hit this server.
"""

import http.server
import json
import os
import socketserver
import sys
import threading


class MockTCPServer(socketserver.TCPServer):
    allow_reuse_address = True


class MockHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        fixtures_dir = self.server.fixtures_dir
        port = self.server.port

        # Match /v0.1/requests/<REQUEST_ID>
        prefix = '/v0.1/requests/'
        if self.path.startswith(prefix):
            request_id = self.path[len(prefix) :]

            # If a 403.json marker exists and the request has an Authorization
            # header, return 403 to simulate a non-owner access.
            marker_403 = os.path.join(fixtures_dir, request_id, '403.json')
            if os.path.isfile(marker_403) and self.headers.get('Authorization'):
                self.send_response(403)
                self.end_headers()
                return

            json_path = os.path.join(fixtures_dir, request_id, 'get.json')
            if os.path.isfile(json_path):
                with open(json_path, 'r') as f:
                    data = json.load(f)
                # Rewrite artifacts URL to point to this mock server
                if 'run' in data and 'artifacts' in data['run']:
                    data['run']['artifacts'] = f'http://localhost:{port}/artifacts/{request_id}'
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(data).encode('utf-8'))
                return

        # Match /artifacts/<REQUEST_ID>/<FILE>
        prefix = '/artifacts/'
        if self.path.startswith(prefix):
            file_path = os.path.join(fixtures_dir, self.path[len(prefix) :])
            if os.path.isfile(file_path):
                with open(file_path, 'r') as f:
                    content = f.read()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(content.encode('utf-8'))
                return

        self.send_response(404)
        self.end_headers()


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: python3 mock_server.py <port>")
        sys.exit(1)

    port = int(sys.argv[1])
    fixtures_dir = os.path.dirname(os.path.abspath(__file__))

    server = MockTCPServer(('localhost', port), MockHandler)
    server.port = port
    server.fixtures_dir = fixtures_dir

    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()

    print(f"Mock server running on port {port}")

    try:
        server_thread.join()
    except KeyboardInterrupt:
        server.shutdown()
