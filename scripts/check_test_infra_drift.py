#!/usr/bin/env python3

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


FLAGS = re.MULTILINE | re.DOTALL


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_spec(root: Path) -> List[Dict]:
    spec_path = root / "scripts" / "test_infra_drift_spec.json"
    with spec_path.open(encoding="utf-8") as stream:
        return json.load(stream)["items"]


def gopath_test_infra_dir() -> Optional[Path]:
    try:
        output = subprocess.check_output(
            ["go", "env", "GOPATH"],
            stderr=subprocess.DEVNULL,
            universal_newlines=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None

    if not output:
        return None

    first_entry = output.split(os.pathsep)[0].strip()
    if not first_entry:
        return None

    return Path(first_entry).expanduser() / "src" / "k8s.io" / "test-infra"


def candidate_test_infra_dirs(root: Path, explicit: Optional[str]) -> List[Path]:
    candidates: List[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    env_value = os.environ.get("TEST_INFRA_DIR")
    if env_value:
        candidates.append(Path(env_value).expanduser())
    go_env_dir = gopath_test_infra_dir()
    if go_env_dir is not None:
        candidates.append(go_env_dir)
    candidates.append(root.parent.parent.parent / "k8s.io" / "test-infra")
    candidates.append(root.parent / "test-infra")
    return candidates


def resolve_test_infra_dir(root: Path, explicit: Optional[str]) -> Path:
    seen: Set[Path] = set()
    for candidate in candidate_test_infra_dirs(root, explicit):
        candidate = candidate.resolve()
        if candidate in seen:
            continue
        seen.add(candidate)
        if (candidate / "config" / "jobs" / "kubernetes").is_dir():
            return candidate
    searched = "\n".join(f"- {path}" for path in seen)
    raise SystemExit(
        "Unable to find a test-infra checkout.\n"
        "Set TEST_INFRA_DIR or pass --test-infra-dir.\n"
        f"Searched:\n{searched}"
    )


def read_text(path: Path) -> str:
    with path.open(encoding="utf-8") as stream:
        return stream.read()


def extract_job_block(text: str, job_name: str) -> str:
    job_match = re.search(
        rf"^(?P<indent>\s*)- name:\s*{re.escape(job_name)}\s*$",
        text,
        re.MULTILINE,
    )
    if not job_match:
        raise ValueError(f"job {job_name!r} not found")

    indent = len(job_match.group("indent"))
    start = job_match.start()
    next_job = re.compile(r"^(?P<indent>\s*)- name:\s*.+$", re.MULTILINE)

    for match in next_job.finditer(text, job_match.end()):
        if len(match.group("indent")) == indent:
            return text[start:match.start()]

    return text[start:]


def normalize(value: str, mode: Optional[str]) -> str:
    value = value.strip()
    if mode == "nospace":
        return re.sub(r"\s+", "", value)
    return value


def capture(text: str, pattern: str) -> str:
    match = re.search(pattern, text, FLAGS)
    if not match:
        raise ValueError(f"pattern not found: {pattern}")
    return match.group(1)


def run_check(local_text: str, upstream_text: str, check: Dict) -> Tuple[bool, str]:
    kind = check["kind"]
    name = check["name"]

    if kind == "contains_both":
        needle = check["needle"]
        if needle not in local_text:
            return False, f"{name}: local text missing {needle!r}"
        if needle not in upstream_text:
            return False, f"{name}: upstream text missing {needle!r}"
        return True, f"{name}: found {needle!r} in both"

    if kind == "presence_regex":
        local_match = re.search(check["local_regex"], local_text, FLAGS)
        upstream_match = re.search(check["upstream_regex"], upstream_text, FLAGS)
        if not local_match:
            return False, f"{name}: local regex did not match"
        if not upstream_match:
            return False, f"{name}: upstream regex did not match"
        return True, f"{name}: regex matched on both sides"

    if kind == "absence_regex":
        if re.search(check["local_regex"], local_text, FLAGS):
            return False, f"{name}: local regex unexpectedly matched"
        return True, f"{name}: local regex absent as expected"

    if kind == "capture_eq":
        normalize_mode = check.get("normalize")
        try:
            local_value = normalize(capture(local_text, check["local_regex"]), normalize_mode)
            upstream_value = normalize(capture(upstream_text, check["upstream_regex"]), normalize_mode)
        except ValueError as error:
            return False, f"{name}: {error}"
        if local_value != upstream_value:
            return False, (
                f"{name}: local={local_value!r} upstream={upstream_value!r}"
            )
        return True, f"{name}: {local_value!r}"

    return False, f"{name}: unsupported check kind {kind!r}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare local workflows against a curated set of upstream test-infra jobs."
    )
    parser.add_argument(
        "--test-infra-dir",
        help="Path to a local kubernetes/test-infra checkout. Defaults to TEST_INFRA_DIR or common local locations.",
    )
    args = parser.parse_args()

    root = repo_root()
    test_infra_dir = resolve_test_infra_dir(root, args.test_infra_dir)
    spec = load_spec(root)

    mismatches = 0
    total_checks = 0

    print(f"Using test-infra checkout: {test_infra_dir}")

    for item in spec:
        local_path = root / item["local_file"]
        upstream_path = test_infra_dir / item["upstream_file"]

        local_text = read_text(local_path)
        upstream_text = read_text(upstream_path)
        upstream_block = extract_job_block(upstream_text, item["upstream_job"])

        print(f"\n== {item['id']}")
        print(f"local:    {item['local_file']}")
        print(f"upstream: {item['upstream_file']}#{item['upstream_job']}")

        for check in item["checks"]:
            total_checks += 1
            ok, message = run_check(local_text, upstream_block, check)
            status = "OK" if ok else "FAIL"
            print(f"  [{status}] {message}")
            if not ok:
                mismatches += 1

    print(
        f"\nSummary: {len(spec)} mappings, {total_checks} checks, {mismatches} mismatches"
    )
    return 1 if mismatches else 0


if __name__ == "__main__":
    sys.exit(main())
