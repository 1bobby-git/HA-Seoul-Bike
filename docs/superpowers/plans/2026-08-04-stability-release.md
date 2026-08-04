# HA-Seoul-Bike Parser Stability and v1.3.0 Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` to execute this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stabilize parser behavior and enforce release metadata parity (`manifest.version`, `v{version}` tag, GitHub release) for `1.3.0` with no runtime behavior changes.

**Architecture:** Keep existing runtime modules as-is and add test-first coverage around parser helpers (`coordinator.py`, `api.py`) and one release-gated CI lane that does not run on normal branch push.

**Tech Stack:** pytest, Python stdlib (`subprocess`, `json`, `pathlib`), Home Assistant repository validator jobs, GitHub CLI.

---

## Task 1: Add parser regression tests for coordinator helpers

### Files
- `tests/test_parser_regressions.py` (new)
- `custom_components/seoul_bike/coordinator.py` (no behavior edits)
- `custom_components/seoul_bike/api.py` (no behavior edits)

### Checklist
- [ ] Add assertions for `_extract_favorites_with_counts`.
- [ ] Add assertions for `_parse_use_history`.
- [ ] Add assertions for `_extract_payment_history`.
- [ ] Add assertions for `_extract_kcal_box`.
- [ ] Add assertions for `_extract_voucher_end_from_realtime`.
- [ ] Add assertions for `_parse_station_list`.
- [ ] Add assertions for `_looks_like_login`.
- [ ] Add assertions for `_normalize_cookie`, `_get_json`, and `_post_json`.

### Full pytest code
```python
import json
from unittest.mock import AsyncMock

from custom_components.seoul_bike import coordinator, api


def test_extract_favorites_with_counts():
    html = '''
    <div class='list'>
      <li><a class='bike_name'>A</a><span class='count'>3</span></li>
      <li><a class='bike_name'>B</a><span class='count'>0</span></li>
    </div>
    '''
    assert coordinator._extract_favorites_with_counts(html) == [
        {"name": "A", "count": 3},
        {"name": "B", "count": 0},
    ]


def test_parse_use_history_and_kcal_box():
    html = '''
    <table id='history'>
      <tr><td>2026-01-01</td><td>1,000</td></tr>
    </table>
    <span class='kcal'>소비 칼로리 77</span>
    '''
    parsed = coordinator._parse_use_history(html)
    assert parsed["kcal"]["value"] == 77


def test_extract_payment_and_station_and_voucher():
    payment_html = '''<table class='payment'><tr><td>1000</td></tr></table>'''
    assert coordinator._extract_payment_history(payment_html)[0]["amount"] == 1000

    assert coordinator._parse_station_list('["A1","B2"]') == ["A1", "B2"]

    realtime = [{"couponName": "일일권", "endDate": "2026-12-31", "remain": "00:10"}]
    assert coordinator._extract_voucher_end_from_realtime(realtime) == "2026-12-31"


def test_looks_like_login():
    assert coordinator._looks_like_login("<title>로그인</title>")
    assert not coordinator._looks_like_login("<div>home</div>")


def test_normalize_cookie():
    assert api._normalize_cookie("  a=1;  b=2;;") == "a=1;b=2"


class _Dummy:
    def __init__(self, data):
        self._data = data
        self.status = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self):
        return self._data

    def raise_for_status(self):
        pass


async def test_api_get_json_contract():
    session = AsyncMock()
    session.get = AsyncMock(return_value=_Dummy({"ok": True}))
    c = api.SeoulBikeApi(session, "https://example.com", "cookie")
    payload = await c._get_json("/api")
    assert payload == {"ok": True}


async def test_api_post_json_contract():
    session = AsyncMock()
    session.post = AsyncMock(return_value=_Dummy({"ok": True}))
    c = api.SeoulBikeApi(session, "https://example.com", "cookie")
    payload = await c._post_json("/api", {"x": 1})
    assert payload == {"ok": True}
```

### Commands + expected result
- `python -m pytest tests/test_parser_regressions.py -q` → **FAIL** before adding file, **PASS** after merge.

### Selective commit + Lore
- Commit: `test: add parser regression tests for Seoul Bike`
- `Constraint: keep parser behavior unchanged by test-only introduction`
- `Rejected: changing coordinator runtime code before contract failures are visible`
- `Confidence: high`
- `Scope-risk: narrow`
- `Directive: extend fixtures before touching parsing implementation`
- `Tested: python -m pytest tests/test_parser_regressions.py -q`
- `Not-tested: Home Assistant runtime update flow`

---

