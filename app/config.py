from pathlib import Path
from typing import Literal

from dotenv import dotenv_values
from pydantic import BaseModel, Field, HttpUrl
import os

ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseModel):
    api_key: str = Field(default="", repr=False)
    base_url: HttpUrl = "https://api.anthropic.com"
    model: str = "claude-sonnet-5-5"
    timeout: float = Field(default=30, gt=0, le=120)
    database_path: str = "data/support.db"
    docs_base_url: str = "https://docs.ampere.sh/docs"
    discord_mode: Literal["mock"] = "mock"
    mock_discord_result: Literal["success", "failure"] = "success"

    @classmethod
    def load(cls):
        values = {**dotenv_values(ROOT / ".env"), **os.environ}
        mapping = {"api_key": "ANTHROPIC_API_KEY", "base_url": "ANTHROPIC_BASE_URL",
                   "model": "ANTHROPIC_MODEL", "timeout": "MODEL_TIMEOUT_SECONDS",
                   "database_path": "DATABASE_PATH", "docs_base_url": "DOCS_BASE_URL",
                   "discord_mode": "DISCORD_MODE", "mock_discord_result": "MOCK_DISCORD_RESULT"}
        return cls(**{k: values[v] for k, v in mapping.items() if values.get(v)})

