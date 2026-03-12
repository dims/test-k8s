# test-k8s

`test-k8s` is a small GitHub Actions harness for running a focused Kubernetes CI matrix against the refs configured in [`config.yaml`](./config.yaml).

Today that means:

- Kubernetes: `kubernetes/kubernetes@master`
- containerd: `containerd/containerd@main`

Each job resolves those refs to exact commit SHAs at runtime, prints both SHAs in the logs and job summary, and uploads collected artifacts from `ARTIFACTS`.

## Actions

Full run history: <https://github.com/dims/test-k8s/actions>

| Workflow | Status | Purpose | Command |
| --- | --- | --- | --- |
| `Verify` | [![Verify](https://github.com/dims/test-k8s/actions/workflows/verify.yml/badge.svg?branch=main)](https://github.com/dims/test-k8s/actions/workflows/verify.yml) | Kubernetes verify lane, excluding typecheck and dependency verification which run separately | `./hack/jenkins/verify-dockerized.sh` |
| `Unit Tests` | [![Unit Tests](https://github.com/dims/test-k8s/actions/workflows/unit.yml/badge.svg?branch=main)](https://github.com/dims/test-k8s/actions/workflows/unit.yml) | Kubernetes unit tests | `make test` |
| `Integration Tests` | [![Integration Tests](https://github.com/dims/test-k8s/actions/workflows/integration.yml/badge.svg?branch=main)](https://github.com/dims/test-k8s/actions/workflows/integration.yml) | Kubernetes integration tests | `./hack/jenkins/test-integration-dockerized.sh` |
| `Typecheck` | [![Typecheck](https://github.com/dims/test-k8s/actions/workflows/typecheck.yml/badge.svg?branch=main)](https://github.com/dims/test-k8s/actions/workflows/typecheck.yml) | Kubernetes typecheck verify target | `make verify WHAT=typecheck` |
| `Dependencies` | [![Dependencies](https://github.com/dims/test-k8s/actions/workflows/dependencies.yml/badge.svg?branch=main)](https://github.com/dims/test-k8s/actions/workflows/dependencies.yml) | Dependency and vendor verification | `make verify WHAT="external-dependencies-version vendor vendor-licenses"` |
| `Cmd Tests` | [![Cmd Tests](https://github.com/dims/test-k8s/actions/workflows/cmd-tests.yml/badge.svg?branch=main)](https://github.com/dims/test-k8s/actions/workflows/cmd-tests.yml) | Kubernetes command/integration-style command tests | `./hack/jenkins/test-cmd-dockerized.sh` |
| `Linter Hints` | [![Linter Hints](https://github.com/dims/test-k8s/actions/workflows/linter-hints.yml/badge.svg?branch=main)](https://github.com/dims/test-k8s/actions/workflows/linter-hints.yml) | `golangci-lint` PR hints lane | `make verify WHAT=golangci-lint-pr-hints` |
| `E2E (kind)` | [![E2E (kind)](https://github.com/dims/test-k8s/actions/workflows/e2e-kind.yml/badge.svg?branch=main)](https://github.com/dims/test-k8s/actions/workflows/e2e-kind.yml) | Focused non-slow, non-disruptive kind-based e2e lane | `e2e-k8s.sh` |
| `E2E (kind, alpha-beta-features)` | [![E2E (kind, alpha-beta-features)](https://github.com/dims/test-k8s/actions/workflows/e2e-kind-alpha-beta-features.yml/badge.svg?branch=main)](https://github.com/dims/test-k8s/actions/workflows/e2e-kind-alpha-beta-features.yml) | Off-by-default alpha and beta feature coverage in kind with all APIs enabled | `e2e-k8s.sh` |
| `Conformance (kind, GA-only)` | [![Conformance (kind, GA-only)](https://github.com/dims/test-k8s/actions/workflows/conformance-kind.yml/badge.svg?branch=main)](https://github.com/dims/test-k8s/actions/workflows/conformance-kind.yml) | kind-based conformance with alpha and beta APIs disabled | `e2e-k8s.sh` |
| `Node E2E` | [![Node E2E](https://github.com/dims/test-k8s/actions/workflows/node-e2e.yml/badge.svg?branch=main)](https://github.com/dims/test-k8s/actions/workflows/node-e2e.yml) | Builds containerd from the configured ref, wires it into the runner, then runs Kubernetes node e2e | `make test-e2e-node` |
| `Test-Infra Drift` | [![Test-Infra Drift](https://github.com/dims/test-k8s/actions/workflows/test-infra-drift.yml/badge.svg?branch=main)](https://github.com/dims/test-k8s/actions/workflows/test-infra-drift.yml) | Detects curated drift between these workflows and upstream `kubernetes/test-infra` job definitions | `make test-infra-drift` |

## Triggers

Workflow triggers vary:

- The main CI lanes (`Verify`, `Unit Tests`, `Integration Tests`, `Typecheck`, `Dependencies`, `Cmd Tests`, `Linter Hints`, `E2E (kind)`, `E2E (kind, alpha-beta-features)`, `Conformance (kind, GA-only)`, and `Node E2E`) run on pushes to `main` and pull requests to `main` when relevant workflow/action/config files change, on manual `workflow_dispatch`, and every 6 hours.
- `Test-Infra Drift` runs on `workflow_dispatch`, daily, and when tracked workflow or drift-detector files change.

## Repository Layout

- [`config.yaml`](./config.yaml): upstream repositories and refs to test
- [`.github/workflows/`](./.github/workflows): one top-level GitHub Actions workflow per CI lane
- [`.github/actions/load-config/`](./.github/actions/load-config): resolves configured refs to exact SHAs
- [`.github/actions/setup-kubernetes/`](./.github/actions/setup-kubernetes): checks out Kubernetes and installs the matching Go toolchain
- [`.github/actions/report-revisions/`](./.github/actions/report-revisions): prints the Kubernetes and containerd revisions under test
- [`.github/actions/collect-logs/`](./.github/actions/collect-logs): gathers and uploads artifacts from `ARTIFACTS`

## Notes

- `Linter Hints` is configured with `continue-on-error`, so it is informational rather than a hard gate.
- The Actions page is the main dashboard for this repo because each CI lane is split into its own top-level workflow.
- To compare these workflows against the curated upstream `test-infra` jobs, run `make test-infra-drift`. It defaults `TEST_INFRA_DIR` from `go env GOPATH`, and you can still override it explicitly.
