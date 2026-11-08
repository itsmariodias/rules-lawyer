from __future__ import annotations

from pathlib import Path

import pytest

from dnd_graph_rag.config import (ChatSettings, EmbeddingSettings,
                                  Neo4jSettings, Settings, anchors_path_for,
                                  get_settings, markdown_path_for)


class TestSettingsPaths:
    def test_given_a_root_when_the_paths_are_read_then_they_hang_off_it(self):
        # Given a settings object rooted somewhere other than the checkout
        settings = Settings(root=Path("/srv/app"))

        # When the derived paths are read
        # Then every one of them sits under that root
        assert settings.data_dir == Path("/srv/app/data")
        assert settings.source_dir == Path("/srv/app/data/source")
        assert settings.output_dir == Path("/srv/app/data/output")
        assert settings.chat_dir == Path("/srv/app/data/chat")

    def test_given_an_explicit_data_dir_when_read_then_it_wins_over_root(self):
        # Given a data directory pointed somewhere else entirely
        settings = Settings(root=Path("/srv/app"), data=Path("/mnt/srd"))

        # When the data directory is read
        # Then it is the override, not root/data
        assert settings.data_dir == Path("/mnt/srd")
        assert settings.pdf_path.parent == Path("/mnt/srd/source")

    def test_given_a_home_relative_data_dir_when_read_then_it_is_expanded(self):
        # Given a data directory written with a tilde
        settings = Settings(data=Path("~/srd-data"))

        # When the data directory is read
        # Then the tilde has been expanded to a real path
        assert "~" not in str(settings.data_dir)
        assert settings.data_dir.is_absolute()

    def test_given_the_configured_names_when_the_files_are_named_then_they_are_used(self):
        # Given the input and output filenames
        settings = Settings(root=Path("/srv/app"), pdf_name="other.pdf",
                            output_name="tree.json")

        # When the file paths are read
        # Then each is its directory plus its configured name
        assert settings.pdf_path == Path("/srv/app/data/source/other.pdf")
        assert settings.output_path == Path("/srv/app/data/output/tree.json")

    def test_given_a_root_when_the_embeddings_are_read_then_they_sit_in_output(self):
        # Given a settings object with no explicit embeddings path
        settings = Settings(root=Path("/srv/app"))

        # When the path is read
        # Then it sits with the rest of the generated output
        assert settings.embeddings_path == Path(
            "/srv/app/data/output/srd_embeddings.idx")

    def test_given_an_explicit_embeddings_path_when_read_then_it_wins(self):
        # Given a settings object pointed at a downloaded file
        settings = Settings(root=Path("/srv/app"),
                            embeddings=Path("~/Downloads/srd.idx"))

        # When the path is read
        # Then that is what is used, with ``~`` expanded
        assert settings.embeddings_path == Path.home() / "Downloads/srd.idx"

    def test_given_conversation_files_when_read_then_they_sit_outside_output(self):
        # Given the settings
        settings = Settings(root=Path("/srv/app"))

        # When the conversation paths are read
        # Then they are in chat/, which is not reproducible and not output/
        assert settings.checkpoint_path == Path("/srv/app/data/chat/chat.sqlite")
        assert settings.store_path == Path(
            "/srv/app/data/chat/chat-store.sqlite")
        assert settings.output_dir not in settings.checkpoint_path.parents

    def test_given_no_api_key_when_the_checkpoint_path_is_read_then_it_still_answers(
            self, monkeypatch):
        # Given an environment with no Google API key
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

        # When the checkpoint path is read
        path = Settings(root=Path("/srv/app")).checkpoint_path

        # Then it resolved without ever building the chat settings
        assert path.name == "chat.sqlite"


class TestSettingsGroups:
    def test_given_settings_when_built_then_no_group_is_constructed_yet(self):
        # Given a fresh settings object
        settings = Settings()

        # When its attribute dictionary is inspected before any is touched
        # Then no cached property has been evaluated
        assert "chat" not in settings.__dict__
        assert "embedding" not in settings.__dict__
        assert "neo4j" not in settings.__dict__

    def test_given_a_group_read_twice_when_compared_then_it_is_the_same_object(self):
        # Given a settings object
        settings = Settings()

        # When the chat settings are read twice
        # Then the second read returns what the first built
        assert settings.chat is settings.chat


