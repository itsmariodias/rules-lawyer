from __future__ import annotations

import pytest

from rules_lawyer.chat.agent import model


class TestModel:
    def test_given_no_api_key_when_built_then_it_is_reported_not_raised_at_import(
            self, settings_env, monkeypatch):
        # Given settings with the key removed (``.env`` may supply one, so
        # unsetting the environment variable is not enough)
        settings = settings_env()
        monkeypatch.setattr(settings.chat, "google_api_key", None)

        # When the model is built
        # Then the failure names the setting and what to do about it
        with pytest.raises(model.NoApiKey, match="GOOGLE_API_KEY"):
            model.model()

    def test_given_a_key_when_built_then_the_pinned_model_is_used(
            self, settings_env, monkeypatch):
        # Given a key in the environment
        monkeypatch.setenv("GOOGLE_API_KEY", "not-a-real-key")
        settings = settings_env()

        # When the model is built
        built = model.model()

        # Then it is the configured model, at the configured temperature
        assert built.model.endswith(settings.chat.model)
        assert built.temperature == settings.chat.temperature


    def test_given_a_blank_key_when_built_then_it_counts_as_no_key_at_all(
            self, settings_env, monkeypatch):
        # Given a key blanked out rather than removed
        monkeypatch.setenv("GOOGLE_API_KEY", "   ")
        settings_env()

        # When the model is built
        # Then it fails the way a missing key does
        with pytest.raises(model.NoApiKey, match="GOOGLE_API_KEY"):
            model.model()
