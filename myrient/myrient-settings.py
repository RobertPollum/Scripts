#https://docs.pydantic.dev/latest/concepts/pydantic_settings/#usage
from collections.abc import Callable
from typing import Any

from pydantic import (
    AliasChoices,
    BaseModel,
    Field,
    ImportString,
)

from pydantic_settings import BaseSettings, SettingsConfigDict

class SubModel(BaseModel):
    max_retries: int = 3
    retry_delay: int = 5
    base_url: str = 'https://myrient.erista.me'


class Settings(BaseSettings):
