async function loadJson(path) {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`failed to fetch ${path}: ${response.status}`);
  }
  return response.json();
}

function qs(selector) {
  return document.querySelector(selector);
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) {
    node.className = className;
  }
  if (text !== undefined) {
    node.textContent = text;
  }
  return node;
}

function routeParams() {
  return new URLSearchParams(window.location.search);
}

function setRoute(params) {
  const query = new URLSearchParams(params);
  const next = query.toString() ? `?${query.toString()}` : window.location.pathname;
  window.history.pushState({}, "", next);
  renderApp().catch(renderFatalError);
}

function routeLink(params, label) {
  const link = el("a", "route-link", label);
  link.href = `?${new URLSearchParams(params).toString()}`;
  link.addEventListener("click", (event) => {
    event.preventDefault();
    setRoute(params);
  });
  return link;
}

function jobHistoryPath(repoSlug, workflowSlug, jobSlug) {
  return `./data/index/job-history/${repoSlug}__${workflowSlug}__${jobSlug}.json`;
}

function runDataPath(repoSlug, workflowSlug, jobSlug, runId, attempt) {
  return `./data/runs/${repoSlug}/${workflowSlug}/${jobSlug}/${runId}/attempt-${attempt}.json`;
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

function formatAttempt(attempt) {
  return `#${attempt.run_id}.${attempt.run_attempt}`;
}

function formatDuration(seconds) {
  if (seconds === null || seconds === undefined) {
    return "unknown";
  }
  if (seconds < 1) {
    return `${seconds.toFixed(3)}s`;
  }
  if (seconds < 60) {
    return `${seconds}s`;
  }
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return `${minutes}m ${remainder}s`;
}

function formatSha(sha) {
  return sha ? sha.slice(0, 12) : "unknown";
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

function formatAttemptTooltip(attempt) {
  return [
    `Result: ${attempt.result || "unknown"}`,
    `Kubernetes: ${attempt.kubernetes_sha || "unknown"}`,
    `containerd: ${attempt.containerd_sha || "unknown"}`,
    `Tests: ${attempt.tests}`,
    `Failed tests: ${attempt.failed_tests}`,
    `Parity: ${attempt.inventory_parity_status || "unknown"}`,
    `Local-only tests: ${attempt.local_only_count ?? 0}`,
    `Upstream-only tests: ${attempt.upstream_only_count ?? 0}`,
    `Duration: ${formatDuration(attempt.duration_seconds)}`,
    `Completed: ${attempt.completed_at || "unknown"}`
  ].join("\n");
}

function renderBreadcrumbs(items) {
  const container = qs("#breadcrumbs");
  container.replaceChildren();
  items.forEach((item, index) => {
    if (index > 0) {
      container.appendChild(el("span", "breadcrumb-separator", "/"));
    }
    if (item.params) {
      container.appendChild(routeLink(item.params, item.label));
    } else {
      container.appendChild(el("span", "breadcrumb-current", item.label));
    }
  });
}

function statCard(label, value) {
  const card = el("div", "stat-card");
  card.appendChild(el("div", "stat-label", label));
  card.appendChild(el("div", "stat-value", value));
  return card;
}

function buildAttemptsCell(attempts) {
  const cell = el("td", "attempts");
  const template = qs("#attempt-template");
  for (const attempt of attempts) {
    const chip = template.content.firstElementChild.cloneNode(true);
    chip.className = chipClass(attempt.result);
    chip.href = attempt.html_url || "#";
    chip.textContent = formatAttempt(attempt);
    chip.title = formatAttemptTooltip(attempt);
    cell.appendChild(chip);
  }
  return cell;
}

function buildCompareCell(row) {
  const cell = el("td", "compare-cell");
  if (!row.upstream_testgrid_url) {
    cell.appendChild(el("span", "compare-link muted", "local"));
    return cell;
  }

  const label = "compare";
  const compare = el("a", "compare-link", label);
  compare.href = row.upstream_testgrid_url;
  compare.target = "_blank";
  compare.rel = "noreferrer";
  compare.title = row.mirrored_prow_job || "Open upstream TestGrid lane";
  cell.appendChild(compare);
  return cell;
}

function renderSummaryTable(summary) {
  const section = el("section", "grid-card");
  const table = el("table");
  const thead = el("thead");
  const headerRow = el("tr");
  ["Workflow", "Repo", "Compare", "Parity", "Recent Attempts"].forEach((label) => headerRow.appendChild(el("th", "", label)));
  thead.appendChild(headerRow);
  table.appendChild(thead);

  const tbody = el("tbody");
  for (const row of summary.rows) {
    const tr = el("tr");

    const workflowCell = el("td");
    const link = routeLink(
      { view: "job", repo: row.repo_slug, workflow: row.workflow_slug, job: row.job_slug },
      row.job_name
    );
    workflowCell.appendChild(link);
    workflowCell.appendChild(el("div", "subtle", row.workflow_name));
    tr.appendChild(workflowCell);

    tr.appendChild(el("td", "", row.repo));
    tr.appendChild(buildCompareCell(row));

    const parityCell = el("td");
    const parity = el(row.reference_run_url ? "a" : "span", parityClass(row.inventory_parity_status), formatParity(row));
    if (row.reference_run_url) {
      parity.href = row.reference_run_url;
      parity.target = "_blank";
      parity.rel = "noreferrer";
    }
    parityCell.appendChild(parity);
    tr.appendChild(parityCell);

    tr.appendChild(buildAttemptsCell(row.recent_attempts));
    tbody.appendChild(tr);
  }

  table.appendChild(tbody);
  section.appendChild(table);
  return section;
}

function renderAttemptTable(history) {
  const section = el("section", "grid-card");
  section.appendChild(el("h2", "section-title", "Attempt History"));

  const table = el("table");
  const thead = el("thead");
  const row = el("tr");
  ["Attempt", "Result", "Completed", "Duration", "Tests", "Parity", "Revisions"].forEach((label) => row.appendChild(el("th", "", label)));
  thead.appendChild(row);
  table.appendChild(thead);

  const tbody = el("tbody");
  for (const attempt of history.attempts || history.recent_attempts || []) {
    const tr = el("tr");

    const attemptCell = el("td");
    attemptCell.appendChild(
      routeLink(
        {
          view: "run",
          repo: history.repo_slug,
          workflow: history.workflow_slug,
          job: history.job_slug,
          run: String(attempt.run_id),
          attempt: String(attempt.run_attempt),
        },
        formatAttempt(attempt)
      )
    );
    tr.appendChild(attemptCell);

    const resultCell = el("td");
    resultCell.appendChild(el("span", chipClass(attempt.result), attempt.result || "unknown"));
    tr.appendChild(resultCell);

    tr.appendChild(el("td", "", attempt.completed_at || "unknown"));
    tr.appendChild(el("td", "", formatDuration(attempt.duration_seconds)));
    tr.appendChild(el("td", "", `${attempt.tests} total / ${attempt.failed_tests} failed`));

    const parityCell = el("td");
    const parity = el(attempt.reference_run_url ? "a" : "span", parityClass(attempt.inventory_parity_status), formatParity(attempt));
    if (attempt.reference_run_url) {
      parity.href = attempt.reference_run_url;
      parity.target = "_blank";
      parity.rel = "noreferrer";
    }
    parityCell.appendChild(parity);
    tr.appendChild(parityCell);

    const revisions = el("td");
    revisions.appendChild(el("div", "", `k8s ${formatSha(attempt.kubernetes_sha)}`));
    revisions.appendChild(el("div", "subtle", `containerd ${formatSha(attempt.containerd_sha)}`));
    tr.appendChild(revisions);

    tbody.appendChild(tr);
  }

  table.appendChild(tbody);
  section.appendChild(table);
  return section;
}

function renderComparisonCard(comparison) {
  const section = el("section", "detail-card");
  section.appendChild(el("h2", "section-title", "Upstream Comparison"));

  const statusLine = el("div", "pill-row");
  statusLine.appendChild(el("span", parityClass(comparison.inventory_parity_status), comparison.inventory_parity_status || "unknown"));
  if (comparison.reference_run_url) {
    const link = el("a", "reference-link", "reference run");
    link.href = comparison.reference_run_url;
    link.target = "_blank";
    link.rel = "noreferrer";
    statusLine.appendChild(link);
  }
  section.appendChild(statusLine);

  const stats = el("div", "stats-grid");
  stats.appendChild(statCard("Local tests", String(comparison.local_test_count ?? 0)));
  stats.appendChild(statCard("Upstream tests", String(comparison.upstream_test_count ?? 0)));
  stats.appendChild(statCard("Local-only", String(comparison.local_only_count ?? 0)));
  stats.appendChild(statCard("Upstream-only", String(comparison.upstream_only_count ?? 0)));
  section.appendChild(stats);

  if (comparison.error) {
    section.appendChild(el("pre", "failure-block", comparison.error));
  }

  if ((comparison.local_only_sample || []).length) {
    section.appendChild(el("h3", "subsection-title", "Local-only sample"));
    const list = el("ul", "sample-list");
    for (const item of comparison.local_only_sample) {
      list.appendChild(el("li", "", item));
    }
    section.appendChild(list);
  }

  if ((comparison.upstream_only_sample || []).length) {
    section.appendChild(el("h3", "subsection-title", "Upstream-only sample"));
    const list = el("ul", "sample-list");
    for (const item of comparison.upstream_only_sample) {
      list.appendChild(el("li", "", item));
    }
    section.appendChild(list);
  }

  return section;
}

function renderRunMetadata(record) {
  const meta = record.metadata;
  const section = el("section", "detail-card");
  section.appendChild(el("h2", "section-title", "Run Summary"));

  const stats = el("div", "stats-grid");
  stats.appendChild(statCard("Result", meta.result || "unknown"));
  stats.appendChild(statCard("Tests", String(record.summary.tests)));
  stats.appendChild(statCard("Failed", String(record.summary.failed)));
  stats.appendChild(statCard("Duration", formatDuration(meta.duration_seconds ?? record.summary.duration_seconds)));
  stats.appendChild(statCard("Kubernetes", formatSha(meta.kubernetes_sha)));
  stats.appendChild(statCard("containerd", formatSha(meta.containerd_sha)));
  section.appendChild(stats);

  const list = el("div", "meta-list");
  const fields = [
    ["Repo", meta.repo],
    ["Workflow", meta.workflow_name],
    ["Job", meta.job_name],
    ["Run", `${meta.run_id}.${meta.run_attempt}`],
    ["GitHub SHA", meta.github_sha],
    ["Build log", meta.artifacts?.build_log || "none"],
    ["Result source", meta.data_quality?.result_source || "unknown"],
    ["Completed", meta.completed_at || meta.collected_at || "unknown"],
  ];
  for (const [label, value] of fields) {
    const row = el("div", "meta-row");
    row.appendChild(el("div", "meta-label", label));
    row.appendChild(el("div", "meta-value", value || "unknown"));
    list.appendChild(row);
  }
  section.appendChild(list);

  return section;
}

function renderSuites(record) {
  const section = el("section", "grid-card");
  section.appendChild(el("h2", "section-title", "Suites"));

  const table = el("table");
  const thead = el("thead");
  const headerRow = el("tr");
  ["Suite", "Source", "Tests", "Failed", "Duration"].forEach((label) => headerRow.appendChild(el("th", "", label)));
  thead.appendChild(headerRow);
  table.appendChild(thead);

  const tbody = el("tbody");
  for (const suite of record.suites) {
    const tr = el("tr");
    tr.appendChild(el("td", "", suite.suite));
    tr.appendChild(el("td", "", suite.source));
    tr.appendChild(el("td", "", String(suite.tests)));
    tr.appendChild(el("td", "", String(suite.failed)));
    tr.appendChild(el("td", "", formatDuration(suite.duration_seconds)));
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  section.appendChild(table);
  return section;
}

function renderTests(record) {
  const section = el("section", "grid-card");
  section.appendChild(el("h2", "section-title", "Tests"));

  const table = el("table");
  const thead = el("thead");
  const headerRow = el("tr");
  ["Status", "Duration", "Suite", "Class", "Name", "Failure"].forEach((label) => headerRow.appendChild(el("th", "", label)));
  thead.appendChild(headerRow);
  table.appendChild(thead);

  const tbody = el("tbody");
  for (const test of record.tests) {
    const tr = el("tr");
    const status = el("td");
    status.appendChild(el("span", chipClass(test.status === "passed" ? "success" : test.status), test.status));
    tr.appendChild(status);
    tr.appendChild(el("td", "", formatDuration(test.duration_seconds)));
    tr.appendChild(el("td", "", test.suite || ""));
    tr.appendChild(el("td", "subtle", test.classname || ""));
    tr.appendChild(el("td", "", test.name || ""));
    const failure = el("td");
    if (test.failure_text) {
      failure.appendChild(el("pre", "failure-block inline", test.failure_text));
    } else {
      failure.textContent = "";
    }
    tr.appendChild(failure);
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  section.appendChild(table);
  return section;
}

async function renderSummaryView() {
  const [summary, repos] = await Promise.all([
    loadJson("./data/index/summary.json"),
    loadJson("./data/repos.json"),
  ]);
  qs("#summary-meta").textContent = `Generated ${summary.generated_at}. Repos: ${repos.repos.map((repo) => repo.repo).join(", ")}`;
  renderBreadcrumbs([{ label: "Summary" }]);

  const content = qs("#content");
  content.replaceChildren();

  const stats = el("section", "detail-card");
  stats.appendChild(el("h2", "section-title", "Overview"));
  const statsGrid = el("div", "stats-grid");
  statsGrid.appendChild(statCard("Jobs", String(summary.rows.length)));
  statsGrid.appendChild(statCard("Repos", String(repos.repos.length)));
  statsGrid.appendChild(statCard("Rows with parity", String(summary.rows.filter((row) => row.comparison_required).length)));
  statsGrid.appendChild(statCard("Rows at match", String(summary.rows.filter((row) => row.inventory_parity_status === "match").length)));
  stats.appendChild(statsGrid);
  content.appendChild(stats);

  content.appendChild(renderSummaryTable(summary));
}

async function renderJobView(params) {
  const history = await loadJson(jobHistoryPath(params.get("repo"), params.get("workflow"), params.get("job")));
  qs("#summary-meta").textContent = `${history.repo} / ${history.job_name}`;
  renderBreadcrumbs([
    { label: "Summary", params: {} },
    { label: history.job_name },
  ]);

  const content = qs("#content");
  content.replaceChildren();

  const overview = el("section", "detail-card");
  overview.appendChild(el("h2", "section-title", "Job Overview"));
  const stats = el("div", "stats-grid");
  stats.appendChild(statCard("Repo", history.repo));
  stats.appendChild(statCard("Workflow", history.workflow_name));
  stats.appendChild(statCard("Attempts", String((history.attempts || []).length)));
  stats.appendChild(statCard("Latest", history.latest_result || "unknown"));
  overview.appendChild(stats);
  content.appendChild(overview);

  if (history.comparison_required) {
    content.appendChild(
      renderComparisonCard({
        inventory_parity_status: history.inventory_parity_status,
        local_only_count: history.local_only_count,
        upstream_only_count: history.upstream_only_count,
        reference_run_url: history.reference_run_url,
      })
    );
  }

  content.appendChild(renderAttemptTable(history));
}

async function renderRunView(params) {
  const record = await loadJson(
    runDataPath(
      params.get("repo"),
      params.get("workflow"),
      params.get("job"),
      params.get("run"),
      params.get("attempt")
    )
  );
  const meta = record.metadata;
  qs("#summary-meta").textContent = `${meta.repo} / ${meta.job_name} / #${meta.run_id}.${meta.run_attempt}`;
  renderBreadcrumbs([
    { label: "Summary", params: {} },
    {
      label: meta.job_name,
      params: { view: "job", repo: meta.repo_slug, workflow: meta.workflow_slug, job: meta.job_slug },
    },
    { label: `#${meta.run_id}.${meta.run_attempt}` },
  ]);

  const content = qs("#content");
  content.replaceChildren();
  content.appendChild(renderRunMetadata(record));
  content.appendChild(renderSuites(record));
  content.appendChild(renderTests(record));

  if (meta.upstream_comparison) {
    content.appendChild(renderComparisonCard(meta.upstream_comparison));
  }
}

function renderFatalError(error) {
  qs("#summary-meta").textContent = `Failed to load dashboard: ${error.message}`;
  renderBreadcrumbs([{ label: "Error" }]);
  const content = qs("#content");
  content.replaceChildren();
  content.appendChild(el("pre", "failure-block", error.stack || error.message));
}

async function renderApp() {
  const params = routeParams();
  const view = params.get("view") || "summary";
  if (view === "summary") {
    return renderSummaryView();
  }
  if (view === "job") {
    return renderJobView(params);
  }
  if (view === "run") {
    return renderRunView(params);
  }
  throw new Error(`unsupported view: ${view}`);
}

window.addEventListener("popstate", () => {
  renderApp().catch(renderFatalError);
});

renderApp().catch(renderFatalError);
