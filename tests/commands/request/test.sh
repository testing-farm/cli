#!/bin/bash -ex

testinfo() { printf "\n== TEST: $@ ==================\n"; }

# we do not want pipefail for these tests
set +o pipefail

# we need to work in a clean directory, the CWD is a git repo and can mess around with us!
TEST_DATA=$PWD/data
TMPDIR=$(mktemp -d)
pushd $TMPDIR

# no token
testinfo "no token specified"
testing-farm request | tee output
egrep "^⛔ No API token found, export \`TESTING_FARM_API_TOKEN\` environment variable$" output

# test with invalid token
export TESTING_FARM_API_TOKEN=invalid

# auto-detection error
testinfo "auto-detection error"
testing-farm request | tee output
egrep "^⛔ could not auto-detect git url$" output

# clone our cli repo
git clone https://gitlab.com/testing-farm/cli
pushd cli

# test auto-detection
testinfo "auto-detection test"
testing-farm request | tee output
egrep "📦 repository https://gitlab.com/testing-farm/cli ref main" output
egrep "💻 container image in plan on x86_64" output
egrep "⛔ API token is invalid. See https://docs.testing-farm.io/general/0.1/onboarding.html for more information." output

# test x86_64 only without compose
testinfo "x86_64 only without compose"
testing-farm request --arch aarch64,s390x | tee output
egrep "⛔ Without compose the tests run against a container image specified in the plan. Only 'x86_64' architecture supported in this case." output

# test GitHub https mapping
testinfo "test GitHub mapping"
git remote set-url origin git@github.com:testing-farm/cli
testing-farm request | tee output
egrep "📦 repository https://github.com/testing-farm/cli ref main" output

# test GitLab https mapping
testinfo "test GitLab mapping"
git remote set-url origin git@gitlab.com:testing-farm/cli
testing-farm request | tee output
egrep "📦 repository https://gitlab.com/testing-farm/cli ref main" output

# test GitLab https mapping #2
testinfo "test GitLab mapping"
git remote set-url origin git+ssh://git@gitlab.com/spoore/centos_rpms_jq.git
testing-farm request | tee output
egrep "📦 repository https://gitlab.com/spoore/centos_rpms_jq.git ref main" output

# test Pagure https mapping
testinfo "test Pagure mapping"
git remote set-url origin ssh://git@pagure.io/testing-farm/cli
testing-farm request | tee output
egrep "📦 repository https://pagure.io/testing-farm/cli ref main" output

# reset origin
git remote set-url origin https://gitlab.com/testing-farm/cli

# test exit code on invalid token
testinfo "test exit code on invalid token"
set +e
testing-farm request
test $? == 255
set -e

# checkout a ref rather, test autodetection working
testinfo "test commit SHA detection"
COMMIT_SHA=$(git rev-parse HEAD)
git checkout $COMMIT_SHA
testing-farm request | tee output
egrep "📦 repository https://gitlab.com/testing-farm/cli ref $COMMIT_SHA" output

# test compose, pool, arch
testinfo "test compose, pool, arch can be specified"
testing-farm request --compose SuperOS --arch aarch64 --pool super-pool | tee output
egrep "📦 repository https://gitlab.com/testing-farm/cli ref $COMMIT_SHA" output
egrep "💻 SuperOS on aarch64 via pool super-pool" output

# invalid variables
testinfo "test invalid variables"
testing-farm request --environment invalid | tee output
egrep "⛔ Option \`invalid\` is invalid, must be defined as \`key=value|@file\`." output

# invalid secrets
testinfo "test invalid secrets"
testing-farm request --environment invalid | tee output
testing-farm request --secret invalid | tee output
egrep "⛔ Option \`invalid\` is invalid, must be defined as \`key=value|@file\`." output

# environment from file - non existent file
testinfo "test environment from file - non existent file"
testing-farm request --environment @xxx --dry-run | tee output
egrep "⛔ Invalid environment file in option \`@xxx\` specified." output

# environment from file - empty file
testinfo "test environment from file - empty file"
testing-farm request --environment @$TEST_DATA/env1.yaml --dry-run | tee output
tail -n+4 output | jq -r .environments[0].variables | egrep '\{\}'

# environment from file - file that is not a dict
testinfo "test environment from file - file that is not a dict"
testing-farm request --environment @$TEST_DATA/env2.yaml --dry-run | tee output
egrep "⛔ Environment file $TEST_DATA/env2.yaml is not a dict." output

# environment from file - file that contains nested dicts
testinfo "test environment from file - file that contains nested dicts"
testing-farm request --environment @$TEST_DATA/env3.yaml --dry-run | tee output
egrep "⛔ Values of environment file $TEST_DATA/env3.yaml are not primitive types." output

