#!/bin/bash -ex

testinfo() { printf "\n== TEST: $@ ==================\n"; }

# we do not want pipefail for these tests
set +o pipefail

# we need to work in a clean directory, the CWD is a git repo and can mess around with us!
TMPDIR=$(mktemp -d)
pushd $TMPDIR

# no request specified
testinfo "no request id"
testing-farm cancel |& tee output
egrep "Missing argument 'REQUEST_ID'." output

# invalid request id
testinfo "invalid request request id"
testing-farm cancel ABC | tee output
egrep "^⛔ Could not find a valid Testing Farm request id in 'ABC'.$" output

# invalid request id, bad uuid
testinfo "invalid request request id"
testing-farm cancel 40cafaa3-0efa-4abf-a20b-a6ad87e8452 | tee output
egrep "^⛔ Could not find a valid Testing Farm request id in '40cafaa3-0efa-4abf-a20b-a6ad87e8452'.$" output

# valid request id, no token
testinfo "valid request request id, no token"
testing-farm cancel 40cafaa3-0efa-4abf-a20b-a6ad87e84527 | tee output
egrep "No API token found in the environment, please export 'TESTING_FARM_API_TOKEN' variable." output

# invalid arguments
testing-farm cancel 40cafaa3-0efa-4abf-a20b-a6ad87e84527 invalid |& tee output
egrep "^⛔ Unexpected argument 'invalid'. Please make sure you are passing the parameters correctly.$" output

# test api url and token
export TESTING_FARM_API_URL="http://localhost:10001"
export TESTING_FARM_API_TOKEN="developer"

# permission denied
testinfo "token invalid"
{ echo -ne "HTTP/1.0 401 Unauthorized"; } | nc -N -l 10001 &
testing-farm cancel 40cafaa3-0efa-4abf-a20b-a6ad87e84527 | tee output
egrep "⛔ API token is invalid. See https://docs.testing-farm.io/general/0.1/onboarding.html for more information." output

# invalid request ID
testinfo "request ID not found"
{ echo -ne "HTTP/1.0 404 Not Found"; } | nc -N -l 10001 &
testing-farm cancel 40cafaa3-0efa-4abf-a20b-a6ad87e84527 | tee output
egrep "Request was not found. Verify the request ID is correct." output

# cancelation requested
testinfo "cancellation accepted"
{ echo -ne "HTTP/1.0 200 OK"; } | nc -N -l 10001 &
testing-farm cancel 40cafaa3-0efa-4abf-a20b-a6ad87e84527 | tee output
egrep "✅ Request cancellation requested. It will be canceled soon." output

# cancelation already in progress
testinfo "cancellation already in progress or already canceled"
{ echo -ne "HTTP/1.0 204 No Content"; } | nc -N -l 10001 &
testing-farm cancel 40cafaa3-0efa-4abf-a20b-a6ad87e84527 | tee output
egrep "⛔ Request was already canceled." output

# cancellation not possible, request already finished
testinfo "cancellation not possible, request finished"
{ echo -ne "HTTP/1.0 409 Conflict"; } | nc -N -l 10001 &
testing-farm cancel 40cafaa3-0efa-4abf-a20b-a6ad87e84527 | tee output
egrep "Requeted cannot be canceled, it is already finished." output
