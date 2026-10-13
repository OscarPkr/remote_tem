# Wave 6 test-isolation foundation

## Provenance and boundary

- Worktree: `/home/alteixeira20/Projects/Odysseus/odysseus-wave6-test-isolation`.
- Starting branch: `wave6/test-isolation-foundation`.
- Starting HEAD: `b1666951faf8285054e1ca90f11533b0fb53fb57`.
- Starting TREE: `a3dee24e3c56c22e1d3f9805f409bf16b086c3d4`.
- `git status --short --branch`: `## wave6/test-isolation-foundation` only.
- `git status --porcelain`: empty. Starting worktree clean.
- No rebase, merge, push, PR edit, or access to the Wave 4 worktree.
- All changes are test code, test helpers, or this test validation report.
  No production code changed; no STOP-level exception was needed.

## Contamination map

| Source | Mutation / binding | Previous cleanup | Escaping state / effect |
| --- | --- | --- | --- |
| Both tests in `tests/test_truncate_message_count_regression.py`, through `_make_manager` | Creates an unowned `mkstemp` DB; directly sets `os.environ["DATABASE_URL"]`; reloads `core.database` then `core.session_manager` | Only the assertion's ORM session is closed | Environment, engine, factory, declarative Base, ORM classes, manager globals, and registered engine listeners survive; database files are never deleted |
| Collection of `tests/test_manage_tasks_owner_scope.py` | Creates a module-lifetime temporary DB and assigns `_TS` permanently to `core.database.SessionLocal` | Some individual rows deleted; ORM sessions closed | The collection-time factory assignment leaks to unrelated tests; truncation reload replaces it, so production handlers and `_seed` / `_get` use different databases |
| `test_checkin_digest_owner_scope.py`, `test_gallery_owner_filter_single_user.py`, `test_document_session_owner_scope.py` | Create module-lifetime DB files / engines and retain local factories | Some rows deleted / route factory restored / ORM sessions closed | Owned files and engines lack teardown; retained imported ORM identities can disagree with reloaded module globals |
| `tests/conftest.py` bootstrap | `DATABASE_URL` was set only if absent before importing `core.database` | No environment restoration | An inherited developer URL could be opened and initialized during collection |

`importlib.reload` updates the existing module dictionary in place; it does
not change the `sys.modules` module object's identity. Previously imported
symbols nevertheless keep their old class/factory identities. In particular,
`src.database` re-exports old objects, while reloaded `core.session_manager`
rebinds its `DbSession`, `DbChatMessage`, `DbDocument`, `SessionLocal`, and
`SessionManager`. Old functions still resolve globals through those changed
module dictionaries. Each database reload also registers a new SQLite connect
listener on SQLAlchemy's Engine class.

The current failures are principally in `test_manage_tasks_owner_scope.py`:
`_seed` writes through its retained `_TS`, but `do_manage_tasks` imports the
now-replaced factory from `core.database` at call time. Ownerless / cross-owner
mutations incorrectly observe "task not found"; successful mutation/list/create
witnesses likewise read or write the wrong test database. Four invalid-date
cases still pass, so the observed contamination count is 16 rather than all
20 task-owner cases.

`src.settings` has TTL caches, but those caches do not resolve DATABASE_URL.
The contaminating helper neither patches nor reloads settings. The database
URL is read directly from the environment at database import/reload time;
settings cache invalidation is not the correction for this leak.

## Baseline reproduction before editing

All baseline commands explicitly selected in-memory bootstrap storage. Python
with installed pytest/SQLAlchemy was
`/tmp/pr40-final-validation-venv/bin/python` (pytest 9.1.1, SQLAlchemy 2.1.1).

