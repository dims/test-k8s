#!/usr/bin/env python3

import argparse
import json
import shutil
import subprocess
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


ALLOWED_EVENTS = {"push", "schedule", "workflow_dispatch"}
SCHEMA_VERSION = 1
RECENT_ATTEMPTS = 10


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


def load_catalog(path: Path):
    payload = read_json(path)
    entries = payload.get("jobs", [])
    by_key = {}
    for entry in entries:
        by_key[(entry["workflow_file"], entry["job_name"])] = entry
    return payload, by_key


def discover_local_bundles(root: Path):
    bundles = []
    for metadata_path in root.glob("**/normalized-results/metadata.json"):
        bundle_dir = metadata_path.parent
        bundles.append({"bundle_dir": bundle_dir, "run_info": {}})
    return bundles


def fetch_runs_for_workflow(repo: str, workflow_file: str, branch: str, max_runs: int):
    workflow_ref = Path(workflow_file).name
    page = 1
    runs = []
    while len(runs) < max_runs:
        output = run_cmd(
            [
                "gh",
                "api",
                f"repos/{repo}/actions/workflows/{workflow_ref}/runs",
                "-f",
                f"branch={branch}",
                "-f",
                "per_page=100",
                "-f",
                f"page={page}",
            ]
        )
        payload = json.loads(output)
        batch = payload.get("workflow_runs", [])
        if not batch:
            break
        for run in batch:
            if run.get("event") not in ALLOWED_EVENTS:
                continue
            if run.get("status") != "completed":
                continue
            runs.append(run)
            if len(runs) >= max_runs:
                break
        if len(batch) < 100:
            break
        page += 1
    return runs[:max_runs]


def fetch_artifacts_for_run(repo: str, run_id: int):
    output = run_cmd(["gh", "api", f"repos/{repo}/actions/runs/{run_id}/artifacts"])
    payload = json.loads(output)
    return payload.get("artifacts", [])


def download_result_artifacts(repo: str, run, download_root: Path):
    artifacts = fetch_artifacts_for_run(repo, run["id"])
    result_names = [artifact["name"] for artifact in artifacts if artifact["name"].endswith("-results") and not artifact.get("expired")]
    bundles = []
    for artifact_name in result_names:
        target_dir = download_root / repo_slug(repo) / str(run["id"]) / f"attempt-{run.get('run_attempt', 1)}" / artifact_name
        target_dir.mkdir(parents=True, exist_ok=True)
        run_cmd(["gh", "run", "download", str(run["id"]), "--repo", repo, "-n", artifact_name, "-D", str(target_dir)])
        for metadata_path in target_dir.glob("**/normalized-results/metadata.json"):
            bundles.append(
                {
                    "bundle_dir": metadata_path.parent,
                    "run_info": {
                        "repo": repo,
                        "run_id": run["id"],
                        "run_attempt": run.get("run_attempt", 1),
                        "conclusion": run.get("conclusion"),
                        "status": run.get("status"),
                        "html_url": run.get("html_url"),
                        "created_at": run.get("created_at"),
                        "updated_at": run.get("updated_at"),
                        "run_started_at": run.get("run_started_at"),
                        "head_sha": run.get("head_sha"),
                        "event": run.get("event"),
                        "head_branch": run.get("head_branch"),
                        "display_title": run.get("display_title"),
                    },
                }
            )
    return bundles


def fetch_remote_bundles(repos, catalog_entries, branch, max_runs):
    bundles = []
    with tempfile.TemporaryDirectory(prefix="publish-grid-data-") as tmp:
        download_root = Path(tmp)
        workflows = sorted({entry["workflow_file"] for entry in catalog_entries})
        for repo in repos:
            for workflow_file in workflows:
                runs = fetch_runs_for_workflow(repo, workflow_file, branch, max_runs)
                for run in runs:
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
        }
        summary_rows.append(row_payload)
        history_path = output_dir / "data" / "index" / "job-history" / f"{repo_key}__{workflow_slug}__{job_slug}.json"
        write_json(history_path, row_payload)

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
