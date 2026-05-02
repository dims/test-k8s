# Kubernetes carry patches

Each file is a `git format-patch` artefact applied (in numeric order) on top
of the upstream `kubernetes/kubernetes` master checkout during CI.  The patches
are applied by the `setup-kubernetes` action via `git am --3way`.

Patches are numbered sequentially; gaps mean a patch was retired after the fix
merged upstream and was dropped here.

## Required fields for each patch entry

Every new patch entry must include:

- **Failing tests** — exact test function name(s) and package path
- **Observed in** — which CI job (`Integration Tests`, `Unit Tests`, etc.) AND which remote (`NVIDIA-dev/test-k8s`, `dims/test-k8s`, or both), including the commit SHA where it was first seen
- **Symptom** — what the log shows (error message, duration, stack fragment)
- **Fix** — what changed and why
- **Upstream status** — open issue / PR link if one exists, or "local workaround"

If a patch is updated (e.g. a threshold is raised), add a **Change history** table recording: when, what triggered the change, which remote showed the failure, the triggering commit SHA, and what changed.

---

## Patch catalogue

### 0001 — test/integration: give apiserver startup more room in CI

**File:** `0001-test-integration-give-apiserver-startup-more-room-in.patch`  
**Failing tests:** `Test4xxStatusCodeInvalidPatch`, `TestClientCAUpdate`, `TestInsecurePodLogs`, `TestSubjectAccessReview`, `TestAdmission`, `TestOneNodeDaemonLaunchesPod`, and others in `test/integration/apiserver/`, `test/integration/auth/`, `test/integration/daemonset/`, `test/integration/admission/`  
**Symptom:** Tests fail with `timed out waiting for the condition` in `test_server.go` after exactly the startup budget elapses. The kube-apiserver starts successfully but the `rbac/bootstrap-roles` post-start hook is still running when the health-check poll times out. Each test package starts its own apiserver against a shared etcd; under heavy parallelism, RBAC bootstrap can take 50–56 s.  
**Fix:** Raise the health-check poll budget in `StartTestServer` from 10 s (upstream default) to 120 s.  
**Upstream status:** Local workaround; not upstreamed (timeout is environment-specific).

**Change history:**

| When | Trigger | Remote | Commit | Change |
|------|---------|--------|--------|--------|
| Mar 2026 | Failures at ~31-35 s on cpu16 runners | `NVIDIA-dev` + `dims` | `243b075e` wave | 10 s → 60 s |
| Apr 2026 | Failures at ~61 s on cpu32 runners (commits `a369ed79`, `91f0a706`) after runner upgrade; `dims` was green | `NVIDIA-dev` only | `9a0bb3d4` | 60 s → 120 s |

---

### 0005 — test/e2e: relax PLR convergence checks after resize

**File:** `0005-test-e2e-wait-for-pod-resize-conditions-to-settle.patch`  
**Observed in:** E2E (kind, alpha-beta-features) — `dims/test-k8s` (4-vCPU ubuntu-24.04) and `NVIDIA-dev/test-k8s` (cpu16 era, pre-`d85809` runner upgrade)  
**Failing tests:** Pod-level-resources (PLR) in-place resize suite (`test/e2e/common/node/pod_resize.go`)  
**Symptom:** `ExpectPodResized` required `PodResizeInProgress` / `PodResizePending` to already be gone and restart counts to be exact. In practice, both signals lag or overshoot after resource convergence — a failing run had `restartCount 2` where the test expected `1`.  
**Fix:** Treat resize conditions as best-effort diagnostics and treat expected restarts as a lower bound (preserving the exact-zero invariant for no-restart cases).  
**Upstream status:** Local workaround; PLR semantics were still in flux at the time.

---

### 0011 — test/e2e: make PLR pod-level-only restart expectations optional

