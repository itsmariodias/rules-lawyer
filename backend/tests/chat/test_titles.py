from __future__ import annotations

import asyncio

import pytest
from langchain_core.messages import AIMessage

from dnd_graph_rag.chat import agent, titles


class Replying:
    """A model that always replies with the same text."""

    def __init__(self, reply: str):
        self.reply = reply
        self.prompts: list[str] = []

    async def ainvoke(self, prompt: str) -> AIMessage:
        self.prompts.append(prompt)
        return AIMessage(content=self.reply)


class Failing:
    """A model whose every call raises."""

    async def ainvoke(self, prompt: str) -> AIMessage:
        raise RuntimeError("429 RESOURCE_EXHAUSTED")


class Stalling:
    """A model that never replies."""

    async def ainvoke(self, prompt: str) -> AIMessage:
        await asyncio.sleep(60)
        raise AssertionError("never reached")


@pytest.fixture
def live(settings_env):
    """Turn the stub off and give the settings a key."""
    settings_env(CHAT_STUB="0")


class TestClean:
    def test_given_a_plain_reply_when_cleaned_then_it_is_kept(self):
        # Given a reply that is already a title
        # When it is cleaned
        # Then it stands
        assert titles.clean("Prone condition effects") == "Prone condition effects"

    def test_given_a_quoted_reply_with_a_full_stop_when_cleaned_then_both_go(self):
        # Given a reply dressed as a sentence
        # When it is cleaned
        # Then only the words are left
        assert titles.clean('"Prone Condition Effects."') == "Prone Condition Effects"
        assert titles.clean("**Sneak Attack Scaling**") == "Sneak Attack Scaling"

    def test_given_a_labelled_reply_when_cleaned_then_the_label_goes(self):
        # Given a reply that names what it is
        # When it is cleaned
        # Then the label is not part of the title
        assert titles.clean("Title: Fireball damage") == "Fireball damage"

    def test_given_a_long_reply_when_cleaned_then_it_is_cut_to_five_words(self):
        # Given a reply that ignored the limit
        # When it is cleaned
        # Then it keeps its first five words
        assert (titles.clean("Creatures that can inflict the Frightened condition")
                == "Creatures that can inflict the")

    def test_given_a_reply_that_explains_itself_when_cleaned_then_only_the_first_line_counts(self):
        # Given a title followed by commentary
        # When it is cleaned
        # Then the commentary is dropped
        assert titles.clean("\nGrappling rules\nThis covers grappling.") == "Grappling rules"

    def test_given_an_empty_reply_when_cleaned_then_there_is_no_title(self):
        # Given a reply with nothing usable in it
        # When it is cleaned
        # Then there is no title, rather than an empty one
        assert titles.clean("") is None
        assert titles.clean('  "."  ') is None


class TestSummarise:
    @pytest.mark.asyncio
    async def test_given_the_stub_when_summarised_then_no_model_is_asked(
            self, stub_model, monkeypatch):
        # Given the scripted model, and a real one that must not be reached
        model = Replying("Should not appear")
        monkeypatch.setattr(agent, "model", lambda: model)

        # When a question is summarised
        title = await titles.summarise("What does Prone do?")

        # Then there is no title and nothing was asked
        assert title is None
        assert model.prompts == []

    @pytest.mark.asyncio
    async def test_given_a_model_when_summarised_then_its_reply_is_the_title(
            self, live, monkeypatch):
        # Given a model that replies the way models do
        model = Replying('"Prone Condition Effects."')
        monkeypatch.setattr(agent, "model", lambda: model)

        # When a question is summarised
        title = await titles.summarise("What exactly does the Prone condition do?")

        # Then the cleaned reply is the title, and the question was in the prompt
        assert title == "Prone Condition Effects"
        assert "What exactly does the Prone condition do?" in model.prompts[0]

    @pytest.mark.asyncio
    async def test_given_a_failing_model_when_summarised_then_there_is_no_title(
            self, live, monkeypatch):
        # Given a model with its quota spent
        monkeypatch.setattr(agent, "model", lambda: Failing())

        # When a question is summarised
        # Then there is no title, rather than a raised error
        assert await titles.summarise("What does Prone do?") is None

    @pytest.mark.asyncio
    async def test_given_no_key_when_summarised_then_there_is_no_title(
            self, live, monkeypatch):
        # Given no key to call the model with
        def missing():
            raise agent.NoApiKey("GOOGLE_API_KEY is not set.")

        monkeypatch.setattr(agent, "model", missing)

        # When a question is summarised
        # Then there is no title
        assert await titles.summarise("What does Prone do?") is None

    @pytest.mark.asyncio
    async def test_given_a_stalled_model_when_summarised_then_it_gives_up(
            self, live, monkeypatch):
        # Given a model that never answers, and a short bound
        monkeypatch.setattr(agent, "model", lambda: Stalling())
        monkeypatch.setattr(titles, "TIMEOUT_SECONDS", 0.05)

        # When a question is summarised
        # Then it stops waiting and there is no title
        assert await titles.summarise("What does Prone do?") is None


class TestTitled:
    @pytest.mark.asyncio
    async def test_given_no_store_when_read_then_there_are_none(self):
        # Given no store at all
        # When the titles are read
        # Then the absence is answered rather than raised
        assert await titles.titled(None) == {}

    @pytest.mark.asyncio
    async def test_given_many_titles_when_read_then_all_come_back(self, store):
        """``BaseStore.asearch`` returns ten results by default."""
        # Given more titles than a default page holds
        for n in range(12):
            await titles.remember(store, f"t{n}", f"Title {n}")

        # When they are read
        named = await titles.titled(store)

        # Then every one is there
        assert len(named) == 12
        assert named["t11"] == "Title 11"

    @pytest.mark.asyncio
    async def test_given_a_title_when_forgotten_then_it_is_gone(self, store):
        # Given a stored title
        await titles.remember(store, "doomed", "Prone condition effects")

        # When it is forgotten
        await titles.forget(store, "doomed")

        # Then nothing is left of it
        assert await titles.titled(store) == {}
