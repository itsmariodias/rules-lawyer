"""The API answering with the fake chat model, for the e2e suite.

    uv run uvicorn tests.e2e_app:app
"""

from rules_lawyer.api import app
from rules_lawyer.chat.routes import chat_service
from tests.fakes import fake_chat_service

app.dependency_overrides[chat_service] = fake_chat_service
