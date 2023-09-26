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

# valid request id, no token
testinfo "valid request request id, no token"
testing-farm restart 40cafaa3-0efa-4abf-a20b-a6ad87e84527 | tee output
egrep "⛔ API token is invalid. See https://docs.testing-farm.io/general/0.1/onboarding.html for more information." output

# git-url, git-ref and git-merge-sha options, just sanity test that they are available
testinfo "git-url, git-ref and git-merge-sha options accepted"
testing-farm restart --git-url https://example.com --git-ref some-ref --git-merge-sha some-sha https://api.dev.testing-farm.io/v0.1/requests/40cafaa3-0efa-4abf-a20b-a6ad87e84527 | tee output
egrep "⛔ API token is invalid. See https://docs.testing-farm.io/general/0.1/onboarding.html for more information." output

# plan and plan filter options, just sanity test that they are available
testinfo "plan and plan filter options accepted"
testing-farm restart --plan myplan --plan-filter some-filter https://api.dev.testing-farm.io/v0.1/requests/40cafaa3-0efa-4abf-a20b-a6ad87e84527 | tee output
egrep "⛔ API token is invalid. See https://docs.testing-farm.io/general/0.1/onboarding.html for more information." output

# test filter option, just sanity test that it is available
testinfo "test filter option accepted"
testing-farm restart --test-filter some-filter https://api.dev.testing-farm.io/v0.1/requests/40cafaa3-0efa-4abf-a20b-a6ad87e84527 | tee output
egrep "⛔ API token is invalid. See https://docs.testing-farm.io/general/0.1/onboarding.html for more information." output

# worker-image option, just test it is accepted
testinfo "worker-image option accepted"
testing-farm restart --worker-image quay.io/testing-farm/worker:latest https://api.dev.testing-farm.io/v0.1/requests/40cafaa3-0efa-4abf-a20b-a6ad87e84527 | tee output
egrep "⛔ API token is invalid. See https://docs.testing-farm.io/general/0.1/onboarding.html for more information." output

# worker-image option, just test it is accepted
testinfo "hardware option accepted"
testing-farm restart --hardware boot.mode=uefi https://api.dev.testing-farm.io/v0.1/requests/40cafaa3-0efa-4abf-a20b-a6ad87e84527 | tee output
egrep "⛔ API token is invalid. See https://docs.testing-farm.io/general/0.1/onboarding.html for more information." output
