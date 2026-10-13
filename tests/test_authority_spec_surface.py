"""Spec-surface admission: the strict router picks the tools after authority is
built, so spec turns admit the router's families; compact/full stay unchanged."""
import json

from src.agent_runtime.authority import create_request_authority, ExactOperation


def _permits(auth, tool, args=None):
    return auth.permits(ExactOperation.normalize(tool, json.dumps(args or {})))


def _auth(text, **kw):
    return create_request_authority(text, owner="pewds", session_id="s1", workspace="", **kw)


def test_spec_surface_admits_a_router_chosen_family_tool():
    auth = _auth("Search for the appointment email", spec_surface=True)
    assert _permits(auth, "mcp__email__search_emails", {"action": "list", "query": "appointment"})


def test_non_spec_turn_does_not_admit_the_same_call():
    auth = _auth("Search for the appointment email")
    assert not _permits(auth, "mcp__email__search_emails", {"action": "list", "query": "appointment"})


def test_spec_surface_admits_browser_interaction_and_batch():
    auth = _auth("do the thing", spec_surface=True)
    assert _permits(auth, "private_browser", {"action": "batch"})
    assert _permits(auth, "private_browser", {"action": "click", "selector": "#go"})
    assert _permits(auth, "private_browser", {"action": "fill", "selector": "#q", "text": "x"})


def test_batch_is_read_but_click_stays_verb_gated_off_spec():
    auth = _auth("search the web for the appointment")
    assert _permits(auth, "private_browser", {"action": "batch"})
    assert not _permits(auth, "private_browser", {"action": "click", "selector": "#go"})


def test_spec_surface_keeps_the_exact_read_input_seal():
    auth = _auth("Read note id abc123", spec_surface=True)
    assert _permits(auth, "manage_notes", {"action": "view", "id": "abc123"})
    assert not _permits(auth, "manage_notes", {"action": "view", "id": "zzz999"})
