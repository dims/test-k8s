PYTHON ?= python3
TEST_INFRA_DIR ?= $(shell go env GOPATH 2>/dev/null | awk -F: '{print $$1 "/src/k8s.io/test-infra"}')

.PHONY: drift test-infra-drift

drift: test-infra-drift

test-infra-drift:
	$(PYTHON) scripts/check_test_infra_drift.py --test-infra-dir $(TEST_INFRA_DIR)
