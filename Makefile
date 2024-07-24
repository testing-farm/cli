all: build test clean
.PHONY: all

# default image tag set to current user name
IMAGE_TAG ?= ${USER}

# in toolbox environment run tmt against localhost
TMT_CONTEXT = -c distro=alpine
ifeq ($(wildcard $(/run/.toolboxenv)),)
TMT_RUN_ARGS = -a provision -h local
TMT_CONTEXT = -c distro=fedora
endif

build:
	poetry build
	buildah bud --layers -t quay.io/testing-farm/cli:$(IMAGE_TAG) -f container/Dockerfile .

push:
	buildah push quay.io/testing-farm/cli:$(IMAGE_TAG)

enter:
	podman run --rm -itv $$(pwd):/code:Z quay.io/testing-farm/cli:$(IMAGE_TAG) bash

pre-commit:
	pre-commit run --all-files

tmt:
	tmt clean runs -i tft-cli
	-tmt $(TMT_CONTEXT) run -e IMAGE_TAG=$(IMAGE_TAG) -i tft-cli $(TMT_RUN_ARGS)
	tmt run -i tft-cli report -vvv

tox:
	tox

testing-farm: build push
	testing-farm request -e IMAGE_TAG=$(IMAGE_TAG)

test: build pre-commit tmt tox

clean:
	buildah rmi quay.io/testing-farm/cli:$(IMAGE_TAG)
