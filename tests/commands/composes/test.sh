#!/bin/bash -ex

testinfo() { printf "\n== TEST: $@ ==================\n"; }

# WORKAROUND: tmt bug causing TMT_TREE to be resynced and lost

# Use tmt tree to run the API
cd "$TMT_TREE"

# clone nucleus repository
git clone https://gitlab.com/testing-farm/nucleus

# start dev API
pushd nucleus/api
poetry env use python3.9
poetry install

trap 'status=$?; cd $TMT_TREE/nucleus/api && make dev/stop; exit $status' EXIT SIGINT
if ! make dev &> "$TMT_PLAN_DATA/api.txt"; then
    echo "[E] Failed to start API."
    cat "$TMT_PLAN_DATA/api.txt"
    exit 1
fi

# wait until API is available
for _ in {1..10}; do
  curl http://localhost:8001 && break
  sleep 1
done

# we need to work in a clean directory, the CWD is a git repo and can mess around with us!
TMPDIR=$(mktemp -d)
pushd $TMPDIR

# no token - requires token for default behavior
testinfo "no token specified"
testing-farm composes | tee output
grep -E "^⛔ No API token found" output

# test with invalid token - should fail for authenticated requests
testinfo "invalid token"
export TESTING_FARM_API_TOKEN=invalid
testing-farm composes | tee output
grep -E "^⛔ API token is invalid" output

# invalid ranch
testinfo "invalid ranch"
testing-farm composes --ranch whatever |& tee output
grep -E "Invalid value for '--ranch': 'whatever' is not one of 'public', 'redhat'." output

# use the developer API
export TESTING_FARM_API_URL=http://localhost:8001

# check if API running on localhost
testinfo "Check if Testing Farm dev API server running on localhost"
curl http://localhost:8001/v0.1/about

# public ranch
testinfo "public ranch listing"
testing-farm composes --ranch public | tee output
grep -E "^Fedora-41" output

# redhat ranch
testinfo "redhat ranch listing"
testing-farm composes --ranch redhat | tee output
grep -E "^RHEL-8.10.0-rc" output

# show regex
testinfo "redhat ranch listing with --show-regex"
testing-farm composes --ranch redhat --show-regex | tee output
grep -E "^RHEL-8.10.0-rc compose" output
grep -E "^RHEL-8.6.0-Nightly regex" output
grep -E "^RHEL-9.0.0-Nightly regex" output
grep -E "^\^\(regex-compose\.\*\)\(\?:aarch64\|x86_64\)\\\$ regex" output

# next commands need a valid token
export TESTING_FARM_API_TOKEN=developer

# listing with default ranch based on token
testinfo "listing with default ranch based on token"
testing-farm composes | tee output
grep -E "^Fedora-41" output

# show regex
testinfo "listing with default ranch based on token with --show-regex"
testing-farm composes --show-regex | tee output
grep -E "^Fedora-36 regex" output
grep -E "^Fedora-41 compose" output
grep -E "^Fedora-Rawhide regex" output
grep -E "^\^\(regex-compose\.\*\)\(\?:aarch64\|x86_64\)\\\$ regex" output

# validate
testinfo "validate composes"
testing-farm composes --validate Fedora-41 --validate Fedora-eln | tee output
grep -E "^✅ Compose 'Fedora-41' is valid" output
grep -E "^❌ Compose 'Fedora-eln' is invalid" output

# search
testinfo "search composes"
testing-farm composes --search Fedora-.* | tee output
grep -E "^Fedora-41" output
testing-farm composes --search RHEL | tee output
grep -E "^⛔ No composes found for 'RHEL'." output

# format: table
testinfo "table format"
testing-farm composes --format table | tee output
grep -E "┏━━━━━━━━━━━┓" output
grep -E "┃ name      ┃" output
grep -E "┡━━━━━━━━━━━┩" output
grep -E "│ Fedora-41 │" output
grep -E "└───────────┘" output

# format: yaml
testinfo "yaml format"
testing-farm composes --format yaml | tee output
grep -E -- "- name: Fedora-41" output
grep -E "  type: compose" output

# format: json
testinfo "json format"
testing-farm composes --format json | jq -c | tee output
grep -E '^\[{"name":"Fedora-41","type":"compose"}\]$' output