```sh
DATABASE_URL=sqlite:///:memory: /tmp/pr40-final-validation-venv/bin/python -m pytest -q -p no:cacheprovider tests/test_manage_tasks_owner_scope.py tests/test_checkin_digest_owner_scope.py tests/test_gallery_owner_filter_single_user.py tests/test_document_session_owner_scope.py tests/test_truncate_message_count_regression.py
# 30 passed, 9 warnings in 2.48s

DATABASE_URL=sqlite:///:memory: /tmp/pr40-final-validation-venv/bin/python -m pytest -q -p no:cacheprovider tests/test_truncate_message_count_regression.py tests/test_manage_tasks_owner_scope.py tests/test_checkin_digest_owner_scope.py tests/test_gallery_owner_filter_single_user.py tests/test_document_session_owner_scope.py
# 16 failed, 14 passed, 9 warnings in 2.40s

DATABASE_URL=sqlite:///:memory: /tmp/pr40-final-validation-venv/bin/python -m pytest -q -p no:cacheprovider -rx --runxfail tests/test_runtime_behavior_regressions.py -k negative_web
# 2 failed (IndexError), 1 passed, 13 deselected, 1 warning in 1.61s
```

The same 30 database tests shuffled with `random.Random(42)` before editing
reported **9 failed, 21 passed**, 9 warnings in 2.37s. Exact command:

```sh
/tmp/pr40-final-validation-venv/bin/python /tmp/odysseus-wave6-isolation-evidence/run_order.py seed:42 before-seed42 tests/test_manage_tasks_owner_scope.py tests/test_checkin_digest_owner_scope.py tests/test_gallery_owner_filter_single_user.py tests/test_document_session_owner_scope.py tests/test_truncate_message_count_regression.py
```

## Isolation correction and regression evidence

- `tests/helpers/database.py` owns a fresh TemporaryDirectory, file-backed
  SQLite engine with NullPool, real schema, and factory for each invocation.
  Teardown disposes the engine and removes the directory including sidecars.
- The truncation fixture temporarily patches only resource bindings in
  `core.database`, `src.database`, and `core.session_manager`, with a matching
  temporary environment URL. Patches are undone before resource disposal.
  No module reload, module eviction, new ORM class, or listener registration.
- Four owner modules now own a disposable database per test rather than at
  collection. Only the task-owner module patches the canonical factory; that
  patch is scoped to the test and restored during teardown. The other modules
  retain their existing handler/route wiring and ownership assertions.
- The existing pytest bootstrap always chooses in-memory storage before
  production database imports and registers environment restoration with the
  pytest configuration lifecycle. No new process-wide autouse cleanup fixture.
- `tests/test_database_test_isolation.py` checks real persistent truncation,
  exact class/factory restoration, file removal, clean subsequent database
  state, and exception teardown. Child pytest runs execute the actual original
  witness entry points in both directions and check process-visible bindings
  after collection and after every test. An inherited developer-DB sentinel
  remains byte-identical, with no database sidecars created, and the inherited
  environment URL is restored after pytest exits.

Mutation checks temporarily restored one original file at a time, ran
`test_actual_tests_restore_process_state_and_ignore_inherited_database[True]`,
and restored the corrected file in `finally`. Both mutations made the new
regression fail (pytest exit 1): original truncation was caught as
"test leaked database or module state", original task-owner collection as
"collection changed database bindings". No mutation was retained.

## Historical negative-web witnesses and production blocker

Both parameter cases in
`test_negative_web_wording_withholds_the_web_tools_unhandled` intended to prove
that inferred negative-web wording can receive a memory-only answer without
`web_search` or `web_fetch` being offered to the model:

1. `Summarise what you already know. Do not search the web.`
2. `No web search please, just tell me what you know about Python decorators.`

Both previously indexed an empty fake-model call list and xfailed on unrelated
`IndexError`. The fake also emitted provider-shaped `choices` JSON at a seam
that now consumes normalized `{"delta": ...}` SSE.

The repaired witnesses drive the unmodified public `stream_agent_loop`, mock
only model output and existing infrastructure edges, capture the actual SSE,
and require one model call, withheld web schemas, and delivered fake answer.
The existing passing "don't search online" control and positive search
control remain. The fake now emits normalized SSE.

