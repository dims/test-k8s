# test-k8s

`test-k8s` is a small GitHub Actions harness for running a focused Kubernetes CI matrix against the refs configured in [`config.yaml`](./config.yaml).

Today that means:

- Kubernetes: `kubernetes/kubernetes@master`
- containerd: `containerd/containerd@main`

Each job resolves those refs to exact commit SHAs at runtime, prints both SHAs in the logs and job summary, and uploads collected artifacts from `ARTIFACTS`.

## Actions

[![Verify](https://github.com/dims/test-k8s/actions/workflows/verify.yml/badge.svg?branch=main)](https://github.com/dims/test-k8s/actions/workflows/verify.yml)
[![Unit Tests](https://github.com/dims/test-k8s/actions/workflows/unit.yml/badge.svg?branch=main)](https://github.com/dims/test-k8s/actions/workflows/unit.yml)
[![Integration Tests](https://github.com/dims/test-k8s/actions/workflows/integration.yml/badge.svg?branch=main)](https://github.com/dims/test-k8s/actions/workflows/integration.yml)
[![Typecheck](https://github.com/dims/test-k8s/actions/workflows/typecheck.yml/badge.svg?branch=main)](https://github.com/dims/test-k8s/actions/workflows/typecheck.yml)
[![Dependencies](https://github.com/dims/test-k8s/actions/workflows/dependencies.yml/badge.svg?branch=main)](https://github.com/dims/test-k8s/actions/workflows/dependencies.yml)
[![Cmd Tests](https://github.com/dims/test-k8s/actions/workflows/cmd-tests.yml/badge.svg?branch=main)](https://github.com/dims/test-k8s/actions/workflows/cmd-tests.yml)
[![Linter Hints](https://github.com/dims/test-k8s/actions/workflows/linter-hints.yml/badge.svg?branch=main)](https://github.com/dims/test-k8s/actions/workflows/linter-hints.yml)
[![E2E (kind)](https://github.com/dims/test-k8s/actions/workflows/e2e-kind.yml/badge.svg?branch=main)](https://github.com/dims/test-k8s/actions/workflows/e2e-kind.yml)
[![Conformance (kind, GA-only)](https://github.com/dims/test-k8s/actions/workflows/conformance-kind.yml/badge.svg?branch=main)](https://github.com/dims/test-k8s/actions/workflows/conformance-kind.yml)
[![Node E2E](https://github.com/dims/test-k8s/actions/workflows/node-e2e.yml/badge.svg?branch=main)](https://github.com/dims/test-k8s/actions/workflows/node-e2e.yml)

Full run history: <https://github.com/dims/test-k8s/actions>

## What Runs

| Workflow | Purpose | Command |
| --- | --- | --- |
| `Verify` | Kubernetes verify lane, excluding typecheck and dependency verification which run separately | `./hack/jenkins/verify-dockerized.sh` |
| `Unit Tests` | Kubernetes unit tests | `make test` |
| `Integration Tests` | Kubernetes integration tests | `./hack/jenkins/test-integration-dockerized.sh` |
| `Typecheck` | Kubernetes typecheck verify target | `make verify WHAT=typecheck` |
| `Dependencies` | Dependency and vendor verification | `make verify WHAT="external-dependencies-version vendor vendor-licenses"` |
| `Cmd Tests` | Kubernetes command/integration-style command tests | `./hack/jenkins/test-cmd-dockerized.sh` |
| `Linter Hints` | `golangci-lint` PR hints lane | `make verify WHAT=golangci-lint-pr-hints` |
| `E2E (kind)` | Focused non-slow, non-disruptive kind-based e2e lane | `e2e-k8s.sh` |
| `Conformance (kind, GA-only)` | kind-based conformance with alpha and beta APIs disabled | `e2e-k8s.sh` |
| `Node E2E` | Builds containerd from the configured ref, wires it into the runner, then runs Kubernetes node e2e | `make test-e2e-node` |

## Triggers

Every workflow runs:

- on pushes to `main` that touch [`config.yaml`](./config.yaml), [`.github/actions/`](./.github/actions/), or the workflow file itself
- on pull requests to `main` with the same path filters
- on manual `workflow_dispatch`
- every 6 hours via `schedule: '0 */6 * * *'`

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
