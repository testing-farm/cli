#!/bin/bash -ex

testinfo() { printf "\n== TEST: $@ ==================\n"; }

# we do not want pipefail for these tests
set +o pipefail

# we need to work in a clean directory, the CWD is a git repo and can mess around with us!
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
egrep "⛔ Options for environment variables are invalid, must be defined as \`key=value\`" output

# invalid secrets
testinfo "test invalid secrets"
testing-farm request --environment invalid | tee output
testing-farm request --secret invalid | tee output
egrep "⛔ Options for environment secrets are invalid, must be defined as \`key=value\`" output

# invalid tmt context
testinfo "test invalid tmt context"
testing-farm request --context invalid | tee output
egrep "⛔ Options for tmt context are invalid, must be defined as \`key=value\`" output

# invalid kickstart
testinfo "test invalid kickstart specification"
testing-farm request --kickstart invalid | tee output
egrep "⛔ Options for environment kickstart are invalid, must be defined as \`key=value\`" output

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

# remove temporary directory
rm -rf $TMPDIR
