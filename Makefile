.DEFAULT_GOAL := help

# Use force targets instead of listing all the targets we have via .PHONY
# https://www.gnu.org/software/make/manual/html_node/Force-Targets.html#Force-Targets
.FORCE:

# default image tag set to current user name
IMAGE = quay.io/testing-farm/cli
IMAGE_TAG ?= ${USER}

PROJECT_ROOT := $(shell git rev-parse --show-toplevel)

build:  ## Build the container image
	rm -rf $(PROJECT_ROOT)/dist
	poetry build
	buildah bud --layers -t $(IMAGE):$(IMAGE_TAG) -f container/Dockerfile .

push:  ## Push the container image to quay.io
	buildah push $(IMAGE):$(IMAGE_TAG)

enter:  ## Run bash in the container with the code
	podman run --rm -itv $$(pwd):/code:Z $(IMAGE):$(IMAGE_TAG) bash

pre-commit:  ## Run pre-commit on all files
	pre-commit run --all-files

tmt:  ## Run available tmt tests
	-tmt clean runs -i tft-cli
	-tmt run -e IMAGE_TAG=$(IMAGE_TAG) -i tft-cli
	tmt run -i tft-cli report -vvv

tox:  ## Run tox based tests
	poetry run tox

testing-farm: build push  ## Run the tmt tests in Testing Farm
	testing-farm request -e IMAGE_TAG=$(IMAGE_TAG)

test: build pre-commit tmt tox  ## Run all the tests

test-container:  ## Test the container via goss
	if command -v goss; then \
		MOUNT_GOSS="-v $$(command -v goss):/usr/bin/goss:Z)"; \
	fi
	podman run -it --rm -v $$PWD:/code:Z $$MOUNT_GOSS --entrypoint make $(IMAGE):$(IMAGE_TAG) goss

goss:  ## Run goss inside the container
	if [ ! -e "/.testing-farm-cli" ]; then \
		echo "Error: expected to run inside the CLI container only."; \
		exit 1; \
	fi
	if ! command -v goss; then \
		wget -O /usr/bin/goss https://github.com/goss-org/goss/releases/latest/download/goss-linux-amd64; \
		chmod +rx /usr/bin/goss; \
	fi
	cd container && goss validate

clean:  ## Cleanup
	buildah rmi $(IMAGE):$(IMAGE_TAG)

# See https://www.thapaliya.com/en/writings/well-documented-makefiles/ for details.
reverse = $(if $(1),$(call reverse,$(wordlist 2,$(words $(1)),$(1)))) $(firstword $(1))

help: .FORCE  ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "$(info $(PRELUDE))"} /^[a-zA-Z_/-]+:.*?##/ { printf "  \033[36m%-35s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(call reverse, $(MAKEFILE_LIST))
