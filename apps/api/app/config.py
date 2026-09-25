"""
Centralized settings, loaded from environment variables (.env in local dev).
Keep every config value here -- no hardcoded connection strings or flags
scattered through the codebase.

PRODUCTION FAILS FAST
With ENVIRONMENT=production the app refuses to start on a configuration that
would be unsafe to serve: no operator tokens (so anyone could save plans or
close roads with field reports), a localhost CORS origin, or the development
database URL. A service that boots with a bad config and fails quietly later
is worse than one that does not boot. See docs/deployment.md.
"""

from functools import lru_cache

import json

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_DATABASE_URL = "postgresql://setuner:setuner@localhost:5432/setuner"


def _as_list(value):
    """Accept the forms a person actually types into a hosting dashboard.

    A list setting given as a bare value crashes pydantic's JSON parsing at
    startup with a stack trace that names json.decoder, not the variable --
    which is exactly what happened on the first real deploy, with
    OPERATOR_TOKEN_HASHES pasted as a bare hash. All of these now work:

        ["a", "b"]      JSON, as the docs show
        a,b             comma-separated
        a               one value

    A single hash or origin is the common case, and it should not be the one
    that fails.
    """
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return []
    if text.startswith("["):
        return json.loads(text)
    return [part.strip() for part in text.split(",") if part.strip()]


class Settings(BaseSettings):
    # enable_decoding=False stops pydantic-settings JSON-decoding list fields
    # before validators see them, which is what made a bare hash in
    # OPERATOR_TOKEN_HASHES a startup crash. `_parse_list` below does the
    # decoding instead, and accepts the plain forms too.
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", enable_decoding=False
    )

    environment: str = "development"
    database_url: str = DEV_DATABASE_URL
    cors_allowed_origins: list[str] = ["http://localhost:3000"]

    # SHA-256 hex digests of operator tokens, never the tokens themselves.
    # Generate with: python -m app.security new-token
    operator_token_hashes: list[str] = []

    # Field reports close and slow roads in current-conditions routing, so in
    # production they need an operator token unless this is set explicitly --
    # an open crowdsourcing deployment is a deliberate choice, not a default.
    public_field_reports: bool = False

    # Planning runs shortest paths over the whole corridor; more concurrent
    # requests than this get a 429 rather than exhausting memory.
    max_concurrent_plans: int = 2

    @field_validator("cors_allowed_origins", "operator_token_hashes", mode="before")
    @classmethod
    def _parse_list(cls, value):
        return _as_list(value)

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    def production_problems(self) -> list[str]:
        """Everything that makes this configuration unsafe to serve publicly."""
        problems = []
        if not self.operator_token_hashes:
            problems.append(
                "OPERATOR_TOKEN_HASHES is empty: every write endpoint would be open. "
                "Generate one with `python -m app.security new-token`."
            )
        bad = [h for h in self.operator_token_hashes if len(h) != 64 or not all(c in "0123456789abcdef" for c in h.lower())]
        if bad:
            problems.append("OPERATOR_TOKEN_HASHES must be 64-character SHA-256 hex digests, not raw tokens.")
        if any("localhost" in o or "127.0.0.1" in o for o in self.cors_allowed_origins):
            problems.append("CORS_ALLOWED_ORIGINS includes localhost; set it to the deployed web origin.")
        if "*" in self.cors_allowed_origins:
            problems.append("CORS_ALLOWED_ORIGINS must not be '*' while credentials are allowed.")
        # Any local database, not just the documented default: a production
        # service pointed at localhost is wrong however it got there, and
        # matching one exact string made the check depend on that string
        # never changing (it did change, and the check went quiet).
        if self.database_url == DEV_DATABASE_URL:
            problems.append("DATABASE_URL is the local development default.")
        elif "@localhost" in self.database_url or "@127.0.0.1" in self.database_url:
            problems.append("DATABASE_URL points at a local database.")
        return problems


@lru_cache
def get_settings() -> Settings:
    return Settings()
