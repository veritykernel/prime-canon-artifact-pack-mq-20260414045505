#!/usr/bin/env bash
# Prove the merge-queue rule with a synthetic workflow in an owner-qualified
# private fixture. Never mirror this repository or create a public repository.
set -euo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export GH_PROMPT_DISABLED=1
export GIT_PAGER=cat
export PYTHONDONTWRITEBYTECODE=1

SOURCE_REPO="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE_NAME="veritykernel/prime-canon-artifact-pack-mq-20260414045505"
SOURCE_HEAD="$(git -C "$SOURCE_REPO" rev-parse HEAD)"
if [ "$(git -C "$SOURCE_REPO" rev-parse --show-toplevel)" != "$SOURCE_REPO" ] \
   || [ "$(git -C "$SOURCE_REPO" branch --show-current)" != "main" ] \
   || [ -n "$(git -C "$SOURCE_REPO" status --porcelain --untracked-files=all)" ] \
   || [ "$SOURCE_HEAD" != "$(gh api "repos/$SOURCE_NAME/branches/main" --jq .commit.sha)" ]; then
  echo "proof requires a clean checkout at the exact protected main commit" >&2
  exit 4
fi
for proof_file in scripts/prove_merge_queue.sh scripts/select_proof_run.py; do
  if [ "$(git -C "$SOURCE_REPO" hash-object "$proof_file")" != \
       "$(git -C "$SOURCE_REPO" rev-parse "HEAD:$proof_file")" ]; then
    echo "proof source differs from the protected commit: $proof_file" >&2
    exit 4
  fi
done
MQ_REPO="$(printenv MQ_REPO || true)"
RETAIN_MQ_REPO="$(printenv RETAIN_MQ_REPO || true)"
if [ -z "$MQ_REPO" ] || [ "$RETAIN_MQ_REPO" != "1" ]; then
  echo "set MQ_REPO to a dedicated empty private veritykernel fixture and RETAIN_MQ_REPO=1" >&2
  exit 4
