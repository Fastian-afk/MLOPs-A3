from agent.logging import redact


def test_numeric_provider_usage_survives_redaction_but_credentials_do_not():
    record = redact(
        {
            "usage": {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25},
            "api_token": "secret",
            "confirmation_token": "nonce",
            "nested": {"prompt_tokens": "a-secret-is-not-a-count"},
        }
    )
    assert record["usage"] == {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25}
    assert record["api_token"] == "[REDACTED]"
    assert record["confirmation_token"] == "[REDACTED]"
    assert record["nested"]["prompt_tokens"] == "[REDACTED]"
