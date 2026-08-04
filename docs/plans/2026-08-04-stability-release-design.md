# HA-Seoul-Bike Parser Stability and v1.3.0 Release Implementation Plan

> For agentic workers

- Use `superpowers:executing-plans` for task-by-task execution with checkpoints.

## Goal
- Restore parser stability for all public HTML/JSON parsing functions and align release metadata so tag/release validation is deterministic for `v1.3.0`.
- Keep runtime behavior untouched while making parser regressions and release metadata checks repeatable and evidence-first.
- Ensure release consistency checks do not break default `push` or `pull_request` CI on main.

## Architecture
- Preserve current integration runtime modules:
  - `custom_components/seoul_bike/coordinator.py`
  - `custom_components/seoul_bike/api.py`
  - `custom_components/seoul_bike/__init__.py`
- Add non-invasive regression tests under a new `tests/` tree that import parsing helpers directly from `coordinator.py` and `api.py`.
- Add one lightweight release-consistency check job in CI that runs only for tag/release-related triggers, separate from baseline validation.
- Drive all release evidence from one script using manifest version, git tag existence, and GitHub release existence.

## Tech Stack
- Python 3.12
- `pytest`
- Pytest fixtures with raw HTML/JSON snippets
- `gh` CLI (release check)
- Existing GitHub Actions workflow YAML

---

## Task 1: Add parser regression suite for `_extract_*`, `_parse_*`, and API helpers

### Files
- `tests/test_parser_regressions.py` (new)
- `custom_components/seoul_bike/coordinator.py` (no behavior change)
- `custom_components/seoul_bike/api.py` (no behavior change)

### Checklist
- [ ] Create `tests/test_parser_regressions.py` with deterministic fixtures for each regression target.
- [ ] Add tests for `coordinator._extract_favorites_with_counts`.
- [ ] Add tests for `coordinator._parse_use_history`.
- [ ] Add tests for `coordinator._extract_payment_history`.
- [ ] Add tests for `coordinator._extract_kcal_box`.
- [ ] Add tests for `coordinator._extract_voucher_end_from_realtime`.
- [ ] Add tests for `coordinator._parse_station_list`.
- [ ] Add tests for `coordinator._looks_like_login`.
- [ ] Add API helper coverage for `_normalize_cookie`, `_get_json`, and `_post_json`.
- [ ] Capture all tests into one file-level run command for TDD proof.

### Full pytest code
```python
import json
from unittest.mock import AsyncMock

from custom_components.seoul_bike import coordinator, api


def test_extract_favorites_with_counts():
    fav_html = """
    <div class="list">
      <li><a class="bike_name">Station 1</a><span class="count">2</span></li>
      <li><a class="bike_name">Station 2</a><span class="count">0</span></li>
    </div>
    """
    items = coordinator._extract_favorites_with_counts(fav_html)
    assert items == [
        {"name": "Station 1", "count": 2},
        {"name": "Station 2", "count": 0},
    ]


def test_parse_use_history():
    html = """
    <table id='history'>
      <tr><th>일자</th><th>자전거</th><th>금액</th></tr>
      <tr><td>2026-01-01</td><td>성공</td><td>1,000</td></tr>
    </table>
    <div class='kcal'>칼로리 45</div>
    """
    payload = coordinator._parse_use_history(html)
    assert isinstance(payload["history"], list)
    assert payload["history"][0]["use_at"] == "2026-01-01"
    assert payload["kcal"]["value"] == 45


def test_parse_station_list():
    text = '["A01","B01","C02"]'
    assert coordinator._parse_station_list(text) == ["A01", "B01", "C02"]


def test_extract_voucher_end():
    realtime = [
        {"couponName": "정기권", "endDate": "2026-12-31", "remaining": "00:10"},
        {"couponName": "일일권", "endDate": "2026-11-30", "remaining": "03:00"},
    ]
    assert coordinator._extract_voucher_end_from_realtime(realtime) == "2026-12-31"


def test_looks_like_login():
    assert coordinator._looks_like_login("<html><title>로그인</title></html>") is True
    assert coordinator._looks_like_login("<html><body>홈</body></html>") is False


def test_extract_payment_history():
    html = """
    <table class='payment'>
      <tr><th>날짜</th><th>금액</th></tr>
      <tr><td>2026-01-01</td><td>1000</td></tr>
    </table>
    """
    rows = coordinator._extract_payment_history(html)
    assert isinstance(rows, list)
    assert rows[0]["amount"] == 1000


def test_extract_kcal_box():
    html = "<div class='kcal'>소비 칼로리 120 칼로리</div>"
    info = coordinator._extract_kcal_box(html)
    assert info["raw"] == html
    assert info["value"] == 120


def test_parse_station_list_from_csv():
    text = "A01,B01,C02"
    assert coordinator._parse_station_list(text) == ["A01", "B01", "C02"]


def test_normalize_cookie():
    value = api._normalize_cookie("abc=1;  \t\n;  xyz=2")
    assert value == "abc=1;xyz=2"


class _DummyResponse:
    def __init__(self, data: dict):
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


async def test_get_json_contract():
    session = AsyncMock()
    session.get = AsyncMock(return_value=_DummyResponse({"ok": True}))
    client = api.SeoulBikeApi(session, "https://example.com", "x")
    data = await client._get_json("/api")
    assert data["ok"] is True
    session.get.assert_awaited_once()


async def test_post_json_contract():
    session = AsyncMock()
    session.post = AsyncMock(return_value=_DummyResponse({"ok": True}))
    client = api.SeoulBikeApi(session, "https://example.com", "x")
    data = await client._post_json("/api", {"a": "b"})
    assert data["ok"] is True
    session.post.assert_awaited_once()
```

