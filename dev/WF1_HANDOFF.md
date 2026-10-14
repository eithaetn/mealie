# WF1 team handoff

Reviewed on 2026-10-14. WF1 is ready for coordinated code review and continuation,
but the FastAPI-to-DRF migration is incomplete. Integration with W2 requires an
explicit choice of Django configuration and dependency version. LDAP, PostgreSQL,
browser, and production deployment validation remain outstanding.

## Repository and delivery state

Checkpoint note: the owner has authorized a local checkpoint containing all the
reviewed WF1 code, portability fixes, inventory, and this report. The repository
state and "uncommitted" labels below describe the review immediately before that
checkpoint. Use the commit containing this report for the complete snapshot;
`531b1183b` alone does not include it. Publishing and integration remain unapproved.

| Item | Verified value |
| --- | --- |
| Workspace | `C:\Users\DELL\mealie-wf1` |
| Current branch | `rewrite/w1-direct-prompt` |
| Fetch and push remote | `origin`: `https://github.com/eithaetn/mealie.git` |
| Target | `mealie-next` at `63cf7468f39f2d7f4b3bad2c3fb9141a246c917e` |
| WF1 HEAD | `531b1183b19d910ec118b20259d3ee6050bfcfcc` |
| WF1 ancestry | 2 commits ahead, 0 behind the verified target |
| Local checkpoints | `b3ddcf6c6` (initial partial migration), `531b1183b` (group self-service) |
| Remote WF1 branch | No `refs/heads/rewrite/w1-direct-prompt` returned by live `ls-remote` |
| W2 | [PR #1: add DRF public about API pilot](https://github.com/eithaetn/mealie/pull/1), open, targeting `mealie-next` |
| W2 head | `migration/fastapi-to-drf-w2` at `381a6a366c6bac2681e2e98080e1f2eaef4f3352`, 4 commits beyond the common base |

GitHub's live branch tips and PR metadata matched the existing local remote refs;
no fetch or branch update was needed. The working tree initially contained 18
uncommitted files: 9 tracked modifications and 9 untracked files. Nothing was
staged. This report adds one file. Those uncommitted changes, including household
and invitation support, are **not contained in the checkpoint commits** and are
not yet available for teammates to fetch.

During the handoff review, no commit, push, merge, rebase, reset, PR creation, or
trial merge was performed. The subsequently authorized local checkpoint is the
only repository-history change in this handoff delivery.
Overlap findings below are from ancestry, changed-file comparisons, and source
review, not a claim that an integration merge has been tested.

## Completed implementation

The public server entry point remains `mealie.app:app`, launched by `task py`.
`DjangoAPIMiddleware` dispatches converted path/method pairs into DRF. FastAPI
continues serving other operations, lifecycle hooks, documentation, and the
production SPA. Existing locale, CORS, compression, and session middleware wrap
both API implementations. Unsupported methods and trailing-slash routing retain
the existing FastAPI behavior through fallback.

SQLAlchemy repositories and Alembic retain database ownership. Pydantic schemas,
camelCase serialization, pagination envelopes, and existing frontend API paths
are retained. There are no WF1 database-model, Alembic migration, Pydantic schema,
or frontend generated-type changes relative to the target.

| Native DRF functionality | Delivery state |
| --- | --- |
| Public about, startup information, and cached theme | Committed |
| Password login, refresh, logout; browser and native OIDC flows | Committed |
| Bearer/cookie authentication, API-token verification and revocation, login lockout, OIDC state/PKCE/nonce checks | Committed; LDAP provider execution still requires its dependency |
| Registration, forgotten/reset password, current user, user update/password, API-token creation/deletion, profile image | Committed |
| User ratings and favorites | Committed |
| Admin about, statistics, and checks | Committed |
| Group self, preferences, storage, member list/detail, household list/detail | Committed |
| Household self, recipe summary, members, preferences, permissions, statistics | Uncommitted |
| Invitation token list/create and invitation email | Uncommitted |

Group/household work preserves repository scoping and permission checks.
Household member lists require `can_manage`; preference writes require
`can_manage_household`. Permission changes reject other-household targets and
self-escalation. Public user responses filter private fields. Invitations retain
admin-only listing, `can_invite`, password-login gating, and restrictions on
non-admin creation for other groups/households. Email tests mock delivery.

The shared base handles legacy validation/error envelopes, JSON rendering,
SQLAlchemy session cleanup, and multipart parsing. Request schemas and service
logic remain reusable by the retained FastAPI declarations.

## Uncommitted-change review

All 18 existing files were inspected, including the untracked implementations,
tests, and inventory. No blocking correctness or permission regression was found
within the reviewed scope. Passing tests support that finding; they do not close
the environment and deployment gaps below.

| Files | Review finding |
| --- | --- |
| `mealie/drf/urls.py`, `household_views.py`, `invitation_views.py` | Registers 10 additional method/path operations using the authenticated base, existing schemas, and aliased responses |
| `mealie/services/household_services/household_self_service.py`, `invitation_service.py` | Matches legacy checks and repository scoping; preserves response and error contracts |
| `tests/integration_tests/test_drf_households.py` | 32 cases cover legacy parity, authentication, validation, tenant isolation, permission escalation, invitation guards, mocked email, and native dispatch |
| `mealie/pkgs/i18n/json_provider.py`, `mealie/services/migrations/tandoor.py` | Explicit UTF-8 reads fix pre-existing Windows failures; no locale files edited |
| `tests/unit_tests/pkgs/i18n/test_locale_provider.py`, `services_tests/scraper_tests/test_cleaner.py`, `services_tests/test_recipe_import_workflow.py` | Unicode coverage and explicit UTF-8 fixture/source reads |
| `tests/unit_tests/services_tests/scheduler/tasks/test_purge_group_exports.py`, `test_config.py`, `pkgs/safehttp/conftest.py` | Portable temporary-file/path assertions and a supported Windows selector loop; SSRF assertions and warnings-as-errors retained |
| `tests/unit_tests/test_security.py`, `test_token_security.py` | Six token/file-access tests separated from LDAP imports; all 21 existing test/helper definitions preserved exactly by AST comparison; LDAP tests remain enabled |
| `dev/drf_inventory.py`, `dev/drf-inventory.json` | Reproducible operation/import inventory; stale import locations refreshed and one formatter finding corrected during this review |

Test paths abbreviated in the table share the stated `tests/unit_tests/` root.
This review changed only inventory formatting/data and added this report; it did
not change application behavior.

## Remaining migration work

The refreshed [inventory](drf-inventory.json) contains every documented method/path
pair and every direct FastAPI import location. There are **48 DRF operations and
218 FastAPI operations** out of 266. These are operation counts, not unique URL
counts. Legacy declarations for migrated operations still exist for OpenAPI and
fallback handling, so a DRF count does not imply their FastAPI imports are gone.

| Remaining API domain | Operations | Main areas |
| --- | ---: | --- |
| Households | 54 | Cookbooks, events, meal plans, recipe actions, shopping, webhooks |
| Groups | 19 | AI providers, labels, migrations, reports, seeders |
| Recipes | 44 | CRUD, creation/import, bulk actions, exports, sharing, suggestions, timeline |
| Organizers | 22 | Categories, tags, tools |
| Shared | 4 | Public shared recipes |
| Comments | 5 | CRUD |
| Parser | 2 | Ingredient parsing |
| Foods | 6 | CRUD and merge |
| Units | 6 | CRUD and merge |
| Admin | 35 | Users, groups, households, backups, debug, email, maintenance |
| Explore | 15 | Public group exploration |
| Media | 5 | Docker, recipe, and user media |
| Utils | 1 | File download |
| **Total** | **218** | |

There are also 203 direct FastAPI import sites across 180 Python files, including
tests and compatibility helpers. Final removal must address `mealie/app.py`,
startup/shutdown, middleware ownership, OpenAPI/code generation, production
SPA/static serving, CI import checks, compatibility exceptions/encoders, tests,
and dependency/lockfile cleanup. These are separate from the 218 operations.

Teammates can build against the existing API contracts now. They must continue
using the combined server until those remaining responsibilities are migrated.

## W2 overlap and integration risks

W2 source was reviewed at the exact PR head above. It adds `mealie/drf_api`, three
test modules, a migration document, and Django/DRF dependencies. It leaves the
normal FastAPI server entry point unchanged and is a standalone public-API pilot.
Its document reports 3,196 passing tests and 18 skips; that result was not rerun
here and is not validation of a combined WF1/W2 implementation.

Only **`pyproject.toml` and `uv.lock`** overlap by changed filename between W2 and
the complete WF1 working tree relative to the common base. Semantic overlap is
larger because the implementations live in different packages:

| Area | WF1 | W2 | Integration decision needed |
| --- | --- | --- | --- |
| Public endpoints | `mealie/drf/views.py` and `AppInfoService` | `mealie/drf_api/views.py` | Both implement GET `/api/app/about`, `/startup-info`, and `/theme` under that prefix; retain one implementation |
| Django package/configuration | `mealie.drf.settings` | `mealie.drf_api.settings` | One process has one active Django settings module; both ASGI modules use `setdefault`, so initialization order matters |
| Django dependency | `Django==5.2.17` | `django==6.1.1` | Select one tested version; names are the same normalized dependency |
| DRF dependency | `3.18.1` | `3.18.1` | Retain a single declaration |
| Lockfile | Revision 3 | Revision 5 | Regenerate/validate once with the team's agreed uv version after choosing dependencies; do not concatenate lockfile edits |
| Permissions | Protected default; explicit public views | `AllowAny` pilot default | Preserve WF1's protected defaults when consolidating settings |
| HTTP behavior | Custom JSON negotiation/rendering; redirects/method fallback in outer server | Default JSON renderer; explicit Django redirect views | Validate through the actual production entry point |
| Deployment hosts | Existing outer-server behavior, Django `ALLOWED_HOSTS=["*"]` | Localhost/testserver-only Django hosts | Confirm the intended proxy/host policy during deployment testing |
| Tests | Combined ASGI contract and security tests | Django `Client`, W2 module monkeypatches | Adapt tests to the chosen package and actual dispatch path |

Do not simply append W2 tests unchanged: their `DJANGO_SETTINGS_MODULE` calls use
`setdefault`, so WF1's earlier initialization can redirect them to WF1 instead.
Their session-failure injection patches W2's `views.get_repositories`, which
would not affect WF1's service. Likewise, `api_client` on WF1 already dispatches
converted requests to DRF; comparing it to another DRF client is not an independent
legacy comparison. Keep explicit reference-router tests and native-dispatch checks.

W2's real-database privacy matrix, session-cleanup tests, redirect query-preservation
checks, and cache/method checks are useful coverage to preserve when porting.
Some overlap with WF1's existing isolated tests; consolidate without losing cases.

## Validation evidence and limits

Environment: Windows, Python 3.14.7, uv 0.12.13, SQLite, Django 5.2.17, DRF 3.18.1.
The local venv lacks `python-ldap` and the PostgreSQL extra. NLTK's English tagger
was downloaded to `%TEMP%\mealie-nltk-data`; runs set `NLTK_DATA` accordingly.

| Check | Result |
| --- | --- |
| Most recent full regression, before this documentation review | **3,353 passed, 0 failed, 18 skipped, 1 collection error**, 399.54 seconds |
| Fresh handoff-focused run | **376 passed, 9 skipped**, covering DRF/auth/user/group/household, token security, Unicode, safe HTTP, config, export purge, and NLP |
| Fresh isolated DRF contracts (`tests/drf`) | **27 passed** |
| Ruff lint and format on all 17 uncommitted Python files | Passed after formatting the inventory helper |
| Mypy on 7 changed/new implementation/helper files | Passed |
| `git diff --check` | Passed; Git reports the existing LF-to-CRLF policy notice |

The full run used `pytest tests --continue-on-collection-errors --tb=short` with
`PYTHONUTF8=0` and the NLTK dataset configured. Its exit status is **1**, because
`tests/unit_tests/test_security.py` cannot import `ldap`; this is not a green full
suite. No tests were disabled to obtain the result. The 18 existing skips are
9 LDAP-service cases, 7 long-running scraper/parser cases, and 2 PostgreSQL-extra
cases. Separating token tests restored six checks that the missing LDAP import
had previously prevented from collecting.

The original 87 failures came from UTF-8/CP1252 decoding (66), missing NLTK data
(16), the Windows curl event loop (3), and temporary-file/path assumptions (2).
The encoding collection error was also fixed. Representative failures reproduced
at the checkpoint and the implicated production code matched the pre-migration
base. No DRF-specific regression was identified in that investigation.

Local logs remain outside Git in `%TEMP%`: `mealie-wf1-regression.log` (original),
`mealie-wf1-regression-after-fixes.log` (full rerun), and
`mealie-wf1-handoff-tests.log` (fresh focused run). They have not been uploaded.

Outstanding validation: install/build `python-ldap` and run its unit tests plus
live-service tests; run the PostgreSQL matrix; run frontend lint/tests and browser
smoke tests; test the production container/SPA, proxy root path and HTTPS cookies,
real OIDC provider and SMTP delivery. New email tests use mocks. Full-project
type/format/lockfile CI gates and the combined WF1/W2 result are not certified by
the targeted checks above. The request schemas were unchanged, so no schema
generation was required in this pass.

## Teammate setup

1. Obtain the complete WF1 snapshot only after the owner approves publishing it.
   Fetching the shared target or using `531b1183b` alone omits the uncommitted work.
2. Prefer the repository's Linux dev container for a complete environment. It
   provides Python 3.14, uv, Task, and native build dependencies including
   `build-essential`, `libpq-dev`, `libsasl2-dev`, `libldap2-dev`, and `libssl-dev`.
   Native Windows setup currently cannot reproduce LDAP coverage in this venv.
3. Use the selected branch's lockfile. `Taskfile.yml` sets `UV_FROZEN=1`; its setup
   installs the dev group and PostgreSQL extra. Do not resolve a new Django version
   just to install the existing snapshot.

From the repository root in the Linux dev environment:

```sh
task setup
export UV_FROZEN=1
export NLTK_DATA="$PWD/.venv/nltk_data"
uv run --frozen python -m nltk.downloader -e -d "$NLTK_DATA" averaged_perceptron_tagger_eng
```

Without Task, the Python dependency equivalent is
`uv sync --frozen --group dev --extra pgsql`. Frontend dependencies are installed
by `task setup:ui`. Keep the NLTK environment variable set for tests and the server.

Use separate terminals for `task dev:services` (PostgreSQL/Mailpit when needed),
`task py` (backend port 9000), and `task ui` (frontend port 3000). Use
`task py:postgres` to exercise PostgreSQL. Retain existing application secrets,
database configuration, and data volumes when testing compatibility on a disposable
copy of existing data. The migration introduces no Django ORM database and needs
no Django `migrate` command; normal Mealie/Alembic initialization remains in place.

If switching from W2, clear a previously exported `DJANGO_SETTINGS_MODULE` or set
it to `mealie.drf.settings` for WF1. Launch the complete `mealie.app` server via
`task py`: directly serving `mealie.drf.asgi:application` omits the outer lifecycle,
middleware, fallback APIs, and SPA responsibilities still required by this snapshot.

Useful validation commands after dependencies and test services are available:

```sh
uv run --frozen pytest --confcutdir=tests/drf tests/drf
uv run --frozen pytest tests/integration_tests/test_drf_groups.py tests/integration_tests/test_drf_households.py tests/integration_tests/test_drf_security.py tests/integration_tests/test_drf_oidc.py tests/integration_tests/test_drf_registration.py tests/integration_tests/user_tests tests/unit_tests/test_token_security.py
task py:test
task ui:check
```

Use the SQLite/PostgreSQL and LDAP service configuration in
`.github/workflows/test-backend.yml` for the complete matrix. Supply NLTK data as
above. Run the full `task py:check` gate before integration; it includes formatting
and can modify files, so inspect its diff. Independent pytest processes must not
share the same test data directory; the existing xdist fixtures isolate workers.

To refresh the handoff inventory without initializing a database:

```sh
TESTING=true PRODUCTION=true uv run --frozen python dev/drf_inventory.py --output dev/drf-inventory.json
```

For this already-provisioned Windows venv only, diagnostic runs use
`uv --cache-dir "$env:TEMP/mealie-uv-cache" run --no-sync ...` and set
`$env:NLTK_DATA="$env:TEMP/mealie-nltk-data"`. `--no-sync` avoids reinstalling
missing native dependencies; it is not a replacement for a complete teammate setup.

## Recommended integration sequence (not executed)

1. Agree with the W2 owner on one Django package, server entry point, dependency
   version, and public-endpoint owner. The lowest-change option is WF1's wired
   `mealie.drf` foundation with its tested 5.2.17 pin, incorporating W2's useful
   coverage. Treat choosing Django 6.1.1 instead as a separately tested upgrade.
2. After explicit owner approval, checkpoint the reviewed uncommitted work in
   reviewable groups: household/invitation migration, portability/test fixes, and
   inventory/handoff documentation. Preserve the existing two checkpoints and
   attribution for W2 work. Publish the branch only with separate authorization.
3. After integration approval, use an isolated integration checkout based on a
   freshly verified `mealie-next`. Reconcile W2 intentionally; do not combine the
   two Django configurations or duplicate dependency declarations unchanged.
   Resolve the manifest first, then generate one consistent lockfile using the
   agreed uv version and run the repository lockfile check.
4. Port W2 coverage to the chosen request path and service injection points. Run
   both implementations' contract cases, tenant/permission tests, token revocation,
   OIDC checks, and database-session cleanup tests. Do not replace protected
   permission defaults with the public pilot's `AllowAny` default.
5. Require clean full regression/CI results with LDAP and PostgreSQL, frontend
   checks, and production smoke tests before merging into the shared target.
   Preserve database/volume backups and validate against a disposable data copy.
6. Assign the remaining 218 operations and runtime responsibilities by domain,
   using the inventory as the shared checklist. Team members can continue from
   this partial handoff; it must not be labelled a completed FastAPI removal or
   production cutover.

All repository-changing integration steps above remain subject to owner approval.
