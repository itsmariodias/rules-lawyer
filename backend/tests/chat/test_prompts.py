from __future__ import annotations

import pytest

from rules_lawyer.chat.prompts import HERE, prompt

NAMES = sorted(path.stem for path in HERE.glob("*.md"))


class TestPrompt:
    def test_given_the_prompts_folder_when_listed_then_the_three_are_there(self):
        # Given the folder beside the loader
        # When its markdown files are listed
        # Then the system prompt, the graph orientation and the title are all there
        assert NAMES == ["graph-orientation", "system", "title"]

    @pytest.mark.parametrize("name", NAMES)
    def test_given_a_prompt_file_when_loaded_then_it_has_text_and_no_trailing_newline(
            self, name):
        # Given a prompt file
        # When it is loaded
        text = prompt(name)

        # Then there is something to send, and it ends where the prose does
        assert text.strip()
        assert not text.endswith("\n")

    def test_given_an_unknown_name_when_loaded_then_it_fails(self):
        # Given a name with no file
        # When it is loaded
        # Then it is refused rather than sent as nothing
        with pytest.raises(FileNotFoundError):
            prompt("no-such-prompt")

    def test_given_the_title_prompt_when_formatted_then_the_question_goes_in_once(self):
        # Given the title prompt
        text = prompt("title")

        # When a question is put into it
        formatted = text.format(question="What does Prone do?")

        # Then the placeholder was its only one, and the question is in it
        assert text.count("{question}") == 1
        assert formatted.count("What does Prone do?") == 1
