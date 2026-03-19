#!/usr/bin/env python3

import argparse
import json
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote


ALLOWED_EVENTS = {"push", "schedule", "workflow_dispatch"}
SCHEMA_VERSION = 1
RECENT_ATTEMPTS = 10
UPSTREAM_PR_SEARCH_LIMIT = 25
UPSTREAM_TEST_SAMPLE_LIMIT = 20
PROW_VIEW_PREFIX = "https://prow.k8s.io/view/gs/"


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def slugify(value: str) -> str:
    import re

    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-{2,}", "-", value)
    return value.strip("-") or "unknown"


def repo_slug(value: str) -> str:
    return value.replace("/", "__")


def run_cmd(args, cwd=None):
    proc = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(args)}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}")
    return proc.stdout


def read_url_text(url: str):
    return run_cmd(["curl", "-fsSL", url])


def read_url_json(url: str):
    return json.loads(read_url_text(url))


def load_catalog(path: Path):
    payload = read_json(path)
    entries = payload.get("jobs", [])
    by_key = {}
    for entry in entries:
        by_key[(entry["workflow_file"], entry["job_name"])] = entry
    return payload, by_key


def canonical_test_name(test):
    classname = (test.get("classname") or test.get("suite") or "").strip()
    name = (test.get("name") or "").strip()
    if classname and name:
        return f"{classname}::{name}"
    return name or classname


def parse_junit_test_names(xml_text: str):
    root = ET.fromstring(xml_text)
    if root.tag == "testsuite":
        suite_nodes = [root]
    elif root.tag == "testsuites":
        suite_nodes = [node for node in root if node.tag == "testsuite"]
    else:
        suite_nodes = []

    names = set()
    for suite in suite_nodes:
        suite_name = suite.attrib.get("name") or ""
        for testcase in suite.iter("testcase"):
            names.add(
                canonical_test_name(
                    {
                        "classname": testcase.attrib.get("classname") or suite_name,
                        "suite": suite_name,
                        "name": testcase.attrib.get("name") or "",
                    }
                )
            )
    return {name for name in names if name}


def extract_gcs_object_prefix(prow_target_url: str):
    if not prow_target_url.startswith(PROW_VIEW_PREFIX):
        return None
    return prow_target_url[len(PROW_VIEW_PREFIX) :]


def build_gcs_objects_url(bucket: str, prefix: str, page_token: str | None = None):
    url = f"https://storage.googleapis.com/storage/v1/b/{bucket}/o?prefix={quote(prefix, safe='/')}"
    if page_token:
        url += f"&pageToken={quote(page_token, safe='')}"
    return url


def list_gcs_objects(bucket: str, prefix: str):
    items = []
    page_token = None
    while True:
        payload = read_url_json(build_gcs_objects_url(bucket, prefix, page_token))
        items.extend(payload.get("items", []))
        page_token = payload.get("nextPageToken")
        if not page_token:
            break
    return items


def is_junit_artifact_name(name: str):
    base = Path(name).name.lower()
    return base.endswith(".xml") and ("junit" in base or "ginkgo" in name.lower())


def fetch_upstream_test_inventory(reference):
    object_prefix = extract_gcs_object_prefix(reference["target_url"])
    if not object_prefix:
        raise RuntimeError(f"unsupported upstream target url: {reference['target_url']}")

    parts = object_prefix.split("/", 1)
    bucket = parts[0]
    run_prefix = parts[1]
    objects = list_gcs_objects(bucket, f"{run_prefix}/artifacts/")
    junit_objects = [item for item in objects if is_junit_artifact_name(item["name"])]
    if not junit_objects:
        return {
            "reference": reference,
            "tests": set(),
            "junit_files": [],
            "missing_junit": True,
        }

    tests = set()
    parse_errors = []
    for item in junit_objects:
        try:
            tests.update(parse_junit_test_names(read_url_text(item["mediaLink"])))
        except Exception as exc:
            parse_errors.append(f"{item['name']}: {exc}")

    started = {}
    try:
        started = read_url_json(f"https://storage.googleapis.com/{bucket}/{run_prefix}/started.json")
    except Exception:
        started = {}

    return {
        "reference": reference,
        "bucket": bucket,
        "run_prefix": run_prefix,
        "started": started,
        "tests": tests,
        "junit_files": [item["name"] for item in junit_objects],
        "parse_errors": parse_errors,
    }


