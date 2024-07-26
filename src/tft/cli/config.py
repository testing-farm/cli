# Copyright Contributors to the Testing Farm project.
# SPDX-License-Identifier: Apache-2.0

from dynaconf import LazySettings

settings = LazySettings(
    # all environment variables have `TESTING_FARM_` prefix
    ENVVAR_PREFIX_FOR_DYNACONF="TESTING_FARM",
    # defaults
    API_URL="https://api.dev.testing-farm.io/v0.1",
    INTERNAL_API_URL="https://internal.api.dev.testing-farm.io/v0.1",
    API_TOKEN=None,
    ISSUE_TRACKER="https://gitlab.com/testing-farm/general/-/issues/new",
    STATUS_PAGE="https://status.testing-farm.io",
    ONBOARDING_DOCS="https://docs.testing-farm.io/general/0.1/onboarding.html",
    CONTAINER_SIGN="/.testing-farm-container",
    WATCH_TICK=3,
    DEFAULT_API_TIMEOUT=10,
    DEFAULT_API_RETRIES=7,
    # should lead to delays of 0.5, 1, 2, 4, 8, 16, 32 seconds
    DEFAULT_RETRY_BACKOFF_FACTOR=1,
    # system CA certificates path, default for RHEL variants
    REQUESTS_CA_BUNDLE="/etc/ssl/certs/ca-bundle.crt",
    # Testing Farm sanity test,
    TESTING_FARM_TESTS_GIT_URL="https://gitlab.com/testing-farm/tests",
    TESTING_FARM_SANITY_PLAN="/testing-farm/sanity",
)
