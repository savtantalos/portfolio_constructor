from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Load service settings from arguments, PORTFOLIO_ variables, and .env.

    Explicit arguments take precedence over environment variables, which take
    precedence over .env values and defaults. Unknown settings are ignored and
    assignment is validated. An unset API key leaves API access unrestricted.
    Cache TTL and provider timeout use seconds; capacity limits apply per app
    instance. The default database is a local SQLite file.
    """

    model_config = SettingsConfigDict(
        env_prefix="PORTFOLIO_", env_file=".env", extra="ignore", validate_assignment=True
    )

    database_url: str = "sqlite:///./portfolio.db"
    api_key: SecretStr | None = None
    cors_origins: list[str] = Field(default_factory=list)
    cache_ttl_seconds: int = Field(default=3600, ge=0, le=86400)
    cache_max_entries: int = Field(default=32, ge=0, le=256)
    provider_timeout_seconds: float = Field(default=15, gt=0, le=60)
    max_concurrent_analyses: int = Field(default=2, ge=1, le=8)
    max_backtest_rebalances: int = Field(default=200, ge=1, le=1000)
