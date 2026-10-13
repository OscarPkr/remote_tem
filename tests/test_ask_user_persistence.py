"""Regression coverage for durable ``ask_user`` choice cards.

The live event must arrive after ``tool_output`` so the settled tool trace
cannot cover/push away the card.  The same payload must be persisted inside
``tool_events`` so chat history can reconstruct it after a reload.
"""

import asyncio
import json
from pathlib import Path

import src.agent_loop as agent_loop


ROOT = Path(__file__).resolve().parents[1]


def _collect(gen):
    async def _run():
        return [chunk async for chunk in gen]

    return asyncio.run(_run())


def _events(chunks):
    events = []
    for chunk in chunks:
        if chunk.startswith("data: ") and not chunk.startswith("data: [DONE]"):
            events.append(json.loads(chunk[6:]))
    return events


def test_ask_user_is_emitted_last_and_persisted(monkeypatch):
    payload = {
        "question": "¿Qué proyecto prefieres?",
        "options": [
            {"label": "Análisis de reseñas"},
            {"label": "Clasificación temática"},
        ],
        "multi": False,
    }

    monkeypatch.setattr(agent_loop, "get_setting", lambda key, default=None: default, raising=False)
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *args, **kwargs: 10, raising=False)

    async def fake_stream(_candidates, messages, **kwargs):
        call = {"name": "ask_user", "arguments": json.dumps(payload, ensure_ascii=False)}
        yield f'data: {json.dumps({"type": "tool_calls", "calls": [call]})}\n\n'
        yield "data: [DONE]\n\n"

    async def fake_execute(block, *args, **kwargs):
        parsed = json.loads(block.content)
        return (
            "ask_user",
            {
                "ask_user": parsed,
                "output": "Awaiting their selection.",
                "exit_code": 0,
            },
        )

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", fake_stream, raising=False)
    monkeypatch.setattr(agent_loop, "execute_tool_block", fake_execute, raising=False)

    chunks = _collect(
        agent_loop.stream_agent_loop(
            "https://api.openai.com/v1",
            "gpt-4o",
            [{"role": "user", "content": "Ayúdame a elegir un proyecto."}],
            relevant_tools={"ask_user"},
            _is_teacher_run=True,
        )
    )
    events = _events(chunks)

    tool_output_index = next(i for i, event in enumerate(events) if event.get("type") == "tool_output")
    ask_user_index = next(i for i, event in enumerate(events) if event.get("type") == "ask_user")
    assert tool_output_index < ask_user_index

    tool_output = events[tool_output_index]
    assert tool_output["ask_user"] == payload
    assert "¿Qué proyecto prefieres?" in tool_output["command"]
    assert "\\u00" not in tool_output["command"]

    metrics = next(event["data"] for event in events if event.get("type") == "metrics")
    assert metrics["tool_events"][0]["ask_user"] == payload


def test_clean_preview_ask_user_ends_turn_without_second_round(monkeypatch):
    """The compact ``stream_preview`` runtime must treat ask_user as a turn boundary.

    Regression for chat d8dca715: the preview fed the ask_user tool result
    back to the model, so it burned a second provider round and persisted the
    model's follow-up prose instead of the question.
    """
    import src.clean_agent_preview as module
    from src.tool_schemas import FUNCTION_TOOL_SCHEMAS
    from src.tool_policy import ToolPolicy
    from src.turn_contract import resolve_full_inventory_contract

    payload = {
        "question": "What would be most useful to start with?",
        "options": [
            {"label": "A 30-day meditation plan"},
            {"label": "How to measure brain activity"},
        ],
        "multi": False,
    }
    requests = []
    responses = iter([
        {'choices': [{'delta': {'tool_calls': [{'index': 0, 'id': 'ask-1',
            'function': {'name': 'ask_user',
                         'arguments': json.dumps(payload, ensure_ascii=False)}}]}}]},
        {'choices': [{'delta': {'content': 'SHOULD NOT BE REQUESTED'}}]},
    ])

    class Response:
        def __init__(self, body): self.body = body
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def raise_for_status(self): pass
        async def aiter_lines(self):
            yield 'data: ' + json.dumps(self.body)
            yield 'data: [DONE]'

    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def stream(self, *args, **kwargs):
            requests.append(kwargs['json'])
            return Response(next(responses))

    async def execute(block, **kwargs):
        parsed = json.loads(block.content)
        return 'ask_user', {
            'ask_user': parsed,
            'output': 'Awaiting their selection.',
            'exit_code': 0,
        }

    monkeypatch.setattr(module.httpx, 'AsyncClient', Client)
    monkeypatch.setattr(module, 'execute_tool_block', execute)

    schema = next(s for s in FUNCTION_TOOL_SCHEMAS if s['function']['name'] == 'ask_user')
    contract = resolve_full_inventory_contract(schemas=[schema], policy=ToolPolicy())
    raw = _collect(module.stream_preview(
        endpoint_url='http://test', model='test', headers={},
        messages=[{'role': 'user', 'content': 'Help me pick a project.'}],
        turn_contract=contract, session_id='test', owner='test',
        disabled_tools=set(), tool_policy=ToolPolicy(),
    ))
    events = _events(raw)

    # Ending the turn means no second provider round is requested.
    assert len(requests) == 1
    ask_user_events = [event for event in events if event.get('type') == 'ask_user']
    assert len(ask_user_events) == 1
    assert ask_user_events[0]['data'] == payload
    # The saved assistant text is the question, not the model's follow-up prose.
    final = next(event for event in events if event.get('type') == 'final_response')
    assert final['content'] == payload['question']
    types = [event.get('type') for event in events]
    assert types.index('ask_user') < types.index('metrics')
    # Reconstructable from persisted metadata, and no phantom extra rounds.
    metrics = next(event['data'] for event in events if event.get('type') == 'metrics')
    assert metrics['tool_events'][0]['ask_user'] == payload
    assert metrics['agent_rounds'] == 1
    assert metrics['clean_v3_turn'][-1] == {
        'role': 'assistant', 'content': payload['question'],
    }


def test_frontend_uses_one_renderer_for_live_and_restored_cards():
    chat = (ROOT / "static" / "js" / "chat.js").read_text(encoding="utf-8")
    renderer = (ROOT / "static" / "js" / "chatRenderer.js").read_text(encoding="utf-8")

    assert "chatRenderer.renderAskUserCard(json.data || {})" in chat
    assert "export function renderAskUserCard" in renderer
    assert "renderAskUserCard(pendingAskUser" in renderer
    assert "function _answerAskUserCards(root, text)" in renderer
    assert "if (role === 'user') _answerAskUserCards(box," in renderer
