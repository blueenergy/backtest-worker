CI_DOCKER_IMAGE_BACKTEST := prime/backtest-worker
CI_DOCKER_IMAGE_SCREENING := prime/screening-worker
CI_DOCKER_REGISTRY ?= prime-local.artifactory-espoo1.int.net.nokia.com
CI_PIP_INDEX ?=
CI_HTTP_PROXY ?=
CI_NO_PROXY ?= localhost,127.,10.,.nsn-net.net,.nokia.com,.nsn-rdnet.net
PYTHON ?= python

GIT_BRANCH := $(shell git rev-parse --abbrev-ref HEAD 2>/dev/null)
DOCKER_IMAGE_TAG := $(shell if [ x${GIT_BRANCH} = xmaster ]; then echo latest; else echo ${GIT_BRANCH}; fi;)
DOCKER_BIN := $(shell if [ -f /usr/bin/podman ]; then echo podman; else echo docker; fi;)
DOCKER_BUILD_BIN := $(shell if [ -f /usr/bin/podman ]; then echo podman build --tls-verify=false; else echo docker build; fi;)
DOCKER_PUSH_BIN := $(shell if [ -f /usr/bin/podman ]; then echo podman push --tls-verify=false --compression-format=gzip; else echo docker push; fi;)

DOCKER_CONTEXT ?= ..
BACKTEST_DOCKERFILE := docker/Dockerfile.backtest
SCREENING_DOCKERFILE := docker/Dockerfile.screening

BUILD_ARGS :=
ifdef CI_PIP_INDEX
BUILD_ARGS += --build-arg CI_PIP_INDEX=${CI_PIP_INDEX}
endif
ifdef CI_HTTP_PROXY
BUILD_ARGS += --build-arg http_proxy=http://${CI_HTTP_PROXY} --build-arg https_proxy=http://${CI_HTTP_PROXY}
ifdef CI_NO_PROXY
BUILD_ARGS += --build-arg no_proxy=${CI_NO_PROXY}
endif
endif

all: package test release

package: build-backtest build-screening

build-backtest:
	${DOCKER_BUILD_BIN} ${BUILD_ARGS} -t ${CI_DOCKER_REGISTRY}/${CI_DOCKER_IMAGE_BACKTEST}:${DOCKER_IMAGE_TAG} -f ${BACKTEST_DOCKERFILE} ${DOCKER_CONTEXT}

build-screening:
	${DOCKER_BUILD_BIN} ${BUILD_ARGS} -t ${CI_DOCKER_REGISTRY}/${CI_DOCKER_IMAGE_SCREENING}:${DOCKER_IMAGE_TAG} -f ${SCREENING_DOCKERFILE} ${DOCKER_CONTEXT}

test: build-backtest
	${DOCKER_BIN} run --rm -w /app/backtest-worker --entrypoint /bin/sh ${CI_DOCKER_REGISTRY}/${CI_DOCKER_IMAGE_BACKTEST}:${DOCKER_IMAGE_TAG} -c "pip install --no-cache-dir -r requirements-dev.txt && python -m pytest tests"
test-only:
	${DOCKER_BIN} run --rm -w /app/backtest-worker --entrypoint /bin/sh ${CI_DOCKER_REGISTRY}/${CI_DOCKER_IMAGE_BACKTEST}:${DOCKER_IMAGE_TAG} -c "pip install --no-cache-dir -r requirements-dev.txt && python -m pytest tests"

test-local:
	${PYTHON} -m pip install --no-cache-dir -r requirements-dev.txt
	PYTHONPATH=${PWD}:${PWD}/../data-access-lib/src:${PWD}/../quant-strategies:${PYTHONPATH} ${PYTHON} -m pytest tests


release: package
	${DOCKER_PUSH_BIN} ${CI_DOCKER_REGISTRY}/${CI_DOCKER_IMAGE_BACKTEST}:${DOCKER_IMAGE_TAG}
	${DOCKER_PUSH_BIN} ${CI_DOCKER_REGISTRY}/${CI_DOCKER_IMAGE_SCREENING}:${DOCKER_IMAGE_TAG}

clean:
	rm -f *.tar.gz

.PHONY: all package build-backtest build-screening test test-only test-local release clean