fi
case "$MQ_REPO" in
  veritykernel/*) ;;
  *) echo "MQ_REPO must be owned by veritykernel" >&2; exit 4 ;;
esac
if [ "$MQ_REPO" = "veritykernel/$(basename "$SOURCE_REPO")" ]; then
  echo "the source repository cannot be used as a proof fixture" >&2
  exit 4
fi

METADATA="$(gh repo view "$MQ_REPO" --json nameWithOwner,isPrivate,isEmpty,description)"
printf '%s' "$METADATA" | python3 -c '
import json,sys
repo=json.load(sys.stdin)
if (repo.get("nameWithOwner") != sys.argv[1] or repo.get("isPrivate") is not True
        or repo.get("isEmpty") is not True
        or repo.get("description") != "prime-canon-merge-queue-fixture-v1"):
    raise SystemExit("proof repository must be an exact empty private fixture with the required marker")
' "$MQ_REPO"
REVIEWER="vk-maintainer-joeyeoj69"
REVIEWER_PERMISSION="$(gh api "repos/$MQ_REPO/collaborators/$REVIEWER/permission" --jq .permission)"
case "$REVIEWER_PERMISSION" in
  write|maintain|admin) ;;
  *) echo "the distinct reviewer must have write authority on the proof fixture" >&2; exit 4 ;;
esac

WORK_DIR="$(mktemp -d /tmp/prime-mq-proof.XXXXXX)"
trap 'rm -rf "$WORK_DIR"' EXIT
PROOF_SELECTOR="$WORK_DIR/select_proof_run.py"
cp "$SOURCE_REPO/scripts/select_proof_run.py" "$PROOF_SELECTOR"
if [ "$(git -C "$SOURCE_REPO" hash-object "$PROOF_SELECTOR")" != \
     "$(git -C "$SOURCE_REPO" rev-parse HEAD:scripts/select_proof_run.py)" ]; then
  echo "proof selector snapshot changed after source validation" >&2
  exit 4
fi
git -C "$WORK_DIR" init -q -b main
git -C "$WORK_DIR" config user.name "PRIME synthetic proof"
git -C "$WORK_DIR" config user.email "prime-proof@users.noreply.github.com"
mkdir -p "$WORK_DIR/.github/workflows"
printf '* @%s\n' "$REVIEWER" > "$WORK_DIR/.github/CODEOWNERS"
cat > "$WORK_DIR/.github/workflows/publish-guard-check.yml" <<'YAML'
name: publish-guard-check
on:
  push:
  pull_request:
  merge_group:
permissions:
  contents: read
jobs:
  publish-guard-check:
    runs-on: ubuntu-latest
    steps:
      - run: /usr/bin/true
YAML
git -C "$WORK_DIR" add .github/workflows/publish-guard-check.yml .github/CODEOWNERS
git -C "$WORK_DIR" commit -qm "Add minimal synthetic merge-queue fixture"
MAIN_SHA="$(git -C "$WORK_DIR" rev-parse HEAD)"
git -C "$WORK_DIR" remote add mq "https://github.com/$MQ_REPO.git"
git -C "$WORK_DIR" push mq HEAD:main
DEFAULT_BRANCH="$(gh repo view "$MQ_REPO" --json defaultBranchRef --jq .defaultBranchRef.name)"
if [ "$DEFAULT_BRANCH" != "main" ]; then
  gh api --method PATCH "repos/$MQ_REPO" -f default_branch=main >/dev/null
fi

wait_run() {
  event="$1"
  expected_sha="$2"
  merge_pr="$3"
  not_before="$4"
  for attempt in $(seq 1 48); do
    RUN_JSON="$(gh run list --repo "$MQ_REPO" --workflow publish-guard-check.yml --event "$event" --json status,conclusion,headSha,headBranch,createdAt,event,url --limit 100)"
    if [ -n "$merge_pr" ]; then
      MATCH="$(printf '%s' "$RUN_JSON" | /usr/bin/python3 "$PROOF_SELECTOR" select --event "$event" --merge-pr "$merge_pr" --not-before "$not_before")"
    else
      MATCH="$(printf '%s' "$RUN_JSON" | /usr/bin/python3 "$PROOF_SELECTOR" select --event "$event" --head-sha "$expected_sha")"
    fi
    IFS='|' read -r RUN_STATUS RUN_CONCLUSION RUN_URL RUN_SHA <<< "$MATCH"
    if [ "$RUN_STATUS" = "completed" ]; then
      [ "$RUN_CONCLUSION" = "success" ] || { echo "$event run failed: $RUN_URL" >&2; return 1; }
      return 0
    fi
    sleep 5
  done
  echo "no exact successful $event run was observed" >&2
  return 1
}

wait_run push "$MAIN_SHA" "" ""
RULESET_JSON="$(cat <<'JSON' | gh api --method POST "repos/$MQ_REPO/rulesets" --input -
{
  "name": "required-ci-publish-guard-main-mq",
  "target": "branch",
  "enforcement": "active",
  "conditions": {"ref_name": {"include": ["refs/heads/main"], "exclude": []}},
  "rules": [
    {"type": "pull_request", "parameters": {
      "allowed_merge_methods": ["squash"],
      "dismiss_stale_reviews_on_push": true,
      "require_code_owner_review": true,
      "require_last_push_approval": true,
      "required_approving_review_count": 1,
      "required_review_thread_resolution": true
    }},
    {"type": "required_status_checks", "parameters": {
      "do_not_enforce_on_create": false,
      "required_status_checks": [{"context": "publish-guard-check"}],
      "strict_required_status_checks_policy": true
    }},
    {"type": "merge_queue", "parameters": {
      "check_response_timeout_minutes": 30,
      "grouping_strategy": "HEADGREEN",
      "max_entries_to_build": 1,
      "max_entries_to_merge": 1,
      "merge_method": "SQUASH",
      "min_entries_to_merge": 1,
      "min_entries_to_merge_wait_minutes": 0
    }}
  ]
}
JSON
)"
RULESET_ID="$(printf '%s' "$RULESET_JSON" | /usr/bin/python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
gh api "repos/$MQ_REPO/rulesets/$RULESET_ID" | /usr/bin/python3 -c '
import json,sys
ruleset=json.load(sys.stdin)
rules={rule["type"]: rule for rule in ruleset.get("rules", [])}
review=rules.get("pull_request", {}).get("parameters", {})
checks=rules.get("required_status_checks", {}).get("parameters", {})
if (ruleset.get("enforcement") != "active" or "merge_queue" not in rules
        or review.get("required_approving_review_count", 0) < 1
        or review.get("require_code_owner_review") is not True
        or review.get("require_last_push_approval") is not True
        or checks.get("strict_required_status_checks_policy") is not True
        or not any(item.get("context") == "publish-guard-check"
                   for item in checks.get("required_status_checks", []))):
    raise SystemExit("synthetic ruleset does not enforce exact review and queue gates")
'

RUN_ID="$(date -u +%Y%m%d%H%M%S)"
PROOF_BRANCH="cycle-2/mq-proof-$RUN_ID"
git -C "$WORK_DIR" switch -q -c "$PROOF_BRANCH"
printf 'synthetic proof run %s\n' "$RUN_ID" > "$WORK_DIR/proof.txt"
git -C "$WORK_DIR" add proof.txt
git -C "$WORK_DIR" commit -qm "Trigger exact queue proof $RUN_ID"
PR_HEAD_SHA="$(git -C "$WORK_DIR" rev-parse HEAD)"
git -C "$WORK_DIR" push mq "HEAD:$PROOF_BRANCH"
wait_run push "$PR_HEAD_SHA" "" ""
gh pr create --repo "$MQ_REPO" --base main --head "$PROOF_BRANCH" --title "Synthetic merge queue proof $RUN_ID" --body "Contains only the minimal publish-guard-check workflow." >/dev/null
PR_NUMBER="$(gh pr view --repo "$MQ_REPO" "$PROOF_BRANCH" --json number --jq .number)"
wait_run pull_request "$PR_HEAD_SHA" "" ""
gh pr edit --repo "$MQ_REPO" "$PR_NUMBER" --add-reviewer "$REVIEWER" >/dev/null
REVIEW_APPROVED="false"
for attempt in $(seq 1 48); do
  gh pr view --repo "$MQ_REPO" "$PR_NUMBER" --json number,headRefOid,reviewDecision,author > "$WORK_DIR/review-pr.json"
  gh api "repos/$MQ_REPO/pulls/$PR_NUMBER/reviews" > "$WORK_DIR/reviews.json"
  if /usr/bin/python3 "$PROOF_SELECTOR" verify-review --pr "$PR_NUMBER" \
       --head-sha "$PR_HEAD_SHA" --reviewer "$REVIEWER" \
       "$WORK_DIR/review-pr.json" "$WORK_DIR/reviews.json"; then
    REVIEW_APPROVED="true"
    break
  fi
  sleep 5
done
[ "$REVIEW_APPROVED" = "true" ] || { echo "exact-head independent reviewer approval was not observed" >&2; exit 1; }

QUEUE_REQUESTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
gh pr merge --repo "$MQ_REPO" "$PROOF_BRANCH" --squash --match-head-commit "$PR_HEAD_SHA"
wait_run merge_group "" "$PR_NUMBER" "$QUEUE_REQUESTED_AT"

MERGED="false"
for attempt in $(seq 1 24); do
  PR_JSON="$(gh pr view --repo "$MQ_REPO" "$PR_NUMBER" --json number,state,headRefOid,mergedAt,mergeCommit)"
  if printf '%s' "$PR_JSON" | /usr/bin/python3 "$PROOF_SELECTOR" verify-merged --pr "$PR_NUMBER" --head-sha "$PR_HEAD_SHA" --not-before "$QUEUE_REQUESTED_AT" >/dev/null 2>&1; then
    MERGED="true"
    break
  fi
  sleep 5
done
[ "$MERGED" = "true" ] || { echo "exact proof PR was not confirmed merged" >&2; exit 1; }

echo "merge_queue_proof=success"
echo "fixture_repo=$MQ_REPO"
echo "source_protected_head=$SOURCE_HEAD"
echo "reviewer=$REVIEWER"
echo "synthetic_ruleset_id=$RULESET_ID"
echo "pr_number=$PR_NUMBER"
echo "merge_group_run_url=$RUN_URL"
echo "merge_group_head_sha=$RUN_SHA"
echo "fixture_retained_by_explicit_owner_choice=true"