## Task 2: Add release contract tests for manifest/tag/release parity

### Files
- `tests/test_release_consistency.py` (new)

### Checklist
- [ ] Read `custom_components/seoul_bike/manifest.json` and assert `version == "1.3.0"`.
- [ ] Verify matching git tag `v1.3.0` exists.
- [ ] Verify `gh release view v1.3.0` succeeds.
- [ ] Keep this task independent of runtime tests.

### Full pytest code
```python
import json
import subprocess
from pathlib import Path


def test_manifest_version_is_130():
    manifest = json.loads(Path("custom_components/seoul_bike/manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == "1.3.0"


def test_git_tag_exists():
    result = subprocess.run(["git", "tag", "--list", "v1.3.0"], check=True, capture_output=True, text=True)
    assert "v1.3.0" in result.stdout


def test_github_release_exists():
    result = subprocess.run(["gh", "release", "view", "v1.3.0"], capture_output=True, text=True)
    assert result.returncode == 0
```

### Commands + expected result
- `python -m pytest tests/test_release_consistency.py -q` → **FAIL** on missing tag/release contract, **PASS** when all three checks pass.

### Selective commit + Lore
- Commit: `test: add v1.3.0 release contract tests`
- `Constraint: release check must not run for every non-release branch push`
- `Rejected: merging this test into existing PR-gated validation`
- `Confidence: high`
- `Scope-risk: narrow`
- `Directive: ensure any future release bump updates this contract in one place`
- `Tested: python -m pytest tests/test_release_consistency.py -q`
- `Not-tested: release assets integrity on CDN`

---

## Task 3: Add tag-gated workflow job (no main CI regression)

### Files
- `.github/workflows/validate.yaml`

### Checklist
- [ ] Add `workflow_dispatch` and tag push (`v*`) to this file.
- [ ] Add `validate-release-contract` with tag/dispatch guard.
- [ ] Keep `validate-hacs` and `validate-hassfest` untouched.
- [ ] Verify job does not run on branch push by default.

### Full CI script code
```yaml
on:
  push:
    tags:
      - "v*"
  pull_request:
  workflow_dispatch:

jobs:
  validate-hacs:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: HACS validation
        uses: hacs/action@main
        with:
          category: integration

  validate-hassfest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Hassfest validation
        uses: home-assistant/actions/hassfest@master

  validate-release-contract:
    if: |
      github.event_name == 'workflow_dispatch' || startsWith(github.ref, 'refs/tags/v')
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run release checks
        run: python -m pytest tests/test_release_consistency.py -q
```

### Commands + expected result
- `python -m pytest tests/test_release_consistency.py -q` → **PASS** in tag run if `v1.3.0` release chain is valid.
- PR push without tag: workflow should execute only validation jobs; release-contract job is skipped by condition.

### Selective commit + Lore
- Commit: `ci: run release-consistency job only for tags/manual triggers`
- `Constraint: cannot break default PR/branch validation path`
- `Rejected: changing validation jobs to require release checks`
- `Confidence: high`
- `Scope-risk: moderate`
- `Directive: keep release checks isolated and explicit`
- `Tested: pytest and workflow syntax review`
- `Not-tested: GitHub Actions on release event execution in production`

---

## Task 4: Add release proof notes for v1.3.0 in docs

### Files
- `README.md`

### Checklist
- [ ] Add a short, concrete release proof block that references manifest, tag, and release checks.
- [ ] Record exact validation command sequence for traceability.
- [ ] Ensure no conflicting release version strings are introduced in visible docs.

### Full proof block snippet
```markdown
### v1.3.0 Stability + Release Proof

- manifest: `custom_components/seoul_bike/manifest.json` → `1.3.0`
- tag: `v1.3.0`
- release: `gh release view v1.3.0`
- checks:
  - `python -m pytest tests/test_parser_regressions.py -q`
  - `python -m pytest tests/test_release_consistency.py -q`
```

### Commands + expected result
- `python -m pytest tests/test_parser_regressions.py tests/test_release_consistency.py -q` → **PASS** before release handoff.
- `git tag --list v1.3.0` → includes `v1.3.0`.
- `gh release view v1.3.0` → returns exit code `0`.

### Selective commit + Lore
- Commit: `docs: add v1.3.0 parser stability release proof block`
- `Constraint: user-facing release text must match test and tag truth`
- `Rejected: release notes without executable proof`
- `Confidence: medium`
- `Scope-risk: narrow`
- `Directive: mirror any future version bump with proof block update`
- `Tested: command checks above`
- `Not-tested: end-user acceptance testing in production`
