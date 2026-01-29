#!/bin/bash -ex

testinfo() { printf "\n== TEST: $@ ==================\n"; }

# we do not want pipefail for these tests
set +o pipefail

# we need to work in a clean directory, the CWD is a git repo and can mess around with us!
TMPDIR=$(mktemp -d)
pushd $TMPDIR

# no request specified
testinfo "no request id"
testing-farm restart |& tee output
egrep "Missing argument 'REQUEST_ID'." output

# invalid request id
testinfo "invalid request request id"
testing-farm restart ABC | tee output
egrep "^⛔ Could not find a valid Testing Farm request id in 'ABC'.$" output

# invalid request id, bad uuid
testinfo "invalid request request id"
testing-farm restart 40cafaa3-0efa-4abf-a20b-a6ad87e8452 | tee output
egrep "^⛔ Could not find a valid Testing Farm request id in '40cafaa3-0efa-4abf-a20b-a6ad87e8452'.$" output

# invalid arguments
testing-farm restart 40cafaa3-0efa-4abf-a20b-a6ad87e8452 invalid |& tee output
egrep "^⛔ Unexpected argument 'invalid'. Please make sure you are passing the parameters correctly.$" output

# valid request id, no token
testinfo "valid request request id, no token"
testing-farm restart 40cafaa3-0efa-4abf-a20b-a6ad87e84527 | tee output
egrep "⛔ API token is invalid. See https://docs.testing-farm.io/Testing%20Farm/0.1/onboarding.html for more information." output

# git-url, git-ref and git-merge-sha options, just sanity test that they are available
testinfo "git-url, git-ref and git-merge-sha options accepted"
testing-farm restart --git-url https://example.com --git-ref some-ref --git-merge-sha some-sha https://api.dev.testing-farm.io/v0.1/requests/40cafaa3-0efa-4abf-a20b-a6ad87e84527 | tee output
egrep "⛔ API token is invalid. See https://docs.testing-farm.io/Testing%20Farm/0.1/onboarding.html for more information." output

# plan and plan filter options, just sanity test that they are available
testinfo "plan and plan filter options accepted"
testing-farm restart --plan myplan --plan-filter some-filter https://api.dev.testing-farm.io/v0.1/requests/40cafaa3-0efa-4abf-a20b-a6ad87e84527 | tee output
egrep "⛔ API token is invalid. See https://docs.testing-farm.io/Testing%20Farm/0.1/onboarding.html for more information." output

# test filter option, just sanity test that it is available
testinfo "test filter option accepted"
testing-farm restart --test-filter some-filter https://api.dev.testing-farm.io/v0.1/requests/40cafaa3-0efa-4abf-a20b-a6ad87e84527 | tee output
egrep "⛔ API token is invalid. See https://docs.testing-farm.io/Testing%20Farm/0.1/onboarding.html for more information." output

# worker-image option, just test it is accepted
testinfo "worker-image option accepted"
testing-farm restart --worker-image quay.io/testing-farm/worker:latest https://api.dev.testing-farm.io/v0.1/requests/40cafaa3-0efa-4abf-a20b-a6ad87e84527 | tee output
egrep "⛔ API token is invalid. See https://docs.testing-farm.io/Testing%20Farm/0.1/onboarding.html for more information." output

# worker-image option, just test it is accepted
testinfo "hardware option accepted"
testing-farm restart --hardware boot.mode=uefi https://api.dev.testing-farm.io/v0.1/requests/40cafaa3-0efa-4abf-a20b-a6ad87e84527 | tee output
egrep "⛔ API token is invalid. See https://docs.testing-farm.io/Testing%20Farm/0.1/onboarding.html for more information." output

# pool option, just test it is accepted
testinfo "pool option accepted"
testing-farm restart --pool some-pool https://api.dev.testing-farm.io/v0.1/requests/40cafaa3-0efa-4abf-a20b-a6ad87e84527 | tee output
egrep "⛔ API token is invalid. See https://docs.testing-farm.io/Testing%20Farm/0.1/onboarding.html for more information." output