**File:** `0011-test-e2e-make-PLR-pod-level-only-restart-expectation.patch`  
**Observed in:** E2E (kind, alpha-beta-features) — `dims/test-k8s` and `NVIDIA-dev/test-k8s` (cpu16 era, pre-`d85809` runner upgrade)  
**Failing tests:** PLR pod-level-only resize scenarios in `test/e2e/common/node/pod_level_resources_resize.go`  
**Symptom:** After patch 0005, the inverse failure appeared: pod-level-only limit changes converged with `restartCount 0` on both remotes, while the test still required `restartCount 1`. The kubelet's restart behaviour for pod-level-only limit changes is not stable across CI environments.  
**Fix:** Added `RestartCountFlexible` field to `ResizableContainerInfo`; pod-level-only limit changes under `RestartContainer` policy now accept either 0 or 1 extra restart. Container-specific resource changes still require exactly 1 restart.  
**Upstream status:** Local workaround; depends on kubelet behaviour that is not yet settled upstream.

---

### 0012 — test/integration/dra: avoid duplicate sequential sharing stress

**File:** `0012-test-integration-dra-avoid-duplicate-sequential-sh.patch`  
**Observed in:** Integration Tests — `dims/test-k8s` and `NVIDIA-dev/test-k8s` (cpu16 era, pre-`d85809`); wall-time concern, not a hard failure  
**Failing tests:** None (no failure; this reduces test wall time)  
**Symptom:** `TestDRA` was running `ShareResourceClaimSequentially` in both the `GA` and `all` configurations. The duplicate added significant package wall time on slower CI runners without testing any additional behaviour.  
**Fix:** Remove the `ShareResourceClaimSequentially` call from the `GA` configuration; keep it only in `all`.  
**Upstream status:** Local optimisation; a rebase of an earlier patch after upstream split the DRA integration test file.

---

### 0014 — test/integration/apiserver: poll schema activation in CRD validator test

