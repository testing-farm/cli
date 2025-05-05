#!/bin/sh -eux
testing-farm version --help

# detect the version from poetry, fallback to rpm, and as last resort from the Python package
version=$(poetry version -s || rpm -q --qf "%{version}" testing-farm || python -c "import importlib.metadata; print(importlib.metadata.version('tft-cli'))")

testing-farm version

testing-farm version | grep "^${version}$"
