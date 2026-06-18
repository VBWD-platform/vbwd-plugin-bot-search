"""Shared fixtures for bot-search tests.

Unit specs drive the plugin's ``handle_action`` against the CORE
``search_provider_registry`` with a fake in-memory ``SearchProvider`` — no DB,
no app context. The registry is cleared around each test so registrations never
leak between tests.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

os.environ.setdefault("FLASK_ENV", "testing")
os.environ.setdefault("TESTING", "true")


@pytest.fixture
def clean_search_registry():
    """Yield the core search registry, cleared before and after the test."""
    from vbwd.services.search import search_provider_registry

    search_provider_registry.clear()
    yield search_provider_registry
    search_provider_registry.clear()
