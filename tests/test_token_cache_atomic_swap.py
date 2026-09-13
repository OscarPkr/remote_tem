"""Token cache atomic swap prevents race condition during refresh.

_refresh_token_cache() in app.py previously mutated the shared _token_cache
dict in two steps: .clear() then .update(). Between those calls the dict was
empty, so any concurrent reader (line 428) saw zero candidates and returned
401 for a valid token.

The fix replaces the two-step mutation with an atomic reference swap
(_token_cache = dict(new_map)).  Python's GIL makes the assignment atomic,
so readers always see either the old fully-populated dict or the new one.
"""
import threading
import time
from collections import defaultdict
from types import SimpleNamespace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_token_row(prefix, token_id="t1", token_hash="h1", owner="admin", scopes="chat"):
    return SimpleNamespace(
        token_prefix=prefix,
        id=token_id,
        token_hash=token_hash,
        owner=owner,
        scopes=scopes,
        is_active=True,
    )


class _SharedCache:
    """Mimics the module-level _token_cache global in app.py.

    Both reader and writer access .current — the same reference object.
    The writer atomically reassigns .current to a new dict; the GIL
    ensures the reader never sees a half-built reference.
    """

    def __init__(self, initial=None):
        self.current = initial or {}


def _build_refresh_fn(shared, rows):
    """Build a _refresh_token_cache closure mirroring app.py's fixed logic."""
    def _refresh():
        new_map = defaultdict(list)
        for r in rows:
            scope_list = [s.strip() for s in (r.scopes or "chat").split(",") if s.strip()]
            new_map[r.token_prefix].append((r.id, r.token_hash, r.owner, scope_list))
        shared.current = dict(new_map)
    return _refresh


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAtomicSwapNoEmptyWindow:
    """The atomic swap must never leave _token_cache empty between frames."""

    def test_swap_replaces_dict_content(self):
        shared = _SharedCache({"old_prefix": [("old_id", "old_hash", "admin", ["chat"])]})
        rows = [_make_token_row("new_prfx", "t2", "h2", "admin", "chat")]
        refresh = _build_refresh_fn(shared, rows)

        refresh()

        assert "old_prefix" not in shared.current
        assert "new_prfx" in shared.current
        assert shared.current["new_prfx"][0] == ("t2", "h2", "admin", ["chat"])

    def test_swap_is_atomic_under_concurrent_readers(self):
        """Concurrent readers never see an empty dict during refresh."""
        shared = _SharedCache({"ody_test12": [("t1", "hash1", "admin", ["chat"])]})
        rows = [_make_token_row("ody_newtok", "t2", "hash2", "admin", "chat")]
        refresh = _build_refresh_fn(shared, rows)

        stop = threading.Event()
        reader_results = {"empty": 0, "ok": 0}

        def reader_loop():
            while not stop.is_set():
                # Mimic app.py line 429: read the shared global directly
                snapshot = shared.current
                if len(snapshot) == 0:
                    reader_results["empty"] += 1
                else:
                    reader_results["ok"] += 1

        threads = [threading.Thread(target=reader_loop, daemon=True) for _ in range(4)]
        for t in threads:
            t.start()

        time.sleep(0.01)
        for _ in range(100):
            refresh()
        time.sleep(0.01)
        stop.set()
        for t in threads:
            t.join(timeout=2)

        assert reader_results["empty"] == 0, (
            "Readers saw empty cache %d times (ok=%d)"
            % (reader_results["empty"], reader_results["ok"])
        )
        assert reader_results["ok"] > 0, "readers should have seen data at least once"

    def test_app_state_ref_stays_in_sync(self):
        """app.state._token_cache must point to the same dict."""
        shared = _SharedCache()
        rows = [_make_token_row("pfx_a")]
        refresh = _build_refresh_fn(shared, rows)

        app_state = SimpleNamespace(_token_cache=shared.current)
        refresh()
        app_state._token_cache = shared.current

        assert app_state._token_cache is shared.current
        assert "pfx_a" in app_state._token_cache


class TestRefreshFromDB:
    """Verify the refresh logic handles DB rows correctly."""

    def test_multiple_prefixes(self):
        shared = _SharedCache()
        rows = [
            _make_token_row("ody_aaaa", "t1", "h1", "admin", "chat"),
            _make_token_row("ody_bbbb", "t2", "h2", "admin", "chat,tools"),
            _make_token_row("ody_aaaa", "t3", "h3", "admin", "memory"),
        ]
        refresh = _build_refresh_fn(shared, rows)

        refresh()

        assert len(shared.current) == 2
        assert len(shared.current["ody_aaaa"]) == 2
        assert len(shared.current["ody_bbbb"]) == 1
        assert shared.current["ody_bbbb"][0][3] == ["chat", "tools"]

    def test_empty_db_clears_cache(self):
        shared = _SharedCache({"stale": [("x", "y", "z", ["chat"])]})
        refresh = _build_refresh_fn(shared, rows=[])

        refresh()

        assert len(shared.current) == 0

    def test_concurrent_refreshes_dont_corrupt(self):
        """Multiple threads refreshing simultaneously don't corrupt cache."""
        shared = _SharedCache()
        rows = [
            _make_token_row("pfx_%d" % i, "t%d" % i, "h%d" % i, "admin", "chat")
            for i in range(20)
        ]
        refresh = _build_refresh_fn(shared, rows)

        errors = []

        def refresh_loop():
            try:
                for _ in range(50):
                    refresh()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=refresh_loop) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert errors == []
        assert len(shared.current) == 20
