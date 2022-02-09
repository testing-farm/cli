#!/bin/sh -eux
testing-farm version --help
testing-farm version | egrep "^[0-9]+\.[0-9]+\.[0-9]+$"