# environment from file - file with a single variable
testinfo "test environment from file - file with a single variable"
testing-farm request --environment @$TEST_DATA/env4.yaml --dry-run | tee output
tail -n+4 output | jq -r .environments[0].variables | egrep '"foo": null'

# environment from file - file with two variables
testinfo "test environment from file - file with two variables"
testing-farm request --environment @$TEST_DATA/env5.yaml --dry-run | tee output
tail -n+4 output | jq -r .environments[0].variables | egrep '"foo": "bar"'
tail -n+4 output | jq -r .environments[0].variables | egrep '"bar": 123'

# invalid tmt context
testinfo "test invalid tmt context"
testing-farm request --context invalid | tee output
egrep "⛔ Option \`invalid\` is invalid, must be defined as \`key=value|@file\`." output

# invalid kickstart
testinfo "test invalid kickstart specification"
testing-farm request --kickstart invalid | tee output
egrep "⛔ Option \`invalid\` is invalid, must be defined as \`key=value|@file\`." output

# dry run
testinfo "test dry run"
testing-farm request --dry-run --compose Fedora | tee output
egrep "🔍 Dry run, showing POST json only" output
tail -n+4 output | jq -r .environments[].os.compose | grep Fedora

# hardware
testinfo "test hardware"
testing-farm request --dry-run --compose Fedora --hardware memory=">=4GB" --hardware virtualization.is-virtualized=false | tee output
tail -n+4 output | jq -r .environments[].hardware.memory | egrep '^>=4GB$'
tail -n+4 output | jq -r '.environments[].hardware.virtualization."is-virtualized"' | egrep '^false$'

# test multiple arches
testinfo "test multiple arches"
testing-farm request --dry-run --compose Fedora --arch x86_64,aarch64,ppc64le | tee output
tail -n+6 output | jq -r .environments[0].arch | egrep '^x86_64$'
tail -n+6 output | jq -r .environments[1].arch | egrep '^aarch64$'
tail -n+6 output | jq -r .environments[2].arch | egrep '^ppc64le$'
testing-farm request --dry-run --compose Fedora --arch x86_64 --arch aarch64 --arch ppc64le | tee output
tail -n+6 output | jq -r .environments[0].arch | egrep '^x86_64$'
tail -n+6 output | jq -r .environments[1].arch | egrep '^aarch64$'
tail -n+6 output | jq -r .environments[2].arch | egrep '^ppc64le$'

# test kickstart
testing-farm request --dry-run --compose Fedora --kickstart metadata=no_autopart --kickstart post-install="%post\n ls\n %end"  | tee output
tail -n+4 output | jq -r .environments[].kickstart.metadata | egrep '^no_autopart$'
tail -n+4 output | jq -r '.environments[].kickstart."post-install"' | egrep '^%post\\n ls\\n %end$'

# test tags
testinfo "test tags"
testing-farm request --dry-run --compose Fedora --tag FirstTag=FirstValue --tag SecondTag=SecondValue  | tee output
tail -n+4 output | jq -r .environments[].settings.provisioning.tags.FirstTag | egrep '^FirstValue$'
tail -n+4 output | jq -r .environments[].settings.provisioning.tags.SecondTag | egrep '^SecondValue$'

# test watchdogs
testing-farm request --dry-run --compose Fedora --watchdog-period-delay 10 --watchdog-dispatch-delay 20 | tee output
tail -n+4 output | jq -r '.environments[].settings.provisioning."watchdog-dispatch-delay"' | egrep '^20$'
tail -n+4 output | jq -r '.environments[].settings.provisioning."watchdog-period-delay"' | egrep '^10$'

# plan-filter
testinfo "test plan-filter"
testing-farm request --plan-filter "tag: plan-filter" --compose Fedora --dry-run | tee output
tail -n+4 output | jq -r .test.fmf.plan_filter | egrep '^tag: plan-filter$'

# test-name
testinfo "test test-name"
testing-farm request --test "foo.*" --compose Fedora --dry-run | tee output
tail -n+4 output | jq -r .test.fmf.test_name | egrep '^foo\.\*$'

# test-filter
testinfo "test test-filter"
testing-farm request --test-filter "tag: test-filter" --compose Fedora --dry-run | tee output
tail -n+4 output | jq -r .test.fmf.test_filter | egrep '^tag: test-filter$'