The two historical xfails remain **strict**, with
`raises=_MemoryOnlyTurnBlocked`. That exception is emitted only when the real
loop makes zero model calls and returns the exact known disabled-web response.
IndexError, arbitrary assertions, or other exceptions no longer qualify.

This is a genuine production defect outside the lane: negative-web detection
is true for both phrasings, but `_classify_agent_request` returns `{'web'}` and
`_web_search_unavailable_for_turn` returns true after the negative has disabled
web tools. The loop short-circuits the requested memory-only response with:

> Web access is disabled for this turn. Enable web search and resend the request.

The passing "Answer from memory only, don't search online." control has
`{'memory', 'web'}` intent domains and does not short-circuit. A minimized
reproduction using those three production functions requires neither a model
nor a mock. Relevant production locations (intentionally untouched):
`src/agent_loop.py` negative detector near line 864, classifier near 10371,
negative-tool disabling near 20735, unavailable calculation near 22233, and
short-circuit response near 25101.

```sh
/tmp/pr40-final-validation-venv/bin/python -m pytest -q -p no:cacheprovider --runxfail tests/test_runtime_behavior_regressions.py -k negative_web_wording_withholds_the_web_tools_unhandled
# 2 failed with _MemoryOnlyTurnBlocked, 14 deselected, 1 warning in 0.75s
```

No production repair was attempted. Runtime intent/availability behavior,
authority, completion/evidence, and Wave 4 effects files remain untouched.
This blocker prevents a READY release-foundation verdict despite passing test
isolation validation.

## Final order validation

The focused manifest has 50 cases: the five baseline database modules plus
`test_database_test_isolation.py` and `test_runtime_behavior_regressions.py`.
Normal collection order is alphabetical by the seven explicitly selected files.
Reversed and seeded runs reorder **individual collected test cases**, including
parameterized cases. Both contamination directions also vary file collection
order. Every execution manifest is retained as JSON in the evidence directory.

| Run | Result |
| --- | --- |
| Normal | 48 passed, 2 xfailed, 0 skipped, 11 warnings in 9.01s |
| Reverse of all collected cases | 48 passed, 2 xfailed, 0 skipped, 11 warnings in 8.47s |
| Truncation module first, owner witnesses afterward | 48 passed, 2 xfailed, 0 skipped, 11 warnings in 8.00s |
| All four owner modules first, truncation afterward | 48 passed, 2 xfailed, 0 skipped, 11 warnings in 8.98s |
| Seed 1 | 48 passed, 2 xfailed, 0 skipped, 11 warnings in 9.01s |
| Seed 42 | 48 passed, 2 xfailed, 0 skipped, 11 warnings in 8.98s |
| Seed 2026 | 48 passed, 2 xfailed, 0 skipped, 11 warnings in 8.97s |

Exact executed commands:

