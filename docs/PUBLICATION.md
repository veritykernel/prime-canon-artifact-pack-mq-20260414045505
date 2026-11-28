# Rendered publication

Use `scripts/publish_rendered_subject.sh <subject-slug>` for the configured
stage destination. The target directory must already exist. The guard accepts
only this verified publisher or its no-effect dry run.

Set `PRIME_CANON_TRUSTED_PYTHON` to an operator-installed Python executable
outside the checkout with PyYAML and jsonschema installed. The guarded
publisher checks that this is an absolute, regular, operator-owned executable
under no-follow, non-writable ancestors. It fails closed when the interpreter
or dependencies are missing. It never activates the checkout's `.venv` or
bootstraps packages from the checkout. The operator controls and pins that
external environment separately; `requirements.txt` is not an install
authorization or a package lock for guarded publication.
The guard invokes reviewed entrypoints under isolated Python with trusted
packages ahead of the checkout's script path, so a candidate `yaml.py` cannot
shadow the installed YAML parser.

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
Verification recomputes the exact Markdown body from the bound canon nodes and
render policy, including the view's generation time. Matching hashes inserted
into both candidate receipts cannot authorize unrelated Markdown.
The claim, evidence, topology, readiness, render and immutable receipt writers
use descriptor-relative no-follow repository reads and writes. An existing
governed file must still match its original byte snapshot before replacement;
the render builder updates the current view only after its paired receipts and
corpus route are written. A failed multi-file build remains a partial effect
to reconcile before retrying.

An existing subject with a legacy view hash must receive a reviewed successor
render generation before it can publish under this binding. Run
`python3 scripts/build_rendered_projection.py . <subject-slug> v2` in a
review branch. This adds `render-execution-v2.yaml` and `render-drift-v2.yaml`,
and the current view names that pair while preserving the original receipts.
Use a new generation label for each later render. CI preserves previously
committed immutable receipts, promoted nodes, and reviewed source units. It
rejects a change to an existing current view unless the change is strictly a
render-only successor with a new receipt pair and live in-sync verification.
New current-view additions remain held until a trusted signed-promotion
admission check is installed; a candidate's claim that it ran the local
promotion script is not such an attestation.

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
commit. Before touching the fixture, it requires a clean source checkout at
the exact protected `main` SHA and pins its selector bytes to that commit.
The synthetic branch changes only a proof marker, and its ruleset requires a
distinct write-qualified VK code-owner approval on the exact PR head before
queue merge. Its run selector binds the result to the exact proof PR and
merge-group run. This script has external GitHub effects and is not part of
ordinary validation or publication.
