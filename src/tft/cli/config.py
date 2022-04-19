# Copyright Contributors to the Testing Farm project.
# SPDX-License-Identifier: Apache-2.0

from dynaconf import LazySettings

settings = LazySettings(
    # all environment variables have `TESTING_FARM_` prefix
    ENVVAR_PREFIX_FOR_DYNACONF="TESTING_FARM",
    # defaults
    API_URL="https://api.dev.testing-farm.io/v0.1",
    API_TOKEN=None,
    ISSUE_TRACKER="https://gitlab.com/testing-farm/general/-/issues/new",
    ONBOARDING_DOCS="https://docs.testing-farm.io/general/0.1/onboarding.html",
    WATCH_TICK=3,
)