def discover_upstream_references(mirrored_jobs):
    if not mirrored_jobs:
        return {}

    payload = json.loads(
        run_cmd(
            [
                "gh",
                "pr",
                "list",
                "--repo",
                "kubernetes/kubernetes",
                "--state",
                "all",
                "--search",
                "sort:updated-desc",
                "--limit",
                str(UPSTREAM_PR_SEARCH_LIMIT),
                "--json",
                "number,updatedAt,statusCheckRollup",
            ]
        )
    )

    references = {}
    pending = set(mirrored_jobs)
    for pr in payload:
        contexts = pr.get("statusCheckRollup") or []
        for context in contexts:
            if context.get("__typename") != "StatusContext":
                continue
            name = context.get("context")
            if name not in pending:
                continue
            if context.get("state") != "SUCCESS":
                continue
            target_url = context.get("targetUrl") or ""
            if not target_url.startswith(PROW_VIEW_PREFIX):
                continue
            references[name] = {
                "job_name": name,
                "target_url": target_url,
                "pr_number": pr["number"],
                "pr_updated_at": pr.get("updatedAt"),
                "started_at": context.get("startedAt"),
            }
            pending.discard(name)
        if not pending:
            break
    return references


def discover_local_bundles(root: Path):
    bundles = []
    for metadata_path in root.glob("**/normalized-results/metadata.json"):
        bundle_dir = metadata_path.parent
        bundles.append({"bundle_dir": bundle_dir, "run_info": {}})
    return bundles


def fetch_recent_runs(repo: str, branch: str, limit: int):
    return json.loads(
        run_cmd(
            [
                "gh",
                "run",
                "list",
                "--repo",
                repo,
                "--branch",
                branch,
                "--limit",
                str(limit),
                "--json",
                "databaseId,workflowName,headSha,status,conclusion,event,createdAt,updatedAt,startedAt,url,headBranch,displayTitle",
            ]
        )
    )


