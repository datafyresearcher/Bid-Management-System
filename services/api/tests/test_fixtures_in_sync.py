"""The fixture tree is duplicated for deployment reasons, and the copies must
not drift apart.

`fixtures/` at the repository root is the canonical copy: docker-compose mounts
it into the API container. `services/api/fixtures/` is a second copy that ships
inside the Docker image and inside the Vercel function bundle.

When the two drift, the deployed API quietly serves a different set of notices
than local development — and, worse, serves stale notice URLs that point at
pages which no longer exist. That failure is invisible until someone follows a
link, so it is caught here instead.
"""

from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parents[1]
CANONICAL = REPO_ROOT / "fixtures"
DEPLOYED = API_ROOT / "fixtures"


def _files(root: Path):
    return {p.relative_to(root).as_posix(): p for p in root.rglob("*") if p.is_file()}


def test_both_fixture_copies_exist():
    assert CANONICAL.is_dir(), f"missing canonical fixtures: {CANONICAL}"
    assert DEPLOYED.is_dir(), f"missing deployed fixtures: {DEPLOYED}"


def test_fixture_copies_are_in_sync():
    canonical = _files(CANONICAL)
    deployed = _files(DEPLOYED)

    missing = sorted(set(canonical) - set(deployed))
    assert not missing, f"files present in {CANONICAL} but not in {DEPLOYED}: {missing}"

    extra = sorted(set(deployed) - set(canonical))
    assert not extra, f"files present in {DEPLOYED} but not in {CANONICAL}: {extra}"

    differing = [
        name for name, path in canonical.items() if path.read_bytes() != deployed[name].read_bytes()
    ]
    assert not differing, (
        "fixture copies have drifted. Copy "
        f"{CANONICAL} over {DEPLOYED} — a stale copy ships wrong notice links.\n"
        f"differing: {sorted(differing)}"
    )
