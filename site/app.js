async function loadJson(path) {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`failed to fetch ${path}: ${response.status}`);
  }
  return response.json();
}

function chipClass(result) {
  switch ((result || "").toLowerCase()) {
    case "success":
      return "attempt-chip success";
    case "failure":
      return "attempt-chip failure";
    case "cancelled":
      return "attempt-chip cancelled";
    case "skipped":
      return "attempt-chip skipped";
    default:
      return "attempt-chip unknown";
  }
}

function parityClass(status) {
  switch (status) {
    case "match":
      return "parity-pill match";
    case "not-required":
      return "parity-pill not-required";
    case "upstream-reference-missing":
    case "upstream-reference-error":
    case "upstream-fetch-error":
    case "upstream-tests-missing":
    case "local-tests-missing":
      return "parity-pill warning";
    default:
      return "parity-pill mismatch";
  }
}

function formatParity(row) {
  const status = row.inventory_parity_status || "unknown";
  if (status === "match") {
    return "match";
  }
  if (status === "not-required") {
    return "n/a";
  }
  if (status === "upstream-reference-missing") {
    return "no upstream";
  }
  if (status === "upstream-reference-error") {
    return "reference error";
  }
  if (status === "upstream-fetch-error") {
    return "fetch error";
  }
  if (status === "upstream-tests-missing") {
    return "no upstream junit";
  }
  if (status === "local-tests-missing") {
    return "no local tests";
  }
  const extra = row.local_only_count ?? 0;
  const missing = row.upstream_only_count ?? 0;
  return `extra ${extra} / missing ${missing}`;
}

function formatAttempt(attempt) {
  return `#${attempt.run_id}.${attempt.run_attempt}`;
}

function formatTooltip(attempt) {
  return [
    `Result: ${attempt.result || "unknown"}`,
    `Kubernetes: ${attempt.kubernetes_sha || "unknown"}`,
    `containerd: ${attempt.containerd_sha || "unknown"}`,
    `Failed tests: ${attempt.failed_tests}`,
    `Parity: ${attempt.inventory_parity_status || "unknown"}`,
    `Local-only tests: ${attempt.local_only_count ?? 0}`,
    `Upstream-only tests: ${attempt.upstream_only_count ?? 0}`,
    `Duration: ${attempt.duration_seconds ?? "unknown"}s`,
    `Completed: ${attempt.completed_at || "unknown"}`
  ].join("\n");
}

async function renderSummary() {
  const [summary, repos] = await Promise.all([
    loadJson("./data/index/summary.json"),
    loadJson("./data/repos.json")
  ]);

  const body = document.getElementById("summary-body");
  const meta = document.getElementById("summary-meta");
  const template = document.getElementById("attempt-template");

  meta.textContent = `Generated ${summary.generated_at}. Repos: ${repos.repos.map((repo) => repo.repo).join(", ")}`;

  for (const row of summary.rows) {
    const tr = document.createElement("tr");

    const workflowCell = document.createElement("td");
    workflowCell.innerHTML = `<strong>${row.job_name}</strong><div class="subtle">${row.workflow_name}</div>`;
    tr.appendChild(workflowCell);

    const repoCell = document.createElement("td");
    repoCell.textContent = row.repo;
    tr.appendChild(repoCell);

    const upstreamCell = document.createElement("td");
    if (row.upstream_testgrid_url) {
      const link = document.createElement("a");
      link.href = row.upstream_testgrid_url;
      link.textContent = row.mirrored_prow_job || "TestGrid";
      link.target = "_blank";
      link.rel = "noreferrer";
      upstreamCell.appendChild(link);
    } else {
      upstreamCell.textContent = "repo-local";
    }
    tr.appendChild(upstreamCell);

    const parityCell = document.createElement("td");
    const parity = document.createElement(row.reference_run_url ? "a" : "span");
    parity.className = parityClass(row.inventory_parity_status);
    parity.textContent = formatParity(row);
    if (row.reference_run_url) {
      parity.href = row.reference_run_url;
      parity.target = "_blank";
      parity.rel = "noreferrer";
    }
    parityCell.appendChild(parity);
    tr.appendChild(parityCell);

    const attemptsCell = document.createElement("td");
    attemptsCell.className = "attempts";
    for (const attempt of row.recent_attempts) {
      const chip = template.content.firstElementChild.cloneNode(true);
      chip.className = chipClass(attempt.result);
      chip.href = attempt.html_url || "#";
      chip.textContent = formatAttempt(attempt);
      chip.title = formatTooltip(attempt);
      attemptsCell.appendChild(chip);
    }
    tr.appendChild(attemptsCell);

    body.appendChild(tr);
  }
}

renderSummary().catch((error) => {
  const meta = document.getElementById("summary-meta");
  meta.textContent = `Failed to load summary: ${error.message}`;
});