class TestChatSettings:
    def test_given_no_stub_when_read_then_the_model_is_the_real_one(self):
        # Given no CHAT_STUB in the environment
        chat = ChatSettings()

        # When the setting is read
        # Then a turn goes to the provider
        assert chat.stub is False

    def test_given_no_overrides_when_read_then_the_search_is_wider_than_the_answer(
            self):
        # Given no CHAT_ overrides in the environment
        chat = ChatSettings()

        # When the retrieval limits are read
        # Then the pool is wider than what the model is handed
        assert chat.top_k == 3
        assert chat.search_limit > chat.top_k

    def test_given_a_blank_key_when_read_then_it_counts_as_no_key_at_all(self):
        # Given the key set to nothing
        chat = ChatSettings(google_api_key="   ")

        # When it is read
        # Then there is no key
        assert chat.google_api_key is None

    def test_given_a_key_when_read_then_it_is_kept_secret(self):
        # Given an API key
        chat = ChatSettings(google_api_key="sk-not-a-real-key")

        # When the settings are rendered
        # Then the key itself is not in the rendering
        assert "sk-not-a-real-key" not in repr(chat)
        assert chat.google_api_key.get_secret_value() == "sk-not-a-real-key"

    def test_given_the_environment_names_the_key_when_read_then_the_alias_is_used(
            self, monkeypatch):
        # Given the key under the name Google's own tooling uses
        monkeypatch.setenv("GOOGLE_API_KEY", "from-the-environment")

        # When the chat settings are built
        chat = ChatSettings()

        # Then it was picked up
        assert chat.google_api_key.get_secret_value() == "from-the-environment"


class TestEmbeddingSettings:
    def test_given_no_override_when_read_then_the_pinned_model_is_used(self):
        # Given the defaults
        settings = EmbeddingSettings()

        # When the model is read
        # Then it is the pinned one, at the width the file is written for
        assert settings.model == "gemini-embedding-001"
        assert settings.dimensions == 1536
        assert settings.task_type == "RETRIEVAL_DOCUMENT"

    def test_given_a_blank_key_when_read_then_it_counts_as_no_key_at_all(self):
        # Given a key set to nothing
        settings = EmbeddingSettings(google_api_key="   ")

        # When it is read
        # Then it is absent, which is what ``resolve`` branches on
        assert settings.google_api_key is None

    def test_given_a_key_when_read_then_it_is_kept_secret(self):
        # Given a key
        settings = EmbeddingSettings(google_api_key="secret-value")

        # When the settings are printed
        # Then the key is not in what was printed
        assert "secret-value" not in repr(settings)
        assert settings.google_api_key.get_secret_value() == "secret-value"


class TestNeo4jSettings:
    def test_given_a_user_and_password_when_auth_is_read_then_it_is_a_pair(self):
        # Given the connection settings
        neo4j = Neo4jSettings(user="neo4j", password="secret")

        # When auth is read
        # Then it is the tuple the driver takes, with the secret unwrapped
        assert neo4j.auth == ("neo4j", "secret")

    def test_given_no_password_when_built_then_it_is_refused(self, monkeypatch):
        # Given an environment with no NEO4J_PASSWORD
        monkeypatch.delenv("NEO4J_PASSWORD", raising=False)

        # When the settings are built with no password anywhere
        # Then it fails, because there is no sensible default for a password
        with pytest.raises(ValueError):
            Neo4jSettings(_env_file=None)


class TestGetSettings:
    def test_given_two_calls_when_compared_then_they_are_the_same_object(self):
        # Given the settings have been read once
        first = get_settings()

        # When they are read again
        second = get_settings()

        # Then the cache handed back what it built
        assert first is second

    def test_given_a_cleared_cache_when_read_then_the_environment_is_reread(
            self, settings_env):
        # Given the output filename overridden in the environment
        settings = settings_env(DND_GRAPH_RAG_OUTPUT_NAME="elsewhere.json")

        # When the output path is read
        # Then the override took effect, because the cache was cleared
        assert settings.output_path.name == "elsewhere.json"


class TestMarkdownPathFor:
    def test_given_an_artifact_when_asked_then_the_markdown_sits_beside_it(self):
        # Given the artifact's path
        # When the markdown path is derived
        markdown = markdown_path_for(Path("/tmp/out/srd_hierarchy.json"))

        # Then it is the same name in the same place, as markdown
        assert markdown == Path("/tmp/out/srd_hierarchy.md")


class TestAnchorsPathFor:
    def test_given_the_markdown_when_asked_then_the_anchors_sit_beside_it(self):
        # Given the markdown's path
        # When the anchors path is derived
        anchors = anchors_path_for(Path("/tmp/out/srd_hierarchy.md"))

        # Then the geometry is written beside the text it indexes
        assert anchors == Path("/tmp/out/srd_hierarchy.anchors.json")
