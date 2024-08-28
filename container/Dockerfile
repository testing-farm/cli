# build image
FROM python:3.9.10-alpine

# Set home
ENV HOME=/root

# bash            - required to run tmt tests against the container
# git             - required for auto-detection
# openssh-client  - required for reserve command
RUN apk add --no-cache bash git make openssh-client

# This file is used to detect if CLI is running inside this container image
RUN touch /.testing-farm-container

# Do not verify host identity
RUN    mkdir -p $HOME/.ssh \
    && chmod 700 $HOME/.ssh \
    && printf "Host *\n  StrictHostKeyChecking no\n  UserKnownHostsFile /dev/null" > $HOME/.ssh/config \
    && chmod 600 $HOME/.ssh/config \
    && touch /.testing-farm-cli

COPY dist/tft_cli*.whl .

RUN pip install tft_cli*.whl && rm -f tft_cli*.whl

WORKDIR /code

# Cannot set entrypoint as tmt does not work without entrypoint set to bash
# https://github.com/psss/tmt/issues/1046
# ENTRYPOINT ["testing-farm"]
# CMD ["--help"]