```sh
/tmp/pr40-final-validation-venv/bin/python /tmp/odysseus-wave6-isolation-evidence/run_order.py normal after-normal tests/test_checkin_digest_owner_scope.py tests/test_database_test_isolation.py tests/test_document_session_owner_scope.py tests/test_gallery_owner_filter_single_user.py tests/test_manage_tasks_owner_scope.py tests/test_runtime_behavior_regressions.py tests/test_truncate_message_count_regression.py
/tmp/pr40-final-validation-venv/bin/python /tmp/odysseus-wave6-isolation-evidence/run_order.py reverse after-reverse tests/test_checkin_digest_owner_scope.py tests/test_database_test_isolation.py tests/test_document_session_owner_scope.py tests/test_gallery_owner_filter_single_user.py tests/test_manage_tasks_owner_scope.py tests/test_runtime_behavior_regressions.py tests/test_truncate_message_count_regression.py
/tmp/pr40-final-validation-venv/bin/python /tmp/odysseus-wave6-isolation-evidence/run_order.py normal after-truncation-first tests/test_truncate_message_count_regression.py tests/test_checkin_digest_owner_scope.py tests/test_database_test_isolation.py tests/test_document_session_owner_scope.py tests/test_gallery_owner_filter_single_user.py tests/test_manage_tasks_owner_scope.py tests/test_runtime_behavior_regressions.py
/tmp/pr40-final-validation-venv/bin/python /tmp/odysseus-wave6-isolation-evidence/run_order.py normal after-owners-first tests/test_checkin_digest_owner_scope.py tests/test_document_session_owner_scope.py tests/test_gallery_owner_filter_single_user.py tests/test_manage_tasks_owner_scope.py tests/test_truncate_message_count_regression.py tests/test_database_test_isolation.py tests/test_runtime_behavior_regressions.py
/tmp/pr40-final-validation-venv/bin/python /tmp/odysseus-wave6-isolation-evidence/run_order.py seed:1 after-seed1 tests/test_checkin_digest_owner_scope.py tests/test_database_test_isolation.py tests/test_document_session_owner_scope.py tests/test_gallery_owner_filter_single_user.py tests/test_manage_tasks_owner_scope.py tests/test_runtime_behavior_regressions.py tests/test_truncate_message_count_regression.py
/tmp/pr40-final-validation-venv/bin/python /tmp/odysseus-wave6-isolation-evidence/run_order.py seed:42 after-seed42 tests/test_checkin_digest_owner_scope.py tests/test_database_test_isolation.py tests/test_document_session_owner_scope.py tests/test_gallery_owner_filter_single_user.py tests/test_manage_tasks_owner_scope.py tests/test_runtime_behavior_regressions.py tests/test_truncate_message_count_regression.py
/tmp/pr40-final-validation-venv/bin/python /tmp/odysseus-wave6-isolation-evidence/run_order.py seed:2026 after-seed2026 tests/test_checkin_digest_owner_scope.py tests/test_database_test_isolation.py tests/test_document_session_owner_scope.py tests/test_gallery_owner_filter_single_user.py tests/test_manage_tasks_owner_scope.py tests/test_runtime_behavior_regressions.py tests/test_truncate_message_count_regression.py
```

The order driver is test-session-local; it is not installed into conftest or
production and never changes the normal suite's ordering. Its exact source
(for recreating `/tmp/odysseus-wave6-isolation-evidence/run_order.py`) is:

```python
import json
import os
from pathlib import Path
import random
import sys
import pytest

out = Path('/tmp/odysseus-wave6-isolation-evidence')
mode, label, *modules = sys.argv[1:]
class Order:
    @pytest.hookimpl(trylast=True)
    def pytest_collection_modifyitems(self, items):
        if mode == 'reverse':
            items.reverse()
        elif mode.startswith('seed:'):
            random.Random(int(mode.split(':')[1])).shuffle(items)
        (out / f'{label}-manifest.json').write_text(json.dumps([i.nodeid for i in items], indent=2) + '\n')
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
args = ['-q', '-p', 'no:cacheprovider', '-rsx', *modules]
(out / f'{label}-command.json').write_text(json.dumps({'argv':sys.argv,'pytest_args':args,'DATABASE_URL':os.environ['DATABASE_URL']},indent=2) + '\n')
raise SystemExit(pytest.main(args, plugins=[Order()]))
```

## Adjacent and complete validation

The first complete run finished with **44 failed, 12509 passed, 62 skipped,
2 xfailed**, 184 warnings and 6 passing subtests in 391.85s. Its failure
inventory was 42 missing-Playwright-package failures and two generated
configuration-reference freshness failures. The local worktree had not had
`npm ci` run; the generator includes test-source line references, and the
bootstrap edit moved the existing references by one line.

`npm ci --ignore-scripts` installed the four already-locked packages; package
and lock files were unchanged. Cached Chromium launched successfully
(version 151.0.7922.34). A bootstrap comment now explains why isolation must
precede collection and preserves the existing referenced line locations,
without editing the generated website or the generator. This follow-up is
commit `f67d0388fd805867a0920dbffd4da056b1361e38`
(`fix(tests): preserve bootstrap reference locations`).

