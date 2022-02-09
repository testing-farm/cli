# build image
FROM python:3.9 as build-stage
RUN pip install "poetry==1.1.12"

RUN python -m venv /venv
ENV VIRTUAL_ENV=/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

WORKDIR /app
COPY pyproject.toml poetry.lock /app
RUN poetry install --no-dev --no-root --no-interaction

COPY src /app/src
RUN poetry install --no-dev --no-interaction

# production base image containing only the bare minimum
FROM python:3.9-slim as final

# Activate the virtual environment
ENV VIRTUAL_ENV=/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
WORKDIR /app

# Copy only application dependencies contained in the virtual environment
COPY --from=build-stage /venv /venv
COPY [".", "/app"]

# Workaround for Debian's posix default shell
# https://github.com/psss/tmt/issues/1047
RUN rm /bin/sh; cp /bin/bash /bin/sh

# Cannot set entrypoint as tmt does not work without entrypoint set to bash
# https://github.com/psss/tmt/issues/1046
# ENTRYPOINT ["testing-farm"]
# CMD ["--help"]
