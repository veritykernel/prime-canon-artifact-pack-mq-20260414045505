#!/usr/bin/env python3
"""Select the workflow run bound to an exact commit or merge-queue PR."""

import argparse
from datetime import datetime, timezone
import json
import re
import sys


SHA = re.compile(r"[0-9a-f]{40}\Z")


def timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def select_run(runs, *, event, head_sha=None, merge_pr=None, not_before=None):
    if not isinstance(runs, list):
        raise ValueError("workflow run list must be an array")
    if bool(head_sha) == bool(merge_pr):
        raise ValueError("specify exactly one exact head or merge-queue PR")
    if merge_pr is not None and (not isinstance(merge_pr, int) or merge_pr < 1 or not_before is None):
        raise ValueError("merge-queue selection requires a positive PR and request time")
    if head_sha and not SHA.fullmatch(head_sha):
        raise ValueError("expected head is not a full SHA-1")

    candidates = []
    for run in runs:
        if not isinstance(run, dict) or run.get("event") != event:
            continue
        run_sha = run.get("headSha")
        if not isinstance(run_sha, str) or not SHA.fullmatch(run_sha):
            continue
        created = timestamp(run.get("createdAt"))
        if head_sha:
            if run_sha != head_sha:
                continue
        else:
            branch = run.get("headBranch", "")
            # GitHub's merge-queue branch is main/pr-N with an optional suffix.
            if not isinstance(branch, str) or not re.fullmatch(rf"main/pr-{merge_pr}(?:[-/].*)?", branch):
                continue
            if created is None or created < not_before:
                continue
        candidates.append((created or datetime.min.replace(tzinfo=timezone.utc), run))

    if not candidates:
        return None
    newest = max(item[0] for item in candidates)
    newest_runs = [run for created, run in candidates if created == newest]
    # A one-second GitHub timestamp cannot order two runs created together.
    return newest_runs[0] if len(newest_runs) == 1 else None


def merged_pr_matches(pr, *, number, head_sha, not_before):
    if not isinstance(pr, dict):
        return False
    merge_commit = pr.get("mergeCommit")
    merged_at = timestamp(pr.get("mergedAt"))
    return (
        pr.get("number") == number
        and pr.get("state") == "MERGED"
        and pr.get("headRefOid") == head_sha
        and isinstance(merge_commit, dict)
        and isinstance(merge_commit.get("oid"), str)
        and SHA.fullmatch(merge_commit["oid"]) is not None
        and merged_at is not None
        and merged_at >= not_before
    )


def independent_review_matches(pr, reviews, *, number, head_sha, reviewer):
    if (not isinstance(pr, dict) or pr.get("number") != number
            or pr.get("headRefOid") != head_sha or pr.get("reviewDecision") != "APPROVED"
            or not isinstance(pr.get("author"), dict)
            or pr["author"].get("login", "").casefold() == reviewer.casefold()
            or not isinstance(reviews, list)):
        return False
    decisions = []
    for review in reviews:
        if (not isinstance(review, dict) or not isinstance(review.get("user"), dict)
                or review["user"].get("login", "").casefold() != reviewer.casefold()
                or review.get("state") not in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED")):
            continue
        submitted = timestamp(review.get("submitted_at"))
        if submitted is None or not isinstance(review.get("id"), int):
            continue
        decisions.append((submitted, review["id"], review))
    if not decisions:
        return False
    latest = max(decisions)[2]
    return latest.get("state") == "APPROVED" and latest.get("commit_id") == head_sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    select = subparsers.add_parser("select")
    select.add_argument("--event", required=True)
    selector = select.add_mutually_exclusive_group(required=True)
    selector.add_argument("--head-sha")
    selector.add_argument("--merge-pr", type=int)
    select.add_argument("--not-before")
    merged = subparsers.add_parser("verify-merged")
    merged.add_argument("--pr", required=True, type=int)
    merged.add_argument("--head-sha", required=True)
    merged.add_argument("--not-before", required=True)
    reviewed = subparsers.add_parser("verify-review")
    reviewed.add_argument("--pr", required=True, type=int)
    reviewed.add_argument("--head-sha", required=True)
    reviewed.add_argument("--reviewer", required=True)
    reviewed.add_argument("pr_json")
    reviewed.add_argument("reviews_json")
    args = parser.parse_args()
    if args.action == "verify-review":
        if not SHA.fullmatch(args.head_sha):
            parser.error("review verification needs a full exact head")
        with open(args.pr_json, encoding="utf-8") as stream:
            pr = json.load(stream)
        with open(args.reviews_json, encoding="utf-8") as stream:
            reviews = json.load(stream)
        if not independent_review_matches(pr, reviews, number=args.pr,
                                          head_sha=args.head_sha, reviewer=args.reviewer):
            raise SystemExit("exact-head independent code-owner approval not observed")
        return
    payload = json.load(sys.stdin)
    if args.action == "select":
        before = timestamp(args.not_before) if args.not_before else None
        if args.merge_pr and before is None:
            parser.error("merge-queue selection needs a valid --not-before")
        match = select_run(payload, event=args.event, head_sha=args.head_sha, merge_pr=args.merge_pr, not_before=before)
        if match is None:
            print("|||")
        else:
            fields = (match.get("status", ""), match.get("conclusion", ""), match.get("url", ""), match.get("headSha", ""))
            if any(not isinstance(field, str) or "|" in field for field in fields):
                raise ValueError("invalid workflow run field")
            print("|".join(fields))
        return
    before = timestamp(args.not_before)
    if before is None or not SHA.fullmatch(args.head_sha):
        parser.error("verification needs valid --not-before and --head-sha")
    if not merged_pr_matches(payload, number=args.pr, head_sha=args.head_sha, not_before=before):
        raise SystemExit("exact PR is not verified merged after the queue request")


if __name__ == "__main__":
    main()