```sh
npm ci --ignore-scripts
# exit 0; 4 packages installed, lockfile and package policy unchanged

python scripts/generate_env_reference.py --check
# exit 0; website/configuration-reference.md is up to date (112 variables)

/tmp/pr40-final-validation-venv/bin/python -m pytest -q -p no:cacheprovider tests/test_document_module_api.py tests/test_env_reference.py
# 16 passed, 1 warning in 17.00s
```

The first full run and the 44-case focused rerun are retained separately from
the final complete run. The 44-case rerun reported **1 failed, 43 passed**
in 73.61s: the existing font/color browser witness observed its font-size
icon still showing `13` after its text had changed to size 5 (expected `24`).
An isolated reproduction of that unchanged test passed in 2.13s. This is an
observed intermittent browser UI witness; no database failure was involved,
and a production root cause has not been established. The test and editor
implementation remain unchanged, with both observations retained rather
than suppressing the failed run. No failure was hidden by skipping or deleting a test.


```sh
/tmp/pr40-final-validation-venv/bin/python -m pytest -q -p no:cacheprovider -rsx tests/test_session_manager.py tests/test_session_manager_cleanup.py tests/test_session_manager_persist_guard.py tests/test_session_mutation_lookup.py tests/test_session_discovery_message_count.py tests/test_history_order_by_timestamp_regression.py tests/test_history_display_model_hydration.py tests/test_session_search.py tests/test_session_search_batch_fetch.py tests/test_session_list_owner_scope.py tests/test_session_owner_attribution.py tests/test_session_endpoint_owner_scope.py tests/test_session_concurrent.py tests/test_app_db_permissions.py tests/test_database_utcnow.py tests/test_tool_policy.py tests/test_turn_contract.py tests/test_chat_preprocess_tool_policy.py tests/test_chat_route_tool_policy.py tests/test_resend_message_nondestructive.py
# 1262 passed, 0 skipped, 0 xfailed, 7 warnings in 40.56s

/tmp/pr40-final-validation-venv/bin/python -m pytest -q -p no:cacheprovider -rsx
# 12556 passed, 59 skipped, 2 xfailed, 184 warnings, 6 subtests passed in 468.49s (0:07:48); exit 0

python -m compileall -q app.py core routes src services scripts tests
# exit 0

git diff --check
# exit 0, no output

git diff --check b1666951faf8285054e1ca90f11533b0fb53fb57
# exit 0, no output

git diff --name-only --diff-filter=U
# exit 0, no output

rg -n '^(<<<<<<< |=======$|>>>>>>> )' <each modified file>
# exit 1, no matches
```

No test was deleted, no skip was added, and no unrelated xfail was added. The
same two historical parameter cases remain xfailed for the demonstrated
production blocker, now restricted to that actual contract failure.

The isolation commit is
`e2b847c84d27ce785565757e81ca5293896eaab3`
(`fix(tests): isolate database and module state`). The final bounded commit
contains the repaired web witnesses and this validation report. Final commit,
HEAD, TREE and clean status are supplied in the accompanying final report to
avoid placing a commit's own hash inside its committed contents.

Full logs, commands, and per-run manifests from this session are in
`/tmp/odysseus-wave6-isolation-evidence/`.

The follow-up normal focused run after preserving bootstrap reference
locations is recorded in `after-bootstrap-followup.log`. It reported **48 passed, 2 xfailed**, 11 warnings in 9.55s. Its exact command is:

```sh
/tmp/pr40-final-validation-venv/bin/python /tmp/odysseus-wave6-isolation-evidence/run_order.py normal after-bootstrap-followup tests/test_checkin_digest_owner_scope.py tests/test_database_test_isolation.py tests/test_document_session_owner_scope.py tests/test_gallery_owner_filter_single_user.py tests/test_manage_tasks_owner_scope.py tests/test_runtime_behavior_regressions.py tests/test_truncate_message_count_regression.py
```