### Full pytest command and expected result
- Command: `python -m pytest tests/test_parser_regressions.py -q`
- Expected before fix (RED): at least one failing test due missing `tests/` coverage.
- Expected after implementation (GREEN): `1 passed in ...` equivalent for file tests.

### Selective commit + Lore message
- Commit: `test: add Seoul Bike parser regression tests`
- Body:
  - `Constraint: no runtime behavior changes in coordinator/api modules`
  - `Rejected: changing parser implementations without contract tests`
  - `Confidence: high`
  - `Scope-risk: narrow`
  - `Directive: expand contract fixtures before touching parser internals`
  - `Tested: python -m pytest tests/test_parser_regressions.py -q`
  - `Not-tested: HA runtime boot and HACS certification path`

---

## Task 2: Add release contract test for manifest/tag/release parity

### Files
- `tests/test_release_consistency.py` (new)
- `manifest` data source: `custom_components/seoul_bike/manifest.json`
- `validate.yaml` (reference only; execution change in Task 3)

### Checklist
- [ ] Create `tests/test_release_consistency.py`.
- [ ] Parse `custom_components/seoul_bike/manifest.json` version as target semantic version.
- [ ] Verify `git tag --list "v{version}"` exists.
- [ ] Verify `gh release view "v{version}"` returns successfully when tag exists.
- [ ] Ensure all checks are explicit and not gated by branch status (only by release event context).

### Full pytest code
```python
import json
import subprocess
from pathlib import Path


MANIFEST_PATH = Path("custom_components/seoul_bike/manifest.json")


def test_release_contract_for_manifest_version():
    payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert payload["version"] == "1.3.0"
    assert payload["version"].startswith("1.")


def test_release_tag_exists_for_manifest():
    payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    version = payload["version"]
    tag = f"v{version}"
    result = subprocess.run(["git", "tag", "--list", tag], check=True, capture_output=True, text=True)
    assert result.stdout.strip() == tag


def test_release_exists_for_manifest_tag():
    payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    tag = f"v{payload['version']}"
    result = subprocess.run(["gh", "release", "view", tag], capture_output=True, text=True)
    assert result.returncode == 0
```

### Full GitHub Actions script code
```yaml
  validate-release-contract:
    runs-on: ubuntu-latest
    if: startsWith(github.ref, 'refs/tags/v')
    steps:
      - uses: actions/checkout@v4
      - name: Run parser and release contract tests
        run: |
          python -m pytest tests/test_parser_regressions.py tests/test_release_consistency.py -q
```

