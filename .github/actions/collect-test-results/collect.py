#!/usr/bin/env python3

import json
import os
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import xml.etree.ElementTree as ET


EXCLUDE_PARTS = {"vendor", "third_party", "_output", "testdata"}
KNOWN_BUILD_LOGS = ("build-log.txt", "integration.log", "e2e.log")


def getenv(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-{2,}", "-", value)
    return value.strip("-") or "unknown"


def repo_slug(value: str) -> str:
    return value.replace("/", "__")


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def is_excluded(path: Path) -> bool:
    return any(part in EXCLUDE_PARTS for part in path.parts)


def read_json(path: Path):
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def relative_to(base: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(base.resolve()))
    except ValueError:
        return str(path.resolve())


def discover_junit_files(search_roots):
    found = []
    seen = set()
    for root in search_roots:
        if not root.exists():
            continue
        for pattern in ("junit*.xml", "**/junit*.xml", "**/ginkgo/*.xml"):
            for candidate in root.glob(pattern):
                if not candidate.is_file() or is_excluded(candidate):
                    continue
                resolved = candidate.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                found.append(candidate)
    return sorted(found, key=lambda p: str(p))


def discover_build_logs(search_roots, explicit_path: str):
    found = []
    seen = set()
    if explicit_path:
        candidate = Path(explicit_path)
        if candidate.exists():
            found.append(candidate)
            seen.add(candidate.resolve())

    for root in search_roots:
        if not root.exists():
            continue
        for name in KNOWN_BUILD_LOGS:
            for candidate in root.glob(f"**/{name}"):
                if not candidate.is_file() or is_excluded(candidate):
                    continue
                resolved = candidate.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                found.append(candidate)
    return sorted(found, key=lambda p: str(p))


def normalize_case_status(raw_status: str) -> str:
    value = raw_status.strip().lower()
    if value in {"success", "passed", "pass"}:
        return "passed"
    if value in {"failure", "failed", "fail"}:
        return "failed"
    if value in {"skipped", "skip"}:
        return "skipped"
    if value in {"cancelled", "canceled"}:
        return "cancelled"
    if value in {"neutral", "unknown", ""}:
        return "unknown"
    return value


def normalize_job_status(raw_status: str) -> str:
    value = raw_status.strip().lower()
    if value in {"success", "failure", "cancelled", "skipped"}:
        return value
    if value in {"cancelled", "canceled"}:
        return "cancelled"
    if value in {"passed", "pass"}:
        return "success"
    if value in {"failed", "fail"}:
        return "failure"
    return value or "unknown"


def suite_slug(name: str, fallback: str) -> str:
    return slugify(name) or slugify(fallback)


def parse_junit_file(path: Path, artifacts_dir: Path):
    root = ET.parse(path).getroot()
    suites = []
    tests = []

    if root.tag == "testsuite":
        suite_nodes = [root]
    elif root.tag == "testsuites":
        suite_nodes = [node for node in root if node.tag == "testsuite"]
    else:
        suite_nodes = []

    for index, suite in enumerate(suite_nodes, start=1):
        suite_name = suite.attrib.get("name") or path.stem or f"suite-{index}"
        current_suite_slug = suite_slug(suite_name, f"{path.stem}-{index}")
        suite_tests = 0
        suite_counter = Counter()
        suite_duration = 0.0

        for case_index, testcase in enumerate(suite.iter("testcase"), start=1):
            suite_tests += 1
            case_name = testcase.attrib.get("name") or f"case-{case_index}"
            class_name = testcase.attrib.get("classname") or suite_name
            duration = float(testcase.attrib.get("time", "0") or 0.0)
            suite_duration += duration

            status = "passed"
            failure_text = ""
            if testcase.find("failure") is not None:
                status = "failed"
                failure_text = "".join(testcase.find("failure").itertext()).strip()
            elif testcase.find("error") is not None:
                status = "failed"
                failure_text = "".join(testcase.find("error").itertext()).strip()
            elif testcase.find("skipped") is not None:
                status = "skipped"
                failure_text = "".join(testcase.find("skipped").itertext()).strip()

            suite_counter[status] += 1
            tests.append(
                {
                    "suite": suite_name,
                    "suite_slug": current_suite_slug,
                    "classname": class_name,
                    "name": case_name,
                    "name_slug": slugify(case_name),
                    "status": status,
                    "duration_seconds": duration,
                    "failure_text": failure_text[:4000],
                    "owner_hint": slugify(class_name.split("/")[0]) if "/" in class_name else slugify(class_name),
                    "source": "junit",
                    "file_source": relative_to(artifacts_dir, path),
                }
            )

        suites.append(
            {
                "suite": suite_name,
                "suite_slug": current_suite_slug,
                "tests": suite_tests,
                "passed": suite_counter["passed"],
                "failed": suite_counter["failed"],
                "skipped": suite_counter["skipped"],
                "cancelled": suite_counter["cancelled"],
                "unknown": suite_counter["unknown"],
                "duration_seconds": suite_duration,
                "source": "junit",
                "file_source": relative_to(artifacts_dir, path),
            }
        )

    return suites, tests


def parse_synthetic_cases(raw_cases: str, suite_name: str, default_status: str):
    suite_name = suite_name or "synthetic"
    suite_key = slugify(suite_name)
    tests = []
    counter = Counter()
    total_duration = 0.0

    for line_number, line in enumerate(raw_cases.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split("|", 3)]
        case_name = parts[0]
        case_status = normalize_case_status(parts[1] if len(parts) > 1 and parts[1] else default_status)
        duration = 0.0
        if len(parts) > 2 and parts[2]:
            try:
                duration = float(parts[2])
            except ValueError:
                duration = 0.0
        message = parts[3] if len(parts) > 3 else ""
        counter[case_status] += 1
        total_duration += duration
        tests.append(
            {
                "suite": suite_name,
                "suite_slug": suite_key,
                "classname": suite_name,
                "name": case_name or f"synthetic-case-{line_number}",
                "name_slug": slugify(case_name or f"synthetic-case-{line_number}"),
                "status": case_status,
                "duration_seconds": duration,
                "failure_text": message[:4000],
                "owner_hint": "synthetic",
                "source": "synthetic",
            }
        )

    suites = [
        {
            "suite": suite_name,
            "suite_slug": suite_key,
            "tests": len(tests),
            "passed": counter["passed"],
            "failed": counter["failed"],
            "skipped": counter["skipped"],
            "cancelled": counter["cancelled"],
            "unknown": counter["unknown"],
            "duration_seconds": total_duration,
            "source": "synthetic",
        }
    ] if tests else []

    return suites, tests


def summarize_tests(tests):
    counter = Counter(test["status"] for test in tests)
    return {
        "tests": len(tests),
        "passed": counter["passed"],
        "failed": counter["failed"],
        "skipped": counter["skipped"],
        "cancelled": counter["cancelled"],
        "unknown": counter["unknown"],
        "duration_seconds": round(sum(float(test.get("duration_seconds", 0.0)) for test in tests), 3),
    }


def main():
    artifacts_dir = Path(getenv("INPUT_ARTIFACTS_DIR", "_artifacts")).resolve()
    ensure_dir(artifacts_dir)
    normalized_dir = artifacts_dir / "normalized-results"
    ensure_dir(normalized_dir)

    tmp_artifacts = Path("/tmp/_artifacts")
    search_roots = [artifacts_dir, tmp_artifacts]

    job_status = normalize_job_status(getenv("INPUT_JOB_STATUS"))
    workflow_name = getenv("GITHUB_WORKFLOW")
    repo_name = getenv("GITHUB_REPOSITORY")
    job_name = getenv("INPUT_JOB_NAME") or getenv("GITHUB_JOB")
    workflow_slug = slugify(workflow_name)
    current_job_slug = slugify(job_name)
    revisions = read_json(artifacts_dir / "tested-revisions.json") or read_json(tmp_artifacts / "tested-revisions.json") or {}

    junit_files = discover_junit_files(search_roots)
    build_logs = discover_build_logs(search_roots, getenv("INPUT_BUILD_LOG_PATH"))

    all_suites = []
    all_tests = []
    for junit_file in junit_files:
        suites, tests = parse_junit_file(junit_file, artifacts_dir)
        all_suites.extend(suites)
        all_tests.extend(tests)

    source_kind = "junit" if all_tests else "none"
    if not all_tests and getenv("INPUT_SYNTHETIC_CASES"):
        all_suites, all_tests = parse_synthetic_cases(
            getenv("INPUT_SYNTHETIC_CASES"),
            getenv("INPUT_SYNTHETIC_SUITE_NAME") or job_name,
            job_status,
        )
        source_kind = "synthetic"

    metadata = {
        "schema_version": 1,
        "repo": repo_name,
        "repo_slug": repo_slug(repo_name),
        "workflow_name": workflow_name,
        "workflow_slug": workflow_slug,
        "workflow_file": getenv("INPUT_WORKFLOW_FILE"),
        "job_id": getenv("GITHUB_JOB"),
        "job_name": job_name,
        "job_slug": current_job_slug,
        "run_id": int(getenv("GITHUB_RUN_ID", "0") or 0),
        "run_attempt": int(getenv("GITHUB_RUN_ATTEMPT", "0") or 0),
        "html_url": f"{getenv('GITHUB_SERVER_URL', 'https://github.com')}/{repo_name}/actions/runs/{getenv('GITHUB_RUN_ID')}",
        "event": getenv("GITHUB_EVENT_NAME"),
        "github_sha": getenv("GITHUB_SHA"),
        "github_ref": getenv("GITHUB_REF"),
        "result": job_status,
        "started_at": None,
        "completed_at": None,
        "duration_seconds": None,
        "collected_at": utc_now(),
        "runner_name": getenv("RUNNER_NAME"),
        "runner_label": getenv("RUNNER_NAME"),
        "mirrored_prow_job": getenv("INPUT_MIRRORED_PROW_JOB"),
        "upstream_testgrid_url": getenv("INPUT_UPSTREAM_TESTGRID_URL"),
        "kubernetes_repo": revisions.get("kubernetes", {}).get("repo"),
        "kubernetes_ref": revisions.get("kubernetes", {}).get("ref"),
        "kubernetes_sha": revisions.get("kubernetes", {}).get("sha"),
        "containerd_repo": revisions.get("containerd", {}).get("repo"),
        "containerd_ref": revisions.get("containerd", {}).get("ref"),
        "containerd_sha": revisions.get("containerd", {}).get("sha"),
        "data_quality": {
            "result_source": source_kind,
            "junit_found": bool(junit_files),
            "synthetic_cases": bool(getenv("INPUT_SYNTHETIC_CASES")),
            "inventory_state": "present" if all_tests else "missing",
        },
        "artifacts": {
            "build_log": relative_to(artifacts_dir, build_logs[0]) if build_logs else None,
            "junit_files": [relative_to(artifacts_dir, path) for path in junit_files],
        },
    }

    file_manifest = {
        "artifacts_dir": str(artifacts_dir),
        "build_logs": [relative_to(artifacts_dir, path) for path in build_logs],
        "junit_files": [relative_to(artifacts_dir, path) for path in junit_files],
        "runner_metadata_files": [
            relative_to(artifacts_dir, path)
            for path in [artifacts_dir / "tested-revisions.json", artifacts_dir / "integration-step-metadata.txt"]
            if path.exists()
        ],
    }

    discovery = {
        "junit_found": bool(junit_files),
        "junit_files": file_manifest["junit_files"],
        "build_log_found": bool(build_logs),
        "build_logs": file_manifest["build_logs"],
        "ginkgo_json_found": any(path.endswith(".json") and "/ginkgo/" in path for path in file_manifest["junit_files"]),
    }

    summary = summarize_tests(all_tests)

    (normalized_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (normalized_dir / "suites.json").write_text(json.dumps(all_suites, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (normalized_dir / "tests.json").write_text(json.dumps(all_tests, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (normalized_dir / "files.json").write_text(json.dumps(file_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (normalized_dir / "discovery.json").write_text(json.dumps(discovery, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (normalized_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
