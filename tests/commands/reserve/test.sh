#!/bin/bash -ex

testinfo() { printf "\n== TEST: $@ ==================\n"; }

# we do not want pipefail for these tests
set +o pipefail

# we need to work in a clean directory, the CWD is a git repo and can mess around with us!
TMPDIR=$(mktemp -d)
pushd $TMPDIR

# no token
testinfo "no token specified"
testing-farm reserve | tee output
egrep "^⛔ No API token found, export \`TESTING_FARM_API_TOKEN\` environment variable.$" output

# test goes only with invalid token
export TESTING_FARM_API_TOKEN=invalid

# no ssh key
testing-farm reserve --ssh-public-key /this-does-not-exist-really | tee output
egrep "^💻 Fedora-Rawhide on x86_64" output
egrep "^🕗 Reserved for 30 minutes$" output
egrep "⛔ No public SSH keys found under /this-does-not-exist-really, cannot continue." output

# create fake "ssh" key and ssh agent
echo "some-key" > /var/tmp/some-key
ssh_key_option="--ssh-public-key /var/tmp/some-key"

# no ssh-agent
testinfo "no ssh agent"
testing-farm reserve $ssh_key_option | tee output
egrep "^💻 Fedora-Rawhide on x86_64" output
egrep "^🕗 Reserved for 30 minutes$" output
egrep "⛔ No 'ssh-agent' seems to be running, it is required for reservations to work, cannot continue." output

# create a fake ssh agent
export SSH_AUTH_SOCK=/some-socket

# defaults + invalid token
testinfo "defaults + invalid token"
testing-farm reserve $ssh_key_option | tee output
egrep "^💻 Fedora-Rawhide on x86_64" output
egrep "^🕗 Reserved for 30 minutes$" output
egrep "^⏳ Maximum reservation time is 720 minutes$" output
egrep "⛔ API token is invalid. See https://docs.testing-farm.io/general/0.1/onboarding.html for more information." output

# test compose, pool, arch
testinfo "test compose, pool, arch can be specified"
testing-farm reserve $ssh_key_option --compose SuperOS --arch aarch64 --pool super-pool | tee output
egrep "💻 SuperOS on aarch64 via pool super-pool" output

# invalid kickstart
testinfo "test invalid kickstart specification"
testing-farm reserve $ssh_key_option  --kickstart invalid | tee output
egrep "⛔ Options for environment kickstart are invalid, must be defined as \`key=value\`" output

# dry run
testinfo "test dry run"
testing-farm reserve $ssh_key_option --dry-run --compose Fedora | tee output
egrep "🔍 Dry run, showing POST json only" output
tail -n+5 output | tr -d '\n' | jq -r .environments[].os.compose | grep Fedora

# hardware
testinfo "test hardware"
testing-farm reserve $ssh_key_option --dry-run --compose Fedora --hardware memory=">=4GB" --hardware virtualization.is-virtualized=false | tee output
tail -n+5 output | tr -d '\n' | jq -r .environments[].hardware.memory | egrep '^>=4GB$'
tail -n+5 output | tr -d '\n' | jq -r '.environments[].hardware.virtualization."is-virtualized"' | egrep '^false$'

# test kickstart
testinfo "test kickstart"
testing-farm reserve $ssh_key_option --dry-run --compose Fedora --kickstart metadata=no_autopart --kickstart post-install="%post\n ls\n %end"  | tee output
tail -n+5 output | tr -d '\n' | jq -r .environments[].kickstart.metadata | egrep '^no_autopart$'
tail -n+5 output | tr -d '\n' | jq -r '.environments[].kickstart."post-install"' | egrep '^%post\\n ls\\n %end$'

# test artifacts
testinfo "test artifacts"
testing-farm reserve $ssh_key_option --dry-run --fedora-koji-build 123 --fedora-koji-build install=false,id=1234 --fedora-copr-build some-project:fedora-38 --fedora-copr-build id=some-project:fedora-38 --redhat-brew-build 456 --redhat-brew-build id=456,install=1 --repository baseurl --repository id=baseurl,install=0 --repository-file https://example.com.repo --repository-file id=https://example.com.repo | tee output
tail -n+5 output | tr -d '\n' | jq -r .environments[].artifacts | tr -d ' \n' | egrep '^\[\{"type":"redhat-brew-build","id":"456"\},\{"type":"redhat-brew-build","id":"456","install":true\},\{"type":"fedora-koji-build","id":"123"\},\{"type":"fedora-koji-build","install":false,"id":"1234"\},\{"type":"fedora-copr-build","id":"some-project:fedora-38"\},\{"type":"fedora-copr-build","id":"some-project:fedora-38"\},\{"type":"repository","id":"baseurl"\},\{"type":"repository","id":"baseurl","install":false\},\{"type":"repository-file","id":"https://example.com.repo"\},\{"type":"repository-file","id":"https://example.com.repo"\}\]$'

# post install script
testinfo "test post install script"
testing-farm reserve $ssh_key_option --dry-run --compose Fedora --post-install-script="some-script" | tee output
tail -n+5 output | tr -d '\n' | jq -r .environments[].settings.provisioning.post_install_script | egrep '^some-script$'

# test print-only-request-id
testinfo "test post install script"
testing-farm reserve $ssh_key_option --dry-run --compose Fedora --print-only-request-id | tee output
egrep "🔍 Dry run, print-only-request-id is set. Nothing will be shown" output

# test duration > timeout
testinfo "test reservation duration > pipeline timeout"
testing-farm reserve $ssh_key_option --dry-run --compose Fedora --duration 3600 | tee output
egrep "⏳ Maximum reservation time is 3600 minutes" output
tail -n+5 output | tr -d '\n' | jq -r '.environments[].variables.TF_RESERVATION_DURATION' | egrep '^3600$'
tail -n+5 output | tr -d '\n' | jq -r '.settings.pipeline.timeout' | egrep '^3600$'

# remove temporary directory
rm -rf $TMPDIR