### Full pytest command and expected result
- Command: `python -m pytest tests/test_release_consistency.py -q`
- Expected before fix (RED): fail if tag `v1.3.0` does not exist.
- Expected after fix (GREEN): all assertions pass.

### Selective commit + Lore message
- Commit: `test: add release manifest-tag-release parity checks`
- Body:
  - `Constraint: release check must be independent of main branch and PR events`
  - `Rejected: gate existing validate.yaml on all push events`
  - `Confidence: high`
  - `Scope-risk: narrow`
  - `Directive: keep release contract checks tied to explicit release context only`
  - `Tested: python -m pytest tests/test_release_consistency.py -q`
  - `Not-tested: GitHub release content review UI`

---

## Task 3: Attach release contract job to CI without breaking default validation

### Files
- `.github/workflows/validate.yaml` (modify)

### Checklist
- [ ] Add `validate-release-contract` job conditioned by tags and manual dispatch.
- [ ] Add `workflow_dispatch` trigger for explicit pre-release checks.
- [ ] Add release-only `if:` guard in release job and keep current `validate-hacs` and `validate-hassfest` untouched.
- [ ] Keep all baseline validation jobs unchanged for `push` and `pull_request`.

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
      - name: Install dependencies
        run: python -m pip install --upgrade pip
      - name: Run release contract tests
        run: python -m pytest tests/test_release_consistency.py -q
```

### Full command and expected result
- Command: `python -m pytest tests/test_release_consistency.py -q`
- Expected before fix (RED): fail on branch-only runs is avoided because job is not active there.
- Expected after fix (GREEN): returns pass on tag or dispatch runs when manifest/tag/release contract is valid.

### Selective commit + Lore message
- Commit: `ci: add tag-gated release consistency check`
- Body:
  - `Constraint: existing validate jobs must keep current baseline behavior on PR and branch push`
  - `Rejected: forcing release-contract failure into every PR`
  - `Confidence: high`
  - `Scope-risk: moderate`
  - `Directive: do not gate hacs/hassfest jobs on manifest/release state`
  - `Tested: yaml lint by review + python -m pytest tests/test_release_consistency.py -q`
  - `Not-tested: full GitHub Actions concurrency and environment permissions`

---

## Task 4: Prepare release proof and changelog consistency for v1.3.0

### Files
- `docs` release notes section (existing)
- `custom_components/seoul_bike/manifest.json` (confirm `1.3.0` already set)
- `README.md`
- `docs/plans/2026-08-04-stability-release-design.md`

### Checklist
- [ ] Verify manifest version is `1.3.0` and immutable for this release.
- [ ] Add a short release proof block in README or docs noting that tag/release parity is enforced by CI.
- [ ] Add a handoff note that no runtime logic is changed in this release.
- [ ] Record exact release commands for manual execution.

### Full proof block snippet (example to include)
```markdown
## Release proof (v1.3.0)

- Manifest: `custom_components/seoul_bike/manifest.json` version `1.3.0`
- Tag check: `git tag -l v1.3.0` returns `v1.3.0`
- Release check: `gh release view v1.3.0` succeeds
- CI check: `python -m pytest tests/test_parser_regressions.py tests/test_release_consistency.py -q`
```

### Commands and expected result
- Command: `git tag --list v1.3.0`
- Expected PASS: output includes `v1.3.0`
- Command: `gh release view v1.3.0`
- Expected PASS: exit code `0` and release body exists
- Command: `python -m pytest tests/test_parser_regressions.py tests/test_release_consistency.py -q`
- Expected PASS: all tests pass

### Selective commit + Lore message
- Commit: `docs: add v1.3.0 release proof and release instructions`
- Body:
  - `Constraint: preserve existing user-facing behavior and integration API`
  - `Rejected: changing firmware or coordinator runtime paths`
  - `Confidence: medium`
  - `Scope-risk: narrow`
  - `Directive: keep release proof aligned with exact test command outcomes`
  - `Tested: python -m pytest tests/test_parser_regressions.py tests/test_release_consistency.py -q`
  - `Not-tested: manual manual-test app flows after release`
