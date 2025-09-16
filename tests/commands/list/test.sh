#!/bin/bash -ex

testinfo() { printf "\n== TEST: $@ ==================\n"; }

# we do not want pipefail for these tests
set +o pipefail

# we need to work in a clean directory, the CWD is a git repo and can mess around with us!
TMPDIR=$(mktemp -d)
pushd $TMPDIR

# no token - requires token for default --mine behavior
testinfo "no token specified"
testing-farm list | tee output
grep -E "^⛔ No API token found" output

# test with invalid token - should fail for authenticated requests
export TESTING_FARM_API_TOKEN=invalid

testinfo "invalid token with --mine"
testing-farm list --mine | tee output
grep -E "^⛔ API token is invalid" output

# test default behavior (--mine is default)
testinfo "default behavior shows user requests"
testing-farm list | tee output
grep -E "^⛔ API token is invalid" output

# test --all flag without token
unset TESTING_FARM_API_TOKEN
testinfo "list all requests without token"
testing-farm list --all --age 1h --format text

# test various output formats
testinfo "test json output format"
testing-farm list --all --age 1h --format json

testinfo "test yaml output format"
testing-farm list --all --age 1h --format yaml

testinfo "test table output format"
testing-farm list --all --age 1h --format table

testinfo "test text output format"
testing-farm list --all --age 1h --format text

# test state filtering
testinfo "test state filtering"
testing-farm list --all --age 1h --state complete --format text

# test age filtering
testinfo "test age filtering"
testing-farm list --all --age 30m --format text
testing-farm list --all --age 1h --format text

# test minimum age
testinfo "test minimum age filtering"
testing-farm list --all --age 1h --min-age 30m --format text

# test brief output
testinfo "test brief output"
testing-farm list --all --age 1h --brief --format text

# test showing secrets (can only be used with --id)
testinfo "test show secrets restriction"
testing-farm list --all --age 1h --show-secrets 2>&1 | tee output
grep -E "^⛔.*--show-secrets.*--id" output

# test show user flag
testinfo "test show user flag"
testing-farm list --all --age 1h --show-token-id --format text

# test time display options
testinfo "test time display options"
testing-farm list --all --age 1h --show-time --format text
testing-farm list --all --age 1h --show-utc --format text

# test ranch filtering
testinfo "test ranch filtering"
testing-farm list --all --age 1h --ranch public --format text
testing-farm list --all --age 1h --ranch redhat --format text

# test request ID filtering (requires token for some functionality)
testinfo "test request ID filtering without token"
testing-farm list --id 12345678-1234-1234-1234-123456789abc | tee output
grep -E "(No API token|Request.*not found|No requests found)" output

# test partial UUID
testinfo "test partial UUID"
testing-farm list --id 12345678 | tee output
grep -E "Could not find a valid Testing Farm request id in '12345678'." output

# test multiple request IDs
testinfo "test multiple request IDs"
testing-farm list --id 12345678-1234-1234-1234-123456789abc --id 87654321-4321-4321-4321-cba987654321 | tee output
grep -E "(No API token|Request.*not found|No requests found)" output

# test showing secrets with ID (should work but require token)
testinfo "test show secrets with ID"
testing-farm list --id 12345678-1234-1234-1234-123456789abc --show-secrets 2>&1 | tee output
grep -E "(No API token|--show-secrets.*--id)" output || true

# test reservations option
testinfo "test reserve flag"
testing-farm list --all --age 1h --reservations

# test conflicting options
testinfo "test conflicting options with --id"
set +e
testing-farm list --id 12345678-1234-1234-1234-123456789abc --mine 2>&1 | tee output
grep -E "conflicts with.*--mine" output

testing-farm list --id 12345678-1234-1234-1234-123456789abc --all 2>&1 | tee output
grep -E "conflicts with.*--all" output

testing-farm list --id 12345678-1234-1234-1234-123456789abc --age 1h 2>&1 | tee output
grep -E "conflicts with.*--age" output

testing-farm list --id 12345678-1234-1234-1234-123456789abc --min-age 1h 2>&1 | tee output
grep -E "conflicts with.*--min-age" output
set -e

# test reservations conflict with ID
testinfo "test reservations conflicts with --id"
set +e
testing-farm list --id 12345678-1234-1234-1234-123456789abc --reservations 2>&1 | tee output
grep -E "--reservations.*cannot be used with.*--id" output
set -e

# test reservations conflicts with explicit format
testinfo "test reservations conflicts with --format"
set +e
testing-farm list --all --age 1h -r --format json 2>&1 | tee output
grep -E "--reservations.*conflicts with.*--format" output
set -e

# test invalid arguments
testinfo "test invalid age format"
set +e
testing-farm list --all --age invalid 2>&1 | tee output
grep -E "(Age must end with|Invalid age)" output

testinfo "test invalid state"
testing-farm list --all --age 1h --state invalid 2>&1 | tee output
grep -E "Invalid value.*state" output

testinfo "test invalid format"
testing-farm list --all --age 1h --format invalid 2>&1 | tee output
grep -E "Invalid value.*format" output

testinfo "test invalid ranch"
testing-farm list --all --age 1h --ranch invalid 2>&1 | tee output
grep -E "Invalid value.*ranch" output
set -e

# test exit codes
testinfo "test exit code on success"
testing-farm list --all --age 1h --format text

# remove temporary directory
rm -rf $TMPDIR
