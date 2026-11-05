#!/usr/bin/env python3
"""Read-only checkout guard for interrupted/scheduled development.

Fetch is deliberately separate. Never changes checkout, index, refs or remote.
Unknown state refuses to suggest that editing is safe.
"""
import json
from pathlib import Path
import subprocess
import sys

BRANCH = "commercial/compliance-foundation-20261105"
ROOT = Path(__file__).resolve().parents[1]


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, text=True,
                          capture_output=True, check=True).stdout.strip()


def inspect():
    branch = git("branch", "--show-current")
    head = git("rev-parse", "HEAD")
    dirty = bool(git("status", "--porcelain"))
    remote_ref = f"refs/remotes/origin/{BRANCH}"
    try:
        remote = git("rev-parse", "--verify", remote_ref)
        ahead, behind = map(int, git("rev-list", "--left-right", "--count", f"HEAD...{remote_ref}").split())
    except subprocess.CalledProcessError:
        remote, ahead, behind = None, None, None
    reasons = []
    if branch != BRANCH:
        reasons.append("wrong_branch")
    if dirty:
        reasons.append("uncommitted_work_requires_review")
    if remote is None:
        reasons.append("remote_branch_missing_or_not_fetched")
    elif behind:
        reasons.append("diverged" if ahead else "behind_remote")
    return dict(branch=branch, head=head, remote_head=remote, ahead=ahead, behind=behind,
                dirty=dirty, ready_for_reviewed_work=not reasons, reasons=reasons,
                note="Read-only snapshot; fetch first and inspect active writers. Not a concurrency lock.")


if __name__ == "__main__":
    try:
        state = inspect()
        print(json.dumps(state, indent=2))
        sys.exit(0 if state["ready_for_reviewed_work"] else 2)
    except (subprocess.CalledProcessError, ValueError) as exc:
        print(json.dumps({"ready_for_reviewed_work": False, "error": type(exc).__name__}))
        sys.exit(2)