def download_result_artifacts(repo: str, run, download_root: Path):
    run_id = run["databaseId"]
    bundles = []
    target_dir = download_root / repo_slug(repo) / str(run_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    try:
        run_cmd(["gh", "run", "download", str(run_id), "--repo", repo, "-D", str(target_dir)])
    except RuntimeError:
        return bundles
    for metadata_path in target_dir.glob("**/normalized-results/metadata.json"):
        bundles.append(
            {
                "bundle_dir": metadata_path.parent,
                "run_info": {
                    "repo": repo,
                    "run_id": run_id,
                    "run_attempt": read_json(metadata_path.parent / "metadata.json").get("run_attempt", 1),
                    "conclusion": run.get("conclusion"),
                    "status": run.get("status"),
                    "html_url": run.get("url"),
                    "created_at": run.get("createdAt"),
                    "updated_at": run.get("updatedAt"),
                    "run_started_at": run.get("startedAt"),
                    "head_sha": run.get("headSha"),
                    "event": run.get("event"),
                    "head_branch": run.get("headBranch"),
                    "display_title": run.get("displayTitle"),
                },
            }
        )
    return bundles


def fetch_remote_bundles(repos, catalog_entries, branch, max_runs):
    bundles = []
    with tempfile.TemporaryDirectory(prefix="publish-grid-data-") as tmp:
        download_root = Path(tmp)
        workflow_names = sorted({entry["workflow_name"] for entry in catalog_entries})
        run_limit = max(100, max_runs * max(1, len(workflow_names)) * 3)
        for repo in repos:
            per_workflow_counts = defaultdict(int)
            for run in fetch_recent_runs(repo, branch, run_limit):
                workflow_name = run.get("workflowName")
                if workflow_name not in workflow_names:
                    continue
                if run.get("event") not in ALLOWED_EVENTS:
                    continue
                if run.get("status") != "completed":
                    continue
                if per_workflow_counts[workflow_name] >= max_runs:
                    continue
                per_workflow_counts[workflow_name] += 1
                bundles.extend(download_result_artifacts(repo, run, download_root))
    return bundles


def load_bundle(bundle_dir: Path):
    return {
        "metadata": read_json(bundle_dir / "metadata.json"),
        "suites": read_json(bundle_dir / "suites.json"),
        "tests": read_json(bundle_dir / "tests.json"),
        "files": read_json(bundle_dir / "files.json"),
        "summary": read_json(bundle_dir / "summary.json"),
        "discovery": read_json(bundle_dir / "discovery.json"),
    }


def enrich_record(bundle, run_info, catalog_by_key):
    metadata = dict(bundle["metadata"])
    key = (metadata.get("workflow_file"), metadata.get("job_name"))
    catalog = catalog_by_key.get(key, {})

    metadata["workflow_slug"] = catalog.get("workflow_slug", metadata.get("workflow_slug", slugify(metadata.get("workflow_name", ""))))
    metadata["job_slug"] = catalog.get("job_slug", metadata.get("job_slug", slugify(metadata.get("job_name", ""))))
    metadata["repo_slug"] = metadata.get("repo_slug", repo_slug(metadata.get("repo", "unknown/unknown")))
    metadata["mirrored_prow_job"] = catalog.get("mirrored_prow_job", metadata.get("mirrored_prow_job"))
    metadata["upstream_testgrid_url"] = catalog.get("upstream_testgrid_url", metadata.get("upstream_testgrid_url"))
    metadata["comparison_required"] = catalog.get("comparison_required", False)
    metadata["display_order"] = catalog.get("display_order", 9999)
    metadata.setdefault("upstream_comparison", {})
    metadata["upstream_comparison"].setdefault(
        "inventory_parity_status",
        "unknown" if metadata.get("comparison_required") else "not-required",
    )

    if run_info:
        metadata["repo"] = run_info.get("repo", metadata.get("repo"))
        metadata["repo_slug"] = repo_slug(metadata.get("repo", "unknown/unknown"))
        metadata["run_id"] = run_info.get("run_id", metadata.get("run_id"))
        metadata["run_attempt"] = run_info.get("run_attempt", metadata.get("run_attempt"))
        metadata["html_url"] = run_info.get("html_url", metadata.get("html_url"))
        metadata["event"] = run_info.get("event", metadata.get("event"))
        metadata["github_sha"] = run_info.get("head_sha", metadata.get("github_sha"))
        metadata["github_ref"] = run_info.get("head_branch", metadata.get("github_ref"))
        metadata["result"] = run_info.get("conclusion", metadata.get("result"))
        metadata["started_at"] = run_info.get("run_started_at", metadata.get("started_at"))
        metadata["completed_at"] = run_info.get("updated_at", metadata.get("completed_at"))
        if run_info.get("run_started_at") and run_info.get("updated_at"):
            start = datetime.fromisoformat(run_info["run_started_at"].replace("Z", "+00:00"))
            finish = datetime.fromisoformat(run_info["updated_at"].replace("Z", "+00:00"))
            metadata["duration_seconds"] = int((finish - start).total_seconds())

    record = {
        "metadata": metadata,
        "summary": bundle["summary"],
        "suites": bundle["suites"],
        "tests": bundle["tests"],
        "files": bundle["files"],
        "discovery": bundle["discovery"],
    }
    return record


def classify_inventory_parity(local_only, upstream_only):
    if not local_only and not upstream_only:
        return "match"
    if upstream_only and not local_only:
        return "missing-local-tests"
    if local_only and not upstream_only:
        return "extra-local-tests"
    return "mismatch"


def apply_upstream_comparison(records):
    mirrored_jobs = sorted(
        {
            record["metadata"].get("mirrored_prow_job")
            for record in records
            if record["metadata"].get("comparison_required") and record["metadata"].get("mirrored_prow_job")
        }
    )
    if not mirrored_jobs:
        return

    try:
        references = discover_upstream_references(mirrored_jobs)
    except Exception as exc:
        for record in records:
            comparison = record["metadata"].setdefault("upstream_comparison", {})
            if record["metadata"].get("comparison_required"):
                comparison["inventory_parity_status"] = "upstream-reference-error"
                comparison["error"] = str(exc)
        return
    inventory_cache = {}
    for record in records:
        metadata = record["metadata"]
        comparison = metadata.setdefault("upstream_comparison", {})
        if not metadata.get("comparison_required"):
            comparison["inventory_parity_status"] = "not-required"
            continue

        mirrored_job = metadata.get("mirrored_prow_job")
        reference = references.get(mirrored_job)
        if not reference:
            comparison["inventory_parity_status"] = "upstream-reference-missing"
            continue

        if mirrored_job not in inventory_cache:
            try:
                inventory_cache[mirrored_job] = fetch_upstream_test_inventory(reference)
            except Exception as exc:
                inventory_cache[mirrored_job] = {"error": str(exc), "reference": reference}

        inventory = inventory_cache[mirrored_job]
        comparison["reference_job_name"] = mirrored_job
        comparison["reference_run_url"] = reference.get("target_url")
        comparison["reference_pr_number"] = reference.get("pr_number")
        comparison["reference_started_at"] = reference.get("started_at")
        comparison["reference_pr_updated_at"] = reference.get("pr_updated_at")

        if "error" in inventory:
            comparison["inventory_parity_status"] = "upstream-fetch-error"
            comparison["error"] = inventory["error"]
            continue
        if inventory.get("missing_junit"):
            comparison["inventory_parity_status"] = "upstream-tests-missing"
            comparison["upstream_test_count"] = 0
            comparison["local_test_count"] = len({canonical_test_name(test) for test in record["tests"] if canonical_test_name(test)})
            continue

        local_tests = {canonical_test_name(test) for test in record["tests"] if canonical_test_name(test)}
        upstream_tests = inventory["tests"]
        if not local_tests:
            comparison["inventory_parity_status"] = "local-tests-missing"
            comparison["upstream_test_count"] = len(upstream_tests)
            comparison["local_test_count"] = 0
            comparison["junit_files"] = inventory.get("junit_files", [])
            continue

        local_only = sorted(local_tests - upstream_tests)
        upstream_only = sorted(upstream_tests - local_tests)
        comparison["inventory_parity_status"] = classify_inventory_parity(local_only, upstream_only)
        comparison["upstream_test_count"] = len(upstream_tests)
        comparison["local_test_count"] = len(local_tests)
        comparison["local_only_count"] = len(local_only)
        comparison["upstream_only_count"] = len(upstream_only)
        comparison["local_only_sample"] = local_only[:UPSTREAM_TEST_SAMPLE_LIMIT]
        comparison["upstream_only_sample"] = upstream_only[:UPSTREAM_TEST_SAMPLE_LIMIT]
        comparison["junit_files"] = inventory.get("junit_files", [])
        if inventory.get("parse_errors"):
            comparison["parse_errors"] = inventory["parse_errors"]
        started = inventory.get("started") or {}
        if started:
            comparison["reference_started_json"] = started


def copy_site_assets(site_dir: Path, output_dir: Path):
    if not site_dir.exists():
        raise FileNotFoundError(f"site directory not found: {site_dir}")
    for child in site_dir.iterdir():
        target = output_dir / child.name
        if child.is_dir():
            shutil.copytree(child, target, dirs_exist_ok=True)
        else:
            shutil.copy2(child, target)
    (output_dir / ".nojekyll").write_text("", encoding="utf-8")


def write_run_files(records, output_dir: Path):
    published_runs = []
    rows = defaultdict(list)
    repos_seen = {}

    for record in records:
        metadata = record["metadata"]
        repo_key = metadata["repo_slug"]
        workflow_slug = metadata["workflow_slug"]
        job_slug = metadata["job_slug"]
        run_id = metadata["run_id"]
        attempt = metadata.get("run_attempt", 1)
        run_path = output_dir / "data" / "runs" / repo_key / workflow_slug / job_slug / str(run_id) / f"attempt-{attempt}.json"
        write_json(run_path, record)
        published_runs.append(
            {
                "repo_slug": repo_key,
                "workflow_slug": workflow_slug,
                "job_slug": job_slug,
                "run_id": run_id,
                "run_attempt": attempt,
                "path": str(run_path.relative_to(output_dir)),
            }
        )
        repos_seen[repo_key] = {"repo": metadata["repo"], "repo_slug": repo_key}
        row_key = (repo_key, workflow_slug, job_slug)
        rows[row_key].append(
            {
                "run_id": run_id,
                "run_attempt": attempt,
                "run_path": str(run_path.relative_to(output_dir)),
                "result": metadata.get("result"),
                "html_url": metadata.get("html_url"),
                "github_sha": metadata.get("github_sha"),
                "kubernetes_sha": metadata.get("kubernetes_sha"),
                "containerd_sha": metadata.get("containerd_sha"),
                "completed_at": metadata.get("completed_at") or metadata.get("collected_at"),
                "started_at": metadata.get("started_at"),
                "duration_seconds": metadata.get("duration_seconds"),
                "failed_tests": record["summary"].get("failed", 0),
                "passed_tests": record["summary"].get("passed", 0),
                "tests": record["summary"].get("tests", 0),
                "upstream_testgrid_url": metadata.get("upstream_testgrid_url"),
                "inventory_parity_status": metadata.get("upstream_comparison", {}).get("inventory_parity_status", "unknown"),
                "upstream_only_count": metadata.get("upstream_comparison", {}).get("upstream_only_count", 0),
                "local_only_count": metadata.get("upstream_comparison", {}).get("local_only_count", 0),
                "reference_run_url": metadata.get("upstream_comparison", {}).get("reference_run_url"),
            }
        )

    summary_rows = []
    for row_key, attempts in sorted(rows.items()):
        attempts.sort(key=lambda item: (item.get("completed_at") or "", item["run_id"], item["run_attempt"]), reverse=True)
        repo_key, workflow_slug, job_slug = row_key
        latest = attempts[0]
        record = next(
            rec for rec in records
            if rec["metadata"]["repo_slug"] == repo_key
            and rec["metadata"]["workflow_slug"] == workflow_slug
            and rec["metadata"]["job_slug"] == job_slug
        )
        metadata = record["metadata"]
        row_payload = {
            "repo": metadata["repo"],
            "repo_slug": repo_key,
            "workflow_name": metadata["workflow_name"],
            "workflow_slug": workflow_slug,
            "job_name": metadata["job_name"],
            "job_slug": job_slug,
            "display_order": metadata.get("display_order", 9999),
            "mirrored_prow_job": metadata.get("mirrored_prow_job"),
            "upstream_testgrid_url": metadata.get("upstream_testgrid_url"),
            "comparison_required": metadata.get("comparison_required", False),
            "recent_attempts": attempts[:RECENT_ATTEMPTS],
            "latest_result": latest["result"],
            "inventory_parity_status": metadata.get("upstream_comparison", {}).get("inventory_parity_status", "unknown"),
            "upstream_only_count": metadata.get("upstream_comparison", {}).get("upstream_only_count", 0),
            "local_only_count": metadata.get("upstream_comparison", {}).get("local_only_count", 0),
            "reference_run_url": metadata.get("upstream_comparison", {}).get("reference_run_url"),
        }
        summary_rows.append(row_payload)
        history_payload = dict(row_payload)
        history_payload["attempts"] = attempts
        history_payload["latest_run_path"] = latest["run_path"]
        history_path = output_dir / "data" / "index" / "job-history" / f"{repo_key}__{workflow_slug}__{job_slug}.json"
        write_json(history_path, history_payload)

    summary_rows.sort(key=lambda row: (row["display_order"], row["repo_slug"], row["job_slug"]))
    write_json(output_dir / "data" / "published-runs.json", {"generated_at": utc_now(), "runs": published_runs})
    write_json(output_dir / "data" / "repos.json", {"generated_at": utc_now(), "repos": list(repos_seen.values())})
    write_json(output_dir / "data" / "index" / "summary.json", {"generated_at": utc_now(), "rows": summary_rows})
    return summary_rows


def write_catalog_views(catalog_payload, output_dir: Path):
    write_json(output_dir / "data" / "schema-version.json", {"schema_version": SCHEMA_VERSION, "generated_at": utc_now()})
    write_json(output_dir / "data" / "jobs.json", catalog_payload)


def collect_records(args, catalog_entries, catalog_by_key):
    if args.input_root:
        bundles = discover_local_bundles(Path(args.input_root))
    else:
        bundles = fetch_remote_bundles(args.repo, catalog_entries, args.branch, args.max_runs_per_workflow)

    records = []
    for item in bundles:
        bundle = load_bundle(item["bundle_dir"])
        records.append(enrich_record(bundle, item["run_info"], catalog_by_key))
    if not args.skip_upstream_comparison:
        apply_upstream_comparison(records)
    return records


def build_site(output_dir: Path, site_dir: Path, catalog_payload, records):
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    copy_site_assets(site_dir, output_dir)
    write_catalog_views(catalog_payload, output_dir)
    write_run_files(records, output_dir)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", default="scripts/testgrid_workflow_catalog.json")
    parser.add_argument("--site-dir", default="site")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--input-root")
    parser.add_argument("--repo", action="append", default=[])
    parser.add_argument("--branch", default="main")
    parser.add_argument("--max-runs-per-workflow", type=int, default=20)
    parser.add_argument("--skip-upstream-comparison", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    catalog_path = Path(args.catalog)
    site_dir = Path(args.site_dir)
    output_dir = Path(args.output_dir)
    catalog_payload, catalog_by_key = load_catalog(catalog_path)
    catalog_entries = catalog_payload.get("jobs", [])
    if not args.input_root and not args.repo:
        raise SystemExit("either --input-root or at least one --repo is required")
    records = collect_records(args, catalog_entries, catalog_by_key)
    build_site(output_dir, site_dir, catalog_payload, records)


if __name__ == "__main__":
    main()