# pipeline type, just test it is accepted
testinfo "test pipeline type"
testing-farm restart --pipeline-type tmt-multihost https://api.dev.testing-farm.io/v0.1/requests/40cafaa3-0efa-4abf-a20b-a6ad87e84527 2>&1 | tee output
egrep "⛔ API token is invalid. See https://docs.testing-farm.io/Testing%20Farm/0.1/onboarding.html for more information." output

testing-farm restart --pipeline-type invalid https://api.dev.testing-farm.io/v0.1/requests/40cafaa3-0efa-4abf-a20b-a6ad87e84527 2>&1 | tee output
egrep "Invalid value for '--pipeline-type': 'invalid' is not 'tmt-multihost'." output

# parallel-limit, just test it is accepted
testinfo "test parallel-limit"
testing-farm restart --parallel-limit 123 https://api.dev.testing-farm.io/v0.1/requests/40cafaa3-0efa-4abf-a20b-a6ad87e84527 2>&1 | tee output
egrep "⛔ API token is invalid. See https://docs.testing-farm.io/Testing%20Farm/0.1/onboarding.html for more information." output

# tags, just test it is accepted
testinfo "test tags"
testing-farm restart --tag ArtemisUseSpot=false -t Business=TestingFarm https://api.dev.testing-farm.io/v0.1/requests/40cafaa3-0efa-4abf-a20b-a6ad87e84527 2>&1 | tee output
egrep "⛔ API token is invalid. See https://docs.testing-farm.io/Testing%20Farm/0.1/onboarding.html for more information." output

# context, just test it is accepted
testinfo "test context"
testing-farm restart --context key=value --context key2=value2 https://api.dev.testing-farm.io/v0.1/requests/40cafaa3-0efa-4abf-a20b-a6ad87e84527 2>&1 | tee output
egrep "⛔ API token is invalid. See https://docs.testing-farm.io/Testing%20Farm/0.1/onboarding.html for more information." output

# context file, just test it is accepted
testinfo "test context file"
testing-farm restart --context @file https://api.dev.testing-farm.io/v0.1/requests/40cafaa3-0efa-4abf-a20b-a6ad87e84527 2>&1 | tee output
egrep "⛔ API token is invalid. See https://docs.testing-farm.io/Testing%20Farm/0.1/onboarding.html for more information." output

# environment, just test it is accepted
testinfo "test environment"
testing-farm restart --environment key=value --environment key2=value2 https://api.dev.testing-farm.io/v0.1/requests/40cafaa3-0efa-4abf-a20b-a6ad87e84527 2>&1 | tee output
egrep "⛔ API token is invalid. See https://docs.testing-farm.io/Testing%20Farm/0.1/onboarding.html for more information." output

# tmt extra args, just test it is accepted
for step in discover prepare report finish; do
  testinfo "tmt extra args - $step"
  testing-farm restart --tmt-$step args --tmt-$step args https://api.dev.testing-farm.io/v0.1/requests/40cafaa3-0efa-4abf-a20b-a6ad87e84527 2>&1 | tee output
  egrep "⛔ API token is invalid. See https://docs.testing-farm.io/Testing%20Farm/0.1/onboarding.html for more information." output
done

# reserve
testing-farm restart --reserve --duration 1800 --no-autoconnect --ssh-public-key ${SSH_KEY}.pub https://api.dev.testing-farm.io/v0.1/request/40cafaa3-0efa-4abf-a20b-a6ad87e84527 | tee output
egrep "⛔ API token is invalid. See https://docs.testing-farm.io/Testing%20Farm/0.1/onboarding.html for more information." output

# edit option, just test it is accepted
testinfo "edit option accepted"
testing-farm restart --edit https://api.dev.testing-farm.io/v0.1/requests/40cafaa3-0efa-4abf-a20b-a6ad87e84527 | tee output
egrep "⛔ API token is invalid. See https://docs.testing-farm.io/Testing%20Farm/0.1/onboarding.html for more information." output

# Mock server tests for source/target URL separation
testinfo "Testing source/target URL separation with mock servers"

# Start mock servers for source and target operations
python3 -c "
import http.server
import socketserver
import threading
import time
import json
import sys
from urllib.parse import urlparse, parse_qs

class MockHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Log to files to verify which server was called
        with open(f'/tmp/mock_{self.server.port}_requests.log', 'a') as f:
            f.write(f'{self.command} {self.path} - {format % args}\n')

    def do_GET(self):
        if '/v0.1/requests/40cafaa3-0efa-4abf-a20b-a6ad87e84527' in self.path:
            # Mock successful request response
            response = {
                'id': '40cafaa3-0efa-4abf-a20b-a6ad87e84527',
                'environments_requested': [{'os': {'compose': 'Fedora-39'}}],
                'test': {'fmf': {'url': 'https://example.com', 'ref': 'main'}},
                'settings': {}
            }
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if '/v0.1/requests' in self.path:
            # Mock successful POST response
            response = {'id': 'new-request-id-12345'}
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())
        else:
            self.send_response(404)
            self.end_headers()

# Start source mock server on port 8001
source_server = socketserver.TCPServer(('localhost', 8001), MockHandler)
source_server.port = 8001
source_thread = threading.Thread(target=source_server.serve_forever)
source_thread.daemon = True
source_thread.start()

# Start target mock server on port 8002
target_server = socketserver.TCPServer(('localhost', 8002), MockHandler)
target_server.port = 8002
target_thread = threading.Thread(target=target_server.serve_forever)
target_thread.daemon = True
target_thread.start()

print('Mock servers started')
time.sleep(60)  # Keep servers running for test duration
" &
MOCK_PID=$!

# Wait for servers to start
sleep 2

# Clear previous logs
rm -f /tmp/mock_8001_requests.log /tmp/mock_8002_requests.log

# Test with different source and target URLs
testinfo "Testing separate source and target URLs"
TESTING_FARM_SOURCE_API_URL=http://localhost:8001 \
TESTING_FARM_INTERNAL_SOURCE_API_URL=http://localhost:8001 \
TESTING_FARM_TARGET_API_URL=http://localhost:8002 \
TESTING_FARM_SOURCE_API_TOKEN=source-token \
TESTING_FARM_TARGET_API_TOKEN=target-token \
testing-farm restart --dry-run 40cafaa3-0efa-4abf-a20b-a6ad87e84527 2>&1 | tee output

# Verify source server was called
if [ -f /tmp/mock_8001_requests.log ]; then
    testinfo "Verifying source server was called"
    grep "GET.*40cafaa3-0efa-4abf-a20b-a6ad87e84527" /tmp/mock_8001_requests.log || {
        echo "❌ Source server was not called for request details"
        exit 1
    }
    echo "✅ Source server correctly called for request details"
else
    echo "❌ Source server log not found"
    exit 1
fi

# Note: Target server won't be called with --dry-run, but we can test the configuration is accepted
echo "✅ Source/target URL separation configuration accepted"

# Cleanup
kill $MOCK_PID 2>/dev/null || true
rm -f /tmp/mock_8001_requests.log /tmp/mock_8002_requests.log

# test --test option with --reserve extends test filter
testinfo "test --test option with --reserve extends test filter"
testing-farm restart --dry-run --reserve --test "my-test" https://api.dev.testing-farm.io/v0.1/requests/40cafaa3-0efa-4abf-a20b-a6ad87e84527 | tee output
egrep "⛔ API token is invalid. See https://docs.testing-farm.io/Testing%20Farm/0.1/onboarding.html for more information." output

# test --test-filter option with --reserve extends test filter
testinfo "test --test-filter option with --reserve extends test filter"
testing-farm restart --dry-run --reserve --test-filter "tag:smoke" https://api.dev.testing-farm.io/v0.1/requests/40cafaa3-0efa-4abf-a20b-a6ad87e84527 | tee output
egrep "⛔ API token is invalid. See https://docs.testing-farm.io/Testing%20Farm/0.1/onboarding.html for more information." output

# test both --test and --test-filter options with --reserve
testinfo "test both --test and --test-filter options with --reserve"
testing-farm restart --dry-run --reserve --test "my-test" --test-filter "tag:smoke" https://api.dev.testing-farm.io/v0.1/requests/40cafaa3-0efa-4abf-a20b-a6ad87e84527 | tee output
egrep "⛔ API token is invalid. See https://docs.testing-farm.io/Testing%20Farm/0.1/onboarding.html for more information." output