# merge-sha
testinfo "test merge-sha"
testing-farm request --git-merge-sha to-be-merged --compose Fedora --dry-run | tee output
tail -n+4 output | jq -r .test.fmf.merge_sha | egrep 'to-be-merged'
testing-farm request --test-type sti --git-url foo --git-merge-sha to-be-merged --compose Fedora --dry-run | tee output
tail -n+4 output | jq -r .test.sti.merge_sha | egrep 'to-be-merged'

# tmt environment variables
testinfo "test tmt environment variables"
testing-farm request --dry-run --compose Fedora --tmt-environment FirstKey=FirstValue -T SecondKey=SecondValue | tee output
tail -n+4 output | jq -r .environments[].tmt.environment.FirstKey | egrep '^FirstValue$'
tail -n+4 output | jq -r .environments[].tmt.environment.SecondKey | egrep '^SecondValue$'

# post install script
testinfo "test post install script"
testing-farm request --dry-run --compose Fedora --post-install-script="some-script" | tee output
tail -n+4 output | jq -r .environments[].settings.provisioning.post_install_script | egrep '^some-script$'

# pipeline type
testinfo "test pipeline type"
testing-farm request --pipeline-type tmt-multihost --compose Fedora --dry-run | tee output
tail -n+4 output | jq -r .settings.pipeline.type | egrep 'tmt-multihost'

testing-farm request --pipeline-type invalid --compose Fedora --dry-run 2>&1 | tee output
egrep "Invalid value for '--pipeline-type': 'invalid' is not 'tmt-multihost'." output

# parallel-limit
testinfo "test parallel-limit"
testing-farm request --parallel-limit 123 --compose Fedora --dry-run | tee output
tail -n+4 output | jq -r '.settings.pipeline."parallel-limit"' | egrep '123'

# user webpage
testinfo "test user webpage"
testing-farm request --dry-run --compose Fedora --user-webpage "https://example.com" --user-webpage-icon "https://example.com/icon.png" --user-webpage-name "Example CI" | tee output
tail -n+4 output | jq -r .user.webpage.url | egrep '^https://example\.com$'
tail -n+4 output | jq -r .user.webpage.icon | egrep '^https://example\.com/icon\.png$'
tail -n+4 output | jq -r .user.webpage.name | egrep '^Example CI$'

# test arch passed into tmt context
testinfo "test arch passed into context"
testing-farm request --dry-run --compose RHEL-8.6.0-Nightly --arch x86_64,s390x -c distro=rhel-8.6 | tee output
tail -n+5 output | jq -r .environments[0].tmt.context.arch | egrep 'x86_64'
tail -n+5 output | jq -r .environments[1].tmt.context.arch | egrep 's390x'

testinfo "test arch passed into contexti no user context set"
testing-farm request --dry-run --compose RHEL-8.6.0-Nightly --arch x86_64,s390x | tee output
tail -n+5 output | jq -r .environments[0].tmt.context.arch | egrep 'x86_64'
tail -n+5 output | jq -r .environments[1].tmt.context.arch | egrep 's390x'

testinfo "test user set arch is respected in tmt context"
testing-farm request --dry-run --compose RHEL-8.6.0-Nightly --arch x86_64,s390x -c arch=mycustomarch | tee output
tail -n+5 output | jq -r .environments[0].tmt.context.arch | egrep 'mycustomarch'
tail -n+5 output | jq -r .environments[1].tmt.context.arch | egrep 'mycustomarch'

# test artifacts
testinfo "test artifacts"
testing-farm request --dry-run --fedora-koji-build 123 --fedora-koji-build install=false,id=1234 --fedora-copr-build some-project:fedora-38 --fedora-copr-build id=some-project:fedora-38 --redhat-brew-build 456 --redhat-brew-build id=456,install=1 --repository baseurl --repository id=baseurl,install=0 --repository-file https://example.com.repo --repository-file id=https://example.com.repo | tee output
tail -n+4 output | tr -d '\n' | jq -r .environments[].artifacts | tr -d ' \n' | egrep '^\[\{"type":"redhat-brew-build","id":"456"\},\{"type":"redhat-brew-build","id":"456","install":true\},\{"type":"fedora-koji-build","id":"123"\},\{"type":"fedora-koji-build","install":false,"id":"1234"\},\{"type":"fedora-copr-build","id":"some-project:fedora-38"\},\{"type":"fedora-copr-build","id":"some-project:fedora-38"\},\{"type":"repository","id":"baseurl"\},\{"type":"repository","id":"baseurl","install":false\},\{"type":"repository-file","id":"https://example.com.repo"\},\{"type":"repository-file","id":"https://example.com.repo"\}\]$'

# remove temporary directory
rm -rf $TMPDIR
