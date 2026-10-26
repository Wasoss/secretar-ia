"""
Configuración centralizada de Secretar-IA usando Pydantic Settings.

Valida todas las variables de entorno al startup y proporciona
tipado seguro en toda la aplicación.
"""
from zoneinfo import ZoneInfo
from pydantic import PostgresDsn, field_validator, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración de la aplicación con validación automática."""

    # --- Telegram ---
    telegram_token: str
    mi_telegram_id: str = Field(validation_alias="MI_TELEGRAM_ID")

    # --- Groq AI ---
    groq_api_key: str
    groq_model: str = "qwen/qwen3.8-27b"
    groq_whisper_model: str = "whisper-large-v3"

    # --- Base de Datos ---
    database_url: PostgresDsn

    # --- Servidor / Deploy ---
    port: int = 10000

    # --- Zona Horaria ---
    timezone: str = "America/Argentina/Buenos_Aires"

    @property
    def tz(self) -> ZoneInfo:
        """Retorna objeto ZoneInfo para uso en datetime aware."""
        return ZoneInfo(self.timezone)

    @field_validator("telegram_token")
    @classmethod
    def validate_telegram_token(cls, v: str) -> str:
        if not v or v == "your_telegram_bot_token_here":
            raise ValueError("TELEGRAM_TOKEN no configurado o usando valor placeholder")
        if ":" not in v:
            raise ValueError("TELEGRAM_TOKEN formato inválido (debe contener ':')")
        return v

    @field_validator("groq_api_key")
    @classmethod
    def validate_groq_api_key(cls, v: str) -> str:
        if not v or v == "your_groq_api_key_here":
            raise ValueError("GROQ_API_KEY no configurado o usando valor placeholder")
        if not v.startswith("gsk_"):
            raise ValueError("GROQ_API_KEY formato inválido (debe empezar con 'gsk_')")
        return v

    @field_validator("mi_telegram_id")
    @classmethod
    def validate_telegram_id(cls, v: str) -> str:
        if not v or v == "your_telegram_user_id_here":
            raise ValueError("MI_TELEGRAM_ID no configurado o usando valor placeholder")
        if not v.isdigit():
            raise ValueError("MI_TELEGRAM_ID debe ser numérico")
        return v

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v: PostgresDsn) -> PostgresDsn:
        url_str = str(v)
        if "your_" in url_str or "placeholder" in url_str:
            raise ValueError("DATABASE_URL no configurado o usando valor placeholder")
        return v

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


# Instancia global (singleton) - se valida al importar
settings = Settings()