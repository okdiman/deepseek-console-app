"""Unit tests for load_config — environment variable parsing."""
import os

import pytest

from deepseek_chat.core.config import load_config, ClientConfig


class TestDeepseekDefaults:
    def test_deepseek_provider(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key-123")
        monkeypatch.setenv("PROVIDER", "deepseek")
        # Clear Groq key to avoid interference
        monkeypatch.delenv("GROQ_API_KEY", raising=False)

        config = load_config()
        assert config.provider == "deepseek"
        assert config.api_key == "test-key-123"
        assert config.model == "deepseek-chat"
        assert config.max_tokens == 4000
        assert "deepseek.com" in config.api_url

    def test_default_provider_is_deepseek(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "key")
        monkeypatch.delenv("PROVIDER", raising=False)
        config = load_config()
        assert config.provider == "deepseek"


class TestGroqDefaults:
    def test_groq_provider(self, monkeypatch):
        monkeypatch.setenv("PROVIDER", "groq")
        monkeypatch.setenv("GROQ_API_KEY", "groq-key-456")

        config = load_config()
        assert config.provider == "groq"
        assert config.api_key == "groq-key-456"
        assert "groq.com" in config.api_url


class TestMissingApiKey:
    def test_deepseek_missing_key(self, monkeypatch):
        monkeypatch.setenv("PROVIDER", "deepseek")
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        # Prevent load_dotenv from re-injecting keys from .env file
        monkeypatch.setattr("deepseek_chat.core.config.load_dotenv", lambda: None)
        with pytest.raises(SystemExit):
            load_config()

    def test_groq_missing_key(self, monkeypatch):
        monkeypatch.setenv("PROVIDER", "groq")
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        monkeypatch.setattr("deepseek_chat.core.config.load_dotenv", lambda: None)
        with pytest.raises(SystemExit):
            load_config()

    def test_invalid_provider(self, monkeypatch):
        monkeypatch.setenv("PROVIDER", "openai")
        with pytest.raises(SystemExit):
            load_config()


class TestCompressionFlags:
    @pytest.mark.parametrize("value,expected", [
        ("true", True),
        ("1", True),
        ("yes", True),
        ("false", False),
        ("0", False),
        ("no", False),
        ("off", False),
    ])
    def test_compression_enabled_parsing(self, monkeypatch, value, expected):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "key")
        monkeypatch.setenv("DEEPSEEK_COMPRESSION_ENABLED", value)
        config = load_config()
        assert config.compression_enabled == expected

    @pytest.mark.parametrize("value,expected", [
        ("true", True),
        ("false", False),
        ("0", False),
        ("off", False),
    ])
    def test_persist_context_parsing(self, monkeypatch, value, expected):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "key")
        monkeypatch.setenv("DEEPSEEK_PERSIST_CONTEXT", value)
        config = load_config()
        assert config.persist_context == expected


class TestCustomValues:
    def test_custom_timeout_and_tokens(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "key")
        monkeypatch.setenv("DEEPSEEK_API_TIMEOUT_SECONDS", "120")
        monkeypatch.setenv("DEEPSEEK_API_MAX_TOKENS", "8000")
        config = load_config()
        assert config.read_timeout_seconds == 120
        assert config.max_tokens == 8000

    def test_compression_threshold_and_keep(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "key")
        monkeypatch.setenv("DEEPSEEK_COMPRESSION_THRESHOLD", "20")
        monkeypatch.setenv("DEEPSEEK_COMPRESSION_KEEP", "8")
        config = load_config()
        assert config.compression_threshold == 20
        assert config.compression_keep == 8

    def test_context_max_messages(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "key")
        monkeypatch.setenv("DEEPSEEK_CONTEXT_MAX_MESSAGES", "100")
        config = load_config()
        assert config.context_max_messages == 100
