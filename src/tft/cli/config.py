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
    ONBOARDING_DOCS="https://docs.testing-farm.io/general/0.1/onboarding.html",
    WATCH_TICK=3,
    DEFAULT_API_TIMEOUT=10,
    DEFAULT_API_RETRIES=7,
    # should lead to delays of 0.5, 1, 2, 4, 8, 16, 32 seconds
    DEFAULT_RETRY_BACKOFF_FACTOR=1,
)
