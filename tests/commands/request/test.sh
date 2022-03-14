#!/bin/bash -ex

# we do not want pipefail for these tests
set +o pipefail

# we need to work in a clean directory, the CWD is a git repo and can mess around with us!
TMPDIR=$(mktemp -d)
pushd $TMPDIR

# no token
testing-farm request | tee output
egrep "^⛔ No API token found, export \`TESTING_FARM_API_TOKEN\` environment variable$" output

# test with invalid token
export TESTING_FARM_API_TOKEN=invalid

# auto-detection error
testing-farm request | tee output
egrep "^⛔ could not auto-detect git url$" output

# clone our cli repo
git clone https://gitlab.com/testing-farm/cli
pushd cli

# test auto-detection
testing-farm request | tee output
egrep "📦 repository https://gitlab.com/testing-farm/cli ref main" output
egrep "💻 container image in plan on x86_64" output
egrep "⛔ API token is invalid. See https://docs.testing-farm.io/general/0.1/onboarding.html for more information." output

# test exit code on invalid token
set +e
testing-farm request
test $? == 255
set -e

# checkout a ref rather, test autodetection working
COMMIT_SHA=$(git rev-parse HEAD)
git checkout $COMMIT_SHA
testing-farm request | tee output
egrep "📦 repository https://gitlab.com/testing-farm/cli ref $COMMIT_SHA" output

# test compose, pool, arch
testing-farm request --compose SuperOS --arch aarch64 --pool super-pool | tee output
egrep "📦 repository https://gitlab.com/testing-farm/cli ref $COMMIT_SHA" output
egrep "💻 SuperOS on aarch64 via pool super-pool" output

# invalid variables
testing-farm request --environment invalid | tee output
egrep "⛔ Options for environment variables are invalid, must be defined as \`key=value\`" output

# invalid secrets
testing-farm request --secret invalid | tee output
egrep "⛔ Options for environment secrets are invalid, must be defined as \`key=value\`" output

# invalid tmt context
testing-farm request --context invalid | tee output
egrep "⛔ Options for tmt context are invalid, must be defined as \`key=value\`" output

# remove temporary directory
rm -rf $TMPDIR
