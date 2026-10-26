from app.llm import provider as llm


def test_parse_json_block_reads_an_object():
    payload = llm.parse_json_block('{"flags": [{"title": "Retention"}]}')
    assert payload == {"flags": [{"title": "Retention"}]}


def test_parse_json_block_strips_markdown_fences():
    text = '```json\n{"requirements": [{"text": "hold a licence"}]}\n```'
    assert llm.parse_json_block(text) == {"requirements": [{"text": "hold a licence"}]}


def test_parse_json_block_keeps_a_bare_array_under_the_expected_key():
    """A model that answers with a list instead of the object it was asked for.

    The free model router answers with a bare array often enough that
    throwing the answer away would waste a call and the information in it.
    """
    text = '[{"severity": "High", "title": "Retention"}, {"severity": "Low", "title": "Delay"}]'
    payload = llm.parse_json_block(text, "flags")
    assert payload is not None
    assert len(payload["flags"]) == 2
    assert payload["flags"][0]["title"] == "Retention"


def test_parse_json_block_ignores_a_bare_array_without_a_key():
    text = '[{"title": "Retention"}]'
    assert llm.parse_json_block(text) is None


def test_parse_json_block_rejects_nonsense():
    assert llm.parse_json_block("not json at all") is None
    assert llm.parse_json_block("") is None
    assert llm.parse_json_block(None) is None


def test_read_text_survives_an_empty_or_unusual_response():
    """A provider that answers with nothing must not fail the call."""
    assert llm.OpenAICompatibleProvider._read_text({}) == ""
    assert llm.OpenAICompatibleProvider._read_text({"choices": []}) == ""
    assert llm.OpenAICompatibleProvider._read_text({"choices": [{"message": {}}]}) == ""
    assert llm.OpenAICompatibleProvider._read_text({"choices": [{"message": {"content": None}}]}) == ""
    assert llm.OpenAICompatibleProvider._read_text({"choices": [{"message": {"content": "hello"}}]}) == "hello"
    # Some providers answer with a list of content blocks.
    blocks = {"choices": [{"message": {"content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]}}]}
    assert llm.OpenAICompatibleProvider._read_text(blocks) == "ab"
