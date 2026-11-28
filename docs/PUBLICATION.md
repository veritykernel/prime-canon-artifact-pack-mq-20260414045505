# Rendered publication

Use `scripts/publish_rendered_subject.sh <subject-slug>` for the configured
stage destination. The target directory must already exist. The guard accepts
only this verified publisher or its no-effect dry run.

The publisher checks the current view, render execution receipt, and drift
receipt against the expected subject and output path. It reads the rendered
source once, verifies the SHA-256 recorded by the execution receipt, and
publishes those same bytes with an atomic replacement inside an open target
directory. It rejects source and destination symlinks and leaves the existing
target untouched if verification fails. A green drift receipt alone cannot
authorize later changed bytes.
The repository target must equal the approved /Users/Shared/nuum-work/stage
subject filename; a repository edit cannot select another host directory.

The current view binds its complete spec, the exact bytes of referenced active
nodes, supersession edges, contradictions, unresolved blockers, prior derivation
receipts, and the four render policy files into the v3 `view_hash`. The active
render execution and drift receipts contain that hash, so their exact IDs are
bound in the spec and their bytes are checked separately. Export prep and the
publisher recompute the content root on every use. `check_render_drift.py` is read-only:
it reports stale inputs without changing an immutable receipt or the view.
The render builder also leaves promoted node bytes unchanged.

An existing subject with a legacy view hash must receive a reviewed successor
render generation before it can publish under this binding. Run
`python3 scripts/build_rendered_projection.py . <subject-slug> v2` in a
review branch. This adds `render-execution-v2.yaml` and `render-drift-v2.yaml`,
and the current view names that pair while preserving the original receipts.
Use a new generation label for each later render. CI preserves previously
committed immutable receipts, promoted nodes, and reviewed source units. It
rejects a change to an existing current view unless the change is strictly a
render-only successor with a new receipt pair and live in-sync verification.

The publish-guard-check workflow checks a candidate checkout with policy from
default branch main. The additional `publish-guard-trusted` job runs only code
from the protected base checkout and compares enforcement files and prior
immutable receipts, nodes, and source units with the candidate. It never
executes candidate code. CODEOWNERS assigns workflows, scripts, and CODEOWNERS
to the VK maintainer. After this source change merges, observe the trusted job
on an exact PR head and add its app-bound context to the hosted ruleset. The
existing `publish-guard-check` and `validate` contexts, strictness, code-owner
review, last-push review, and no-bypass setting remain required.

The merge-queue proof script accepts only an explicitly selected, empty private
`veritykernel` fixture with the exact proof marker and owner retention choice.
It creates a synthetic workflow there and never pushes this repository's source
commit. Its run selector binds the result to the exact proof PR and merge-group
run. This script has external GitHub effects and is not part of ordinary
validation or publication.
