"""The model-facing words for forgetting the recap must match the words the code gate accepts."""
import re

import pytest

from super_agent_voice import recap
from super_agent_voice.gemini_adapter import _FORGET_ASKED

# Words a model might be told, whether or not the gate accepts them.
CANDIDATES = ("forget", "clear", "delete", "erase", "remove", "wipe", "scratch")


def gate_words() -> set[str]:
    group = re.search(r"\(\?:([a-z|]+)\)", _FORGET_ASKED.pattern)
    assert group, "the gate pattern changed shape; update this test"
    return set(group[1].split("|"))


def description() -> str:
    return next(t["function"]["description"] for t in recap.TOOLS if t["function"]["name"] == "forget_conversation")


def test_the_tool_description_names_exactly_the_words_the_gate_accepts():
    named = {word for word in CANDIDATES if re.search(rf"\b{word}\b", description())}
    assert named == gate_words()


@pytest.mark.parametrize("word", CANDIDATES)
def test_the_gate_accepts_a_word_if_and_only_if_the_description_names_it(word):
    assert bool(_FORGET_ASKED.search(f"please {word} it")) == bool(re.search(rf"\b{word}\b", description()))
