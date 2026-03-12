PYTHON ?= python3

.PHONY: drift test-infra-drift

drift: test-infra-drift

test-infra-drift:
	$(PYTHON) scripts/check_test_infra_drift.py $(if $(TEST_INFRA_DIR),--test-infra-dir $(TEST_INFRA_DIR),)