The additional browser observation came from the 44-case manifest retained in
`full-failures-manifest.json`; every exact node ID in that diagnostic command is
retained in `full-failures-rerun-command.json`. The isolated diagnostic command:

```sh
/tmp/pr40-final-validation-venv/bin/python -m pytest -q -p no:cacheprovider tests/test_document_rich_font_color_controls.py::test_numeric_font_size_and_custom_colors_work_on_desktop_and_mobile
# 1 passed, 1 warning in 2.13s
```

## Independent review disposition

A read-only review of isolation commit e2b847c8 raised two concerns, which
were checked against the frozen source rather than accepted as proven leaks:

- `core.models._SESSION_MANAGER_INSTANCE`: `SessionManager.__init__` only
  initializes its owned cache and loads metadata; it does not call the global
  setter. `SessionManager.add_message` explicitly persists through its own
  manager instead of calling `Session.add_message` / the singleton. Neither
  truncation witness nor the helper invokes a singleton setter or API route
  setup. Thus the asserted singleton mutation is absent from this lane's real
  seam. Resetting that unrelated singleton would add cleanup without a proven
  owned mutation and could hide a genuine leak elsewhere.
- Eager real-database import versus `clear_fake_database_modules`: the exact
  pre-import block already exists on frozen b1666951. The clearing helper
  intentionally leaves real modules with a string `__file__` intact and evicts
  replacement fake modules lacking it. The correction neither adds that
  pre-import nor changes fake-module identification. Its "real module" early
  return is intended behavior, not a newly introduced cleanup conflict.

Neither concern supplied a failing reproducer. Both were resolved by the
existing source paths and the actual collection/teardown identity regression;
no speculative global cleanup was introduced.

The minimized production reproduction command was:

```sh
DATABASE_URL=sqlite:///:memory: /tmp/pr40-final-validation-venv/bin/python - <<'PYTHON'
from src.agent_loop import _explicitly_avoids_web_lookup, _classify_agent_request, _web_search_unavailable_for_turn
from src.tool_policy import WEB_TOOL_NAMES
for text in (
    "Answer from memory only, don't search online.",
    'Summarise what you already know. Do not search the web.',
    'No web search please, just tell me what you know about Python decorators.',
):
    intent = _classify_agent_request([{'role': 'user', 'content': text}], text)
    domains = set(intent['domains'])
    print(repr(text))
    print('negative_web:', _explicitly_avoids_web_lookup(text))
    print('intent_domains:', sorted(domains))
    print('web_disabled_short_circuit:', _web_search_unavailable_for_turn(domains, set(WEB_TOOL_NAMES), text, None, None))
PYTHON
```

Results: negative-web detection true for all three; intent domains respectively
`['memory', 'web']`, `['web']`, `['web']`; short-circuit false, true, true.

## Final validation result and verdict

The final complete run in `full-pytest-final.log` exited 0:
**12556 passed, 59 skipped, 2 xfailed**, 184 warnings and 6 passing subtests in
468.49s. All 12617 collected cases are accounted for. The existing optional,
platform-specific and opt-in skips remain; no skip marker was added. Installing
the already-locked Node dependencies enabled three previously skipped cases,
so the skip count decreased from 62 in the first run to 59. No tests were
deleted and no unrelated xfail was introduced.

The font/color browser witness passed in the final complete run. Its failed
44-case diagnostic and passing isolated result remain documented as an
intermittent observation; no production root cause was established or fixed.

Database/environment/module isolation validation is green. Both historical
negative-web cases remain narrowly expected failures for a reproduced genuine
runtime defect outside the test-isolation boundary. These are integration
blockers; production intent/short-circuit behavior must be corrected in an
appropriate lane before removing their strict markers.

WAVE 6 TEST-ISOLATION FOUNDATION NOT READY
