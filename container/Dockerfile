# build image
FROM python:3.9.10-alpine

# bash - required to run tmt tests against the container
# git  - required for auto-detection
RUN apk add --no-cache bash git

# This file is used to detect if CLI is running inside this container image
RUN touch /.testing-farm-container

COPY dist/tft_cli*.whl .

RUN pip install tft_cli*.whl && rm -f tft_cli*.whl

WORKDIR /code

# Cannot set entrypoint as tmt does not work without entrypoint set to bash
# https://github.com/psss/tmt/issues/1046
# ENTRYPOINT ["testing-farm"]
# CMD ["--help"]
