all: build test clean
.PHONY: all

TAG ?= latest

build:
	buildah bud -t quay.io/testing-farm/cli:$(TAG) -f container/Dockerfile .

push:
	podman push quay.io/testing-farm/cli:$(TAG)

pre-commit:
	pre-commit run --all-files

tmt:
	tmt clean runs -i tft-cli
	-tmt run -i tft-cli
	tmt run -i tft-cli report -vvv

tox:
	tox

test: build pre-commit tmt tox

clean:
	podman rmi quay.io/testing-farm/cli:$(TAG)
