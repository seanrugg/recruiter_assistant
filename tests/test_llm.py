"""Small models wrap JSON in chatter. The parser has to read through it."""
import pytest
from recruiting_desk import llm


@pytest.mark.parametrize("text", [
    '{"subject": "S", "body": "B"}',
    'Here you go:\n```json\n{"subject": "S", "body": "B"}\n```',
    'Sure! {"subject": "S", "body": "B"} Hope that helps.',
])
def test_lenient_json(text):
    assert llm.parse_json(text)["subject"] == "S"


def test_garbage_raises_a_readable_error():
    with pytest.raises(llm.ProviderError):
        llm.parse_json("I cannot help with that.")


def test_key_never_reaches_the_ui():
    llm.save_settings({"provider": "anthropic", "api_key": "sk-secret"})
    pub = llm.public_settings()
    assert pub["has_key"] is True
    assert "sk-secret" not in str(pub)
