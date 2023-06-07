#!/bin/bash -ex

testinfo() { printf "\033[0;32m\n== TEST: %s ==================\n\033[0m" "$@"; }

# we do not want pipefail for these tests
set +o pipefail

# we need to work in a clean directory, the CWD is a git repo and can mess around with us!
TMPDIR=$(mktemp -d)
pushd "$TMPDIR"

# no command specified
testinfo "no request id"
testing-farm run |& tee output
grep -E "Missing argument 'COMMAND...'." output

# valid command, no token
testinfo "valid command, no token"
testing-farm run echo hello | tee output
grep -E "^⛔ No API token found, export \`TESTING_FARM_API_TOKEN\` environment variable.$" output

export TESTING_FARM_API_TOKEN=token

# valid command, invalid token
testinfo "valid command, invalid token"
testing-farm run echo hello | tee output
grep -E "^⛔ API token is invalid. See https://docs.testing-farm.io/general/0.1/onboarding.html for more information.$" output

# valid command, no arguments
testinfo "valid command, no arguments"
testing-farm run --dry-run -- echo hello | tee output
grep -E "🔍 showing POST json" output
tail -n+2 output | jq -r .test.fmf.url | grep -E "^https://gitlab.com/testing-farm/tests$"
tail -n+2 output | jq -r .test.fmf.ref | grep -E "^main$"
tail -n+2 output | jq -r .test.fmf.name | grep -E "^/testing-farm/sanity$"
tail -n+2 output | jq -r .environments[].os | grep null
tail -n+2 output | jq -r .environments[].variables.SCRIPT | grep -E "^echo hello$"

# compose
testinfo "compose"
testing-farm run --dry-run --compose Fedora-Rawhide -- sestatus | tee output
tail -n+2 output | jq -r .environments[].os.compose | grep -E "^Fedora-Rawhide$"
tail -n+2 output | jq -r .environments[].variables.SCRIPT | grep -E "^sestatus$"

# hardware
testinfo "hardware"
testing-farm run --dry-run --compose Fedora-Rawhide --hardware memory=">=4GB" --hardware virtualization.is-virtualized=false -- sestatus | tee output
tail -n+2 output | jq -r .environments[].hardware.memory | grep -E '^>=4GB$'
tail -n+2 output | jq -r '.environments[].hardware.virtualization."is-virtualized"' | grep -E '^false$'
