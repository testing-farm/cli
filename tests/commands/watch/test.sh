#!/bin/bash -ex

testinfo() { printf "\n== TEST: $@ ==================\n"; }

# we do not want pipefail for these tests
set +o pipefail

# we need to work in a clean directory, the CWD is a git repo and can mess around with us!
TMPDIR=$(mktemp -d)
pushd $TMPDIR

# required id parameter
testinfo "required --id parameter"
testing-farm watch |& tee output
egrep "Missing option '--id'." output

# invalid arguments
testing-farm watch --id parameter invalid |& tee output
egrep "^⛔ Unexpected argument 'invalid'. Please make sure you are passing the parameters correctly.$" output

# invalid id parameter
testinfo "invalid --id parameter"
testing-farm watch --id invalid | tee output
egrep "^⛔ invalid request id$" output
testing-farm watch --id c1c1584b-7a35-4e64-a010-1430a0e36cbc | tee output
egrep "^🔎 api https://api.dev.testing-farm.io/v0.1/requests/c1c1584b-7a35-4e64-a010-1430a0e36cbc$" output
egrep "^⛔ request with given ID not found$" output

# passed test
testinfo "passing test"
testing-farm watch --id 49d77b77-acff-44c6-bcb3-e3bc21b76d1b | tee output
egrep "^🔎 api https://api.dev.testing-farm.io/v0.1/requests/49d77b77-acff-44c6-bcb3-e3bc21b76d1b$" output
egrep "^🚢 artifacts https://artifacts.dev.testing-farm.io/49d77b77-acff-44c6-bcb3-e3bc21b76d1b$" output
egrep "^✅ tests passed$" output

# failed test
testinfo "failed test"
testing-farm watch --id 8a512116-27d1-483a-8d12-c6bb0063f091 | tee output
egrep "^❌ tests failed$" output

# error
testinfo "error test"
testing-farm watch --id 50b94e05-1396-473f-819a-9bdbd17e8e54 | tee output
egrep "^🔎 api https://api.dev.testing-farm.io/v0.1/requests/50b94e05-1396-473f-819a-9bdbd17e8e54$" output
egrep "^📛 pipeline error$" output
egrep "^Test environment installation failed: reason unknown, please escalate$" output

# api url
testinfo "custom API url"
TESTING_FARM_API_URL=https://api.stage.testing-farm.io timeout 1 testing-farm watch --id 50b94e05-1396-473f-819a-9bdbd17e8e54 2>/dev/null | tee output
egrep "^🔎 api https://api.stage.testing-farm.io/v0.1/requests/50b94e05-1396-473f-819a-9bdbd17e8e54$" output

# multihost test
testinfo "multihost test"
testing-farm watch --id 51335c9e-355e-46ff-a915-76194898c29d | tee output
egrep "^🔎 api https://api.dev.testing-farm.io/v0.1/requests/51335c9e-355e-46ff-a915-76194898c29d$" output
egrep "^🚢 artifacts https://artifacts.dev.testing-farm.io/51335c9e-355e-46ff-a915-76194898c29d$" output
egrep "^✅ tests passed$" output
egrep "^│ /testing-farm/multihost/basic │ pass   │$" output

# remove temporary directory
rm -rf $TMPDIR