**File:** `0014-test-integration-apiserver-poll-schema-activation-i.patch`  
**Observed in:** Integration Tests — `dims/test-k8s` and `NVIDIA-dev/test-k8s` (cpu16 era, pre-`d85809`)  
**Failing tests:** `TestCustomResourceValidatorsWithSchemaConversion` in `test/integration/apiserver/`  
**Symptom:** After updating a CRD schema, the test immediately updated an existing CR expecting the new CEL validation error. Schema propagation is asynchronous, so the update raced the new schema and produced no error, causing the test to fail intermittently.  
**Fix:** Poll the CR update until the expected validation error appears, making the test wait for schema activation.  
**Upstream status:** Matches upstream flake [issue #135540](https://github.com/kubernetes/kubernetes/issues/135540) and proposed fix in [PR #135660](https://github.com/kubernetes/kubernetes/pull/135660). Carry patch kept until the upstream fix merges and is present in master.

---

### 0015 — pkg/controller: deep copy spec in FakePodControl.CreatePodsWithGenerateName

**File:** `0015-pkg-controller-deep-copy-spec-in-FakePodControl-Cre.patch`  
**Observed in:** Unit Tests (with `-race`) — `dims/test-k8s` and `NVIDIA-dev/test-k8s` (cpu16 era, pre-`d85809`)  
**Failing tests:** `TestExpectationsOnRecreate` in `pkg/controller/replicaset/`  
**Symptom:** `FakePodControl.CreatePodsWithGenerateName` modified `spec.GenerateName` on the caller's pointer before appending to `f.Templates`. When the informer mutation detector ran `reflect.DeepEqual` on the same cached `ReplicaSet` template spec concurrently, the data race was detected under `-race`.  
**Fix:** Deep-copy `spec` before setting `GenerateName` so the original cached object is never mutated.  
**Upstream status:** Local fix; not yet upstreamed at the time of writing.

---

### 0016 — pkg/kubelet/volumemanager: fix flaky TestWaitForAllPodsUnmount on slow CI runners

**File:** `0016-pkg-kubelet-volumemanager-fix-flaky-TestWaitForAllPo.patch`  
**Observed in:** Unit Tests — `dims/test-k8s` and `NVIDIA-dev/test-k8s` (cpu16 era, pre-`d85809`)  
**Failing tests:** `TestWaitForAllPodsUnmount` (20-pod subtest) in `pkg/kubelet/volumemanager/`  
**Symptom:** Each subtest called `ktesting.Init(t)` which draws down the shared `-timeout=180s` package budget. On slow runners, earlier subtests (1-pod, 10-pod) consumed enough of the budget that the 20-pod subtest had under two minutes left for `WaitForAttachAndMount`, causing a spurious context-deadline failure before the actual assertion.  
**Fix:** Use a dedicated 3-minute context for the attach-and-mount setup goroutines with `defer attachCancel()` for cleanup.  
**Upstream status:** References upstream flake [issue #136255](https://github.com/kubernetes/kubernetes/issues/136255).

---

### 0017 — test/integration/scheduler/podgroup: fix flaky TestPostFilterInvocationCount

**File:** `0017-test-integration-scheduler-podgroup-fix-flaky-TestP.patch`  
**Observed in:** Integration Tests — `dims/test-k8s` and `NVIDIA-dev/test-k8s` (cpu16 era, pre-`d85809`)  
**Failing tests:** `TestPostFilterInvocationCount` in `test/integration/scheduler/podgroup/`  
**Symptom:** The test polled for `mockPlugin.count == 3` (exactly). With zero backoff configured, the scheduler retried unscheduled pods immediately. On slow runners, the count had already advanced past 3 before the first 100 ms poll fired, so the `== 3` condition never matched and the test timed out.  
**Fix:** Change the poll condition to `>= 3` so it succeeds as soon as at least one call per pod-group pod has been observed.  
**Upstream status:** Local fix; the upstream test uses exact equality which is inherently fragile with zero backoff.

---

### 0018 — test/integration/garbagecollector: fix flaky TestCascadingDeleteOnCRDConversionFailure

**File:** `0018-test-integration-garbagecollector-fix-flaky-TestCas.patch`  
**Observed in:** Integration Tests — `dims/test-k8s` (4-vCPU ubuntu-24.04 runner); first seen on commit `d85809d6` (runner upgrade wave)  
**Failing tests:** `TestCascadingDeleteOnCRDConversionFailure` in `test/integration/garbagecollector/`  
**Symptom:** The server-side watch cache for a bad CRD oscillates between failing and briefly recovering. If the metadata informer's initial LIST coincides with a recovery window, `HasSynced()` becomes permanently `true` (one-way latch in client-go). The final `IsSynced()` assertion then fails the test even though the primary behaviour (cascading delete despite bad webhook) worked correctly.  
**Fix:** (1) Replace fixed sleep with a poll to give slow runners enough time to observe the unsynced state. (2) Demote the final `IsSynced()` check from `t.Fatal` to `t.Log` since it is inherently non-deterministic.  
**Upstream status:** Local fix; the non-determinism is a fundamental property of the one-way `HasSynced` latch.

---

### 0019 — test/e2e_node: raise container_threads_max bound for large-memory nodes

**File:** `0019-test-e2e_node-raise-container_threads_max-bound-for-.patch`  
**Observed in:** Node E2E — `NVIDIA-dev/test-k8s` only; runner `linux-amd64-cpu32` (m7i.8xlarge, 32 vCPU / 128 GB RAM); first seen on commit `d85809d6` (first cpu32 run after runner upgrade)  
**Failing tests:** `ContainerMetrics should report container metrics` in `test/e2e_node/container_metrics_test.go`  
**Symptom:** The `container_threads_max` cAdvisor metric reports the kernel thread limit (`/proc/sys/kernel/threads-max`), which the kernel derives from available RAM when no cgroup `pids.max` limit is set. On the 128 GiB runner this limit is ~152,051, exceeding the old upper bound of 100,000.  
**Fix:** Raise the upper bound from 100,000 to 1,000,000 (covers nodes up to ~1 TiB RAM). Follows the precedent of upstream commit `a75cd2e0f47`.  
**Upstream status:** Submitted and pending upstream review. Specific to large-memory self-hosted runners — standard Prow nodes have ≤16 GiB.

---

### 0020 — test/integration/apiserver: raise per-resource admission throughput limit

**File:** `0020-test-integration-apiserver-raise-per-resource-admis.patch`  
**Observed in:** Integration Tests — `NVIDIA-dev/test-k8s` only; runner `linux-amd64-cpu32` (m7i.8xlarge); consistently failed on commits `d85809d6` and `00ad7fa32` (first two cpu32 runs); `dims` was not affected (4-vCPU ubuntu-24.04 runs fewer packages in parallel)  
**Failing tests:** `TestWebhookAdmissionWithWatchCache` and `TestPolicyAdmissionV1beta1` in `test/integration/apiserver/admissionwebhook/` and `test/integration/apiserver/cel/`  
**Symptom:** Both tests assert that admission webhook operations average < 150 ms per resource. The 150 ms ceiling was set in 2019 (commit `e9bb667bf77`) for dedicated GCP Prow VMs. On the 32-vCPU m7i.8xlarge runner more packages run in parallel, increasing shared-resource (etcd, kube-apiserver) contention. Individual delete operations take 1–7 s each (especially `configmaps`, `endpoints`, `events`), pushing the average to 164–170 ms. The tests ran with `--runtime-config=api/all=true` (~590 resource+verb combinations), amplifying the effect.  
**Fix:** Raise the ceiling from 150 ms to 500 ms in both files. This still catches catastrophic rate-limiting (the original concern — from `e9bb667bf77`) while tolerating normal load variation across CI environments.  
**Upstream status:** Local workaround. The threshold is inherently machine-specific; upstreaming would require a more environment-aware approach.

---

### 0021 — pkg/kubelet/cm/dra: raise gRPC client timeout in should-timeout tests

**File:** `0021-pkg-kubelet-cm-dra-raise-gRPC-client-timeout-in-sho.patch`  
**Observed in:** Unit Tests — `NVIDIA-dev/test-k8s` only; runner `linux-amd64-cpu32` (m7i.8xlarge); seen intermittently on commit `00ad7fa32` (passed on `d85809d6`, failed on second run); `dims` was not affected  
**Failing tests:** `TestUnprepareResources/should_timeout` (and the equivalent in `TestPrepareResources`) in `pkg/kubelet/cm/dra/manager_test.go`  
**Symptom:** The "should timeout" test case configures a 20 ms gRPC client deadline (server sleeps 40 ms). The test asserts `unprepareResourceCalls == 1`, meaning the server must have received the RPC before the deadline fires. On a heavily loaded 32-core machine, gRPC connection setup or goroutine scheduling can itself exceed 20 ms, so the `DeadlineExceeded` fires before the server handler even starts — leaving the call counter at 0. The 20 ms value was introduced in commit `10b6319e64b` ("fix slow dra unit test") to speed up the test; it proved too tight on cpu32.  
**Fix:** Raise the client timeout from 20 ms to 200 ms (server sleep correspondingly stays 2× = 400 ms). The timeout path is still exercised; the deadline simply allows enough scheduling headroom.  
**Upstream status:** Local workaround. The value is environment-specific; a more robust fix would ensure the gRPC connection is pre-warmed before starting the timeout measurement.

---

### 0022 — cmd/kube-apiserver/app/testing: raise healthz poll budget to 120 s

**File:** `0022-cmd-kube-apiserver-app-testing-raise-healthz-poll-b.patch`  
**Observed in:** Integration Tests — `dims/test-k8s` (ubuntu-24.04) on commit `9a0bb3d4`; also expected to affect `NVIDIA-dev/test-k8s` cpu32 runs  
**Failing tests:** `TestStructuredAuthenticationConfig/valid_config_no_conditions` in `test/integration/apiserver/anonymous/`; also packages `test/integration/apiserver/oidc`, `test/integration/certificates`, `test/integration/controlplane/transformation`, `test/integration/clustertrustbundles`  
**Symptom:** `kubeapiservertesting.StartTestServerOrDie` uses a 60-second health-check poll (`wait.Poll(100ms, time.Minute, ...)`). On loaded CI runners where many packages start in parallel, RBAC bootstrap contention pushes apiserver startup past 60 s. The poll times out with `"failed to wait for /healthz to return ok: timed out waiting for the condition"`, failing tests at exactly ~61–62 s.  
**Fix:** Raise the health-check budget in `cmd/kube-apiserver/app/testing/testserver.go` from `time.Minute` (60 s) to `120*time.Second`. This mirrors the identical fix applied to `test/integration/framework/test_server.go` in patch 0001.  
**Upstream status:** Local workaround; the timeout is environment-specific.

---

### 0023 — pkg/registry/scheduling/rest: raise bootstrap-system-priority-classes poll budget to 120 s

**File:** `0023-pkg-registry-scheduling-rest-raise-bootstrap-system-.patch`  
**Observed in:** Integration Tests — `NVIDIA-dev/test-k8s` only; runner `linux-amd64-cpu32` (m7i.8xlarge); seen on commits `1bb6995f` and `64d4a0c2` (two consecutive runs)  
**Failing tests:** `TestAPIServerTransportMetrics` in `test/integration/client/metrics/`  
**Symptom:** The `scheduling/bootstrap-system-priority-classes` PostStartHook in `pkg/registry/scheduling/rest/storage_scheduling.go` uses `wait.Poll(1s, 30s)` to retry `PriorityClass` creation while storage version registration completes. On 32-vCPU runners where many integration test packages start their own apiserver simultaneously, etcd and storage version registration contention causes repeated `ServiceUnavailable` errors. After 30 s the poll times out, the hook returns an error, the apiserver fatally exits with `"PostStartHook scheduling/bootstrap-system-priority-classes failed: unable to add default system priority classes: timed out waiting for the condition"`, and the test binary exits before reporting results.  
**Fix:** Raise the poll budget from `30*time.Second` to `120*time.Second`. Consistent with the same approach applied to health-check probes in patches 0001 and 0022.  
**Upstream status:** Local workaround; the threshold is environment-specific.

---

### 0024 — test/integration/controllermanager: raise leader-election-release poll budget to 30 s

**File:** `0024-test-integration-controllermanager-raise-leader-ele.patch`  
**Observed in:** Integration Tests — `NVIDIA-dev/test-k8s` only; runner `linux-amd64-cpu32`; seen on commit `455baecae9d1` (run 25141185206 at 00:34 UTC)  
**Failing tests:** `TestLeaderElectionReleaseOnCancel` in `test/integration/controllermanager/`  
**Symptom:** After shutting down the KCM, the test polls for 10 s (with `return false, err` on any GET error) to confirm the leader-election lease holder is cleared. On a 32-vCPU runner under heavy parallel load the apiserver hits handler timeouts; the GET for the lease returns `context deadline exceeded` after the 10 s budget is fully consumed, and the poll propagates that error immediately instead of retrying, producing: `expected lease holder to be cleared after shutdown, but got "<nil>": Get "...": context deadline exceeded`.  
**Fix:** Raise the poll budget from `10*time.Second` to `30*time.Second` and change `return false, err` to `return false, nil` so transient apiserver-overload errors are retried.  
**Upstream status:** Local workaround; test added in March 2026 (commit `db60e61ac`) with no upstream fix yet.

---

### 0025 — test/integration/apiextensions: retry transient apiserver errors in TestApplyCRDuringCRDFinalization

**File:** `0025-test-integration-apiextensions-retry-transient-err.patch`  
**Observed in:** Integration Tests — `dims/test-k8s`; runner `ubuntu-24.04` (4-vCPU GitHub-hosted); first seen on commit `ac0ac2f70f5a` (run 25148174740)  
**Failing tests:** `TestApplyCRDuringCRDFinalization` in `staging/src/k8s.io/apiextensions-apiserver/test/integration/`  
**Symptom:** Apiserver returned `http: Handler timeout` for a PUT to CRD status under etcd contention. The `PollUntilContextTimeout` loop at line 193 used `return false, err`, propagating the transient GET error immediately and failing the test within ~3.84 s with: `timed out waiting for CRD Terminating condition to be set`.  
**Fix:** Change `return false, err` to `return false, nil` so transient apiserver-overload errors are retried rather than propagated. The poll already uses `wait.ForeverTestTimeout` as its deadline so retrying is safe.  
**Upstream status:** Related to GitHub issue [#137603](https://github.com/kubernetes/kubernetes/issues/137603). Upstream PR #135567 (merged 2026-01-14) added the wait loop but left `return false, err` in place. Local workaround until the upstream fix lands.

---

### 0026 — test/integration/daemonset: raise poll budgets to 120 s and retry transient errors

**File:** `0026-test-integration-daemonset-raise-poll-budgets-to-12.patch`  
**Observed in:** Integration Tests — `NVIDIA-dev/test-k8s` only; runner `linux-amd64-cpu32`; first seen on commit `303b83323f11` (run 25150377062); kubernetes SHA `4de87946765`  
**Failing tests:** `TestOneNodeDaemonLaunchesPod/OnDelete` in `test/integration/daemonset/`  
**Symptom:** `validateDaemonSetStatus` polls `ds.Status.NumberReady` with a 60-second budget. On the loaded 32-vCPU runner, the daemonset controller's status-update loop was slow enough to exhaust the budget, producing: `daemonset_test.go:488: timed out waiting for the condition`. The subtest took 135.99 s total (including setup + `validateDaemonSetPodsAndMarkReady`), leaving the status poll no head room.  
**Fix:** Raise all four poll helper functions (`validateDaemonSetPodsAndMarkReady`, `validateDaemonSetPodsActive`, `validateDaemonSetStatus`, `validateUpdatedNumberScheduled`) from `60*time.Second` to `120*time.Second`. Also change `return false, err` to `return false, nil` in `validateDaemonSetPodsAndMarkReady` (UpdateStatus) and `validateDaemonSetStatus` / `validateUpdatedNumberScheduled` (Get) to retry transient apiserver errors rather than propagating them.  
**Upstream status:** No open upstream issue found. Local workaround.

**Change history:**

| When | Trigger | Remote | Commit | Change |
|------|---------|--------|--------|--------|
| Apr 2026 | First failure, OnDelete 135.99s | `NVIDIA-dev` | `303b83323f11` | 60 s → 120 s (patch 0026) |
| Apr 2026 | Second failure, OnDelete 197.20s; daemonset controller version conflict due to `StaleControllerConsistencyDaemonSet` Beta gate; informer didn't catch up in 120 s | `NVIDIA-dev` | `a601d275ed95` | 120 s → 180 s for `validateDaemonSetStatus` + `validateUpdatedNumberScheduled` (patch 0027) |
| May 2026 | Third failure, OnDelete 254.74s; cascading consistency retry chain: each write produces a new resource version the informer hasn't synced yet; exponential backoff (5s,10s,20s...72s gaps) pushed total past 180s | `NVIDIA-dev` | run 25251729171 | 180 s → 300 s for `validateDaemonSetStatus` + `validateUpdatedNumberScheduled` (patch 0027 updated) |

---

### 0027 — test/integration/daemonset: raise status poll budgets to 300 s (StaleControllerConsistency catch-up)

**File:** `0027-test-integration-daemonset-raise-status-poll-to-180.patch`  
**Observed in:** Integration Tests — `NVIDIA-dev/test-k8s` only; runner `linux-amd64-cpu32`; seen on commit `a601d275ed95` (run 25151286336) and again in run 25251729171; kubernetes SHA `4de87946765`  
**Failing tests:** `TestOneNodeDaemonLaunchesPod/OnDelete` in `test/integration/daemonset/`  
**Symptom:** Even with 180 s budget, the test still failed after 254.74 s total (OnDelete subtest). The DaemonSet controller creates a cascading consistency retry chain: after the first `StaleControllerConsistencyDaemonSet` check fails (read 12249 < wrote 12349), it requeues with exponential backoff. When the informer catches up, the controller writes again (12500) but immediately fails again. Each retry cycle: 5s → 10s → 20s → 40s → 72s+ gap, totalling over 4 minutes before the controller made a net-forward status update. Error: `daemonset_test.go:488: timed out waiting for the condition`.  
**Fix:** Raise `validateDaemonSetStatus` and `validateUpdatedNumberScheduled` from `120*time.Second` to `300*time.Second`. The 120 s in `validateDaemonSetPodsAndMarkReady` (polling the local informer cache) is unchanged.  
**Upstream status:** No open upstream issue. The `StaleControllerConsistencyDaemonSet` feature was introduced in 1.36 Beta. Local workaround.

---

### 0028 — test/integration/job: raise job status poll budget to 60 s for slow runners

**File:** `0028-test-integration-job-raise-job-status-poll-budget-t.patch`  
**Observed in:** Integration Tests — `dims/test-k8s` only; GitHub-hosted `ubuntu-24.04` (4 vCPU); commit `c92b59d939c4` (run 25197118552); NVIDIA-dev passed the same wave cleanly  
**Failing tests:** `TestBackoffLimitPerIndex_DelayedPodDeletion` in `test/integration/job/`  
**Symptom:** `validateJobsPodsStatusOnly` polls `wait.ForeverTestTimeout` (30 s) for job status to show `{Active: 1, Failed: 1}`. On the 4-vCPU runner under load with many parallel test packages, the job controller did not process the pod failure and create a replacement pod within 30 s. Error: `job_test.go:1006: Waiting for Job Status: context deadline exceeded` / `Found 0 active Pods, want 1`.  
**Fix:** Double the budget in `validateJobsPodsStatusOnly` from `wait.ForeverTestTimeout` to `2*wait.ForeverTestTimeout` (60 s). Passing cases resolve in well under 5 s; the extra headroom only matters under scheduler/controller starvation on constrained runners.  
**Upstream status:** No open upstream issue. Local workaround.

---

### 0029 — test/integration/scheduler: wait for nodes in cache before scheduler restart

**File:** `0029-test-integration-scheduler-wait-for-nodes-in-cache-.patch`
**Observed in:** Integration Tests — `NVIDIA-dev/test-k8s` only; self-hosted `linux-amd64-cpu32` (32 vCPU); first seen in run 25205734755; dims/test-k8s run 25205941993 passed cleanly  
**Failing tests:** `TestSchedulerRestartWithNominatedNode` in `test/integration/scheduler/nominated_node_name/`  
**Symptom:** Two distinct races, both from the scheduler starting before its node cache is warm: (1) After restarting the scheduler (second `initSched()` call), `evaluateNominatedNode` gets `"nodeinfo not found"` and assigns pods to wrong nodes (first seen in run 25205734755). (2) Before the first scheduler start, node scoring runs with stale cache; `node-other` (PreferNoSchedule taint) outscores `node-preferred` causing pod-a's bind to land on the wrong node and NominatedNodeName to be wrong (first seen in run 25257575513).  
**Fix:** Add `testutils.WaitForNodesInCache(ctx, testCtx.Scheduler, 2)` before BOTH the first and second `Scheduler.Run()` call. Updated patch guards both start sites.  
**Upstream status:** Test added upstream in PR #138443 (merged Apr 30 2026). Race is inherent in the test design; fix is the correct guard. Will propose upstream.

---

### 0030 — plugin/pkg/admission/podgroup: use direct client for Workload lookup

**File:** `0030-plugin-pkg-admission-podgroup-use-direct-client-for.patch`
**Observed in:** Integration Tests — `NVIDIA-dev/test-k8s` only; self-hosted `linux-amd64-cpu32` (32 vCPU); first seen in run 25227024633; dims/test-k8s run 25227315480 passed cleanly  
**Failing tests:** `TestPodGroupAdmission/PodGroup_referencing_terminating_Workload_is_rejected` in `test/integration/scheduler/podgroup/admission/`  
**Symptom:** After deleting a Workload (which sets `DeletionTimestamp` but leaves the object due to a finalizer), the admission plugin's informer-backed lister may still return the old object without `DeletionTimestamp`. On the 32-vCPU runner the PodGroup creation test completes so quickly that the lister is stale; the admission plugin passes the PodGroup creation when it should reject. The test expects a Forbidden error but gets success.  
**Fix:** Replace the lister-based Workload lookup in `Validate()` with a direct API call (`p.client.SchedulingV1alpha2().Workloads(...).Get()`), ensuring fresh state. The informer is retained for the `WaitForReady` check. Also update the unit test to populate the fake client (not just the informer store) to match the new code path.  
**Upstream status:** Production bug in `plugin/pkg/admission/podgroup` (KEP-5832, PR #137464). The lister is unsuitable for this check because DeletionTimestamp changes need strong consistency. Will propose upstream fix.

---

### 0031 — test/cmd/apps: wait for statefulset observedGeneration after rollout restart

**File:** `0031-test-wait-statefulset-observedGeneration-after-rollout-restart.patch`
**Observed in:** Cmd Tests — `dims/test-k8s` only; GitHub-hosted `ubuntu-24.04` (4 vCPU); first seen in run 25251718712 (2026-05-02 12:17 UTC); NVIDIA-dev run 25251723817 and all 4 prior dims runs passed cleanly  
**Failing tests:** `run_stateful_set_tests` in `test/cmd/apps.sh` (called via `hack/make-rules/test-cmd.sh`)  
**Symptom:** After `kubectl rollout restart statefulset nginx`, the test immediately calls `kube::test::get_object_assert` (point-in-time check) on `.status.observedGeneration` expecting 3. On the slow 4-vCPU runner the StatefulSet controller had not yet processed the new generation, returning 2. Error: `apps.sh:624: FAIL! Get statefulset nginx {{.status.observedGeneration}} Expected: 3, Got: 2`.  
**Fix:** Change `get_object_assert` to `wait_object_assert` on `apps.sh:624`. This matches lines 611 and 616 which already use `wait_object_assert` for the same field in the same function; the inconsistency was present since the original 2019 commit (145935d8157).  
**Upstream status:** No open upstream issue. Local workaround; will propose upstream.

---

### 0032 — apimachinery/util/proxy: fix data race on UpgradeAwareHandler.Transport

**File:** `0032-apimachinery-util-proxy-fix-data-race-on-UpgradeAwa.patch`
**Observed in:** Unit Tests — `NVIDIA-dev/test-k8s` only; self-hosted `linux-amd64-cpu32` (32 vCPU); first seen in run 25254307641 (2026-05-02 14:37 UTC); dims run 25254315398 passed cleanly  
**Failing tests:** `TestProxyUpgradeErrorResponseTerminates/code=400` in `staging/src/k8s.io/apimachinery/pkg/util/proxy/`  
**Symptom:** Two concurrent HTTP connections served by the same `*UpgradeAwareHandler` instance race on the `Transport` field. Goroutine A writes `h.Transport = h.defaultProxyTransport(...)` (line 237) while Goroutine B reads `h.Transport` for `proxy.Transport =` (line 259). The race detector reports write/read conflict at the same address. A second racy edge: the `corsRemovingTransport.RoundTripper` field written during struct initialisation in goroutine A is read by goroutine B before the pointer store to `h.Transport` is visible.  
**Fix:** Capture `h.Transport` into a local variable `transport` at the top of the `ServeHTTP` hot-path, compute the wrapped value into `transport`, and assign `proxy.Transport = transport`. This eliminates all mutations of the shared `h.Transport` field during request handling while preserving identical semantics: `defaultProxyTransport` is pure and cheap; `WrapTransport` wraps the original field value (not a previously-wrapped result) on every request, which is correct.  
**Upstream status:** Race present since 2017 (commit edc12aafe2f). No upstream issue or fix found. Will propose upstream.

### 0033 — controller/daemon: requeue with fixed delay on ConsistencyError

**File:** `0033-controller-daemon-requeue-with-fixed-delay-on-Consi.patch`
**Observed in:** Integration Tests — `NVIDIA-dev/test-k8s`; self-hosted `linux-amd64-cpu32` (32 vCPU); first seen in run 25258625294 (2026-05-02 18:09 UTC)  
**Failing tests:** `TestOneNodeDaemonLaunchesPod/OnDelete` in `test/integration/daemonset/`  
**Symptom:** When `StaleControllerConsistencyDaemonSet` (Beta) is enabled, `syncDaemonSet` calls `consistencyStore.EnsureReady()` to confirm that written pod resource-versions have been observed by the informer. If the informer lags (common under heavy load on a 32-vCPU runner), `EnsureReady` returns a `ConsistencyError`. The error was returned from `syncDaemonSet` to the workqueue, which applies exponential backoff (5ms × 2^N, max 1000 s). After ~16 consecutive informer-lag misses, the DaemonSet item sits in backoff for 327 s before the next retry — exceeding the 300 s `validateDaemonSetStatus` budget (patch 0027).  
**Fix:** Detect `ConsistencyError` in `syncDaemonSet` before the main `EnsureReady` error return and requeue the key with a fixed 100 ms delay via `dsc.queue.AddAfter`, then return `nil`. A `ConsistencyError` is a transient "not yet observed" condition, not a real failure; returning `nil` prevents the workqueue failure-counter from accumulating, while `AddAfter` ensures the item is retried promptly without busy-looping.  
**Upstream status:** No upstream issue or fix found. Will propose upstream.
