"""Konfigurasi aplikasi.

Semua nilai dibaca dari file .env (lihat .env.example).
Kalau .env tidak ada, dipakai nilai default di bawah supaya aplikasi
tetap bisa dijalankan untuk development.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Catat"
    secret_key: str = "ganti-dengan-string-acak-panjang"

    # Database SQLite disimpan di folder data/ supaya gampang di-backup.
    database_url: str = f"sqlite:///{(DATA_DIR / 'app.db').as_posix()}"
    upload_dir: Path = DATA_DIR / "uploads"

    # Sesi login
    session_days: int = 30
    cookie_secure: bool = False  # set true kalau sudah pakai HTTPS
    login_max_attempts: int = 5
    login_lock_minutes: int = 15

    # Telegram
    telegram_bot_token: str = ""
    telegram_allowed_chat_id: str = ""  # Changed to string to avoid validation error
    telegram_webhook_url: str = ""  # Public webhook URL (empty = polling mode)
    
    @property
    def telegram_chat_id(self) -> int | None:
        """Convert chat ID string to int."""
        if self.telegram_allowed_chat_id:
            try:
                return int(self.telegram_allowed_chat_id)
            except ValueError:
                return None
        return None

    # Zona waktu untuk tampilan dan parsing tanggal
    timezone: str = "Asia/Jakarta"

    # LLM lokal (opsional). Kalau false, sistem tetap jalan penuh.
    llm_enabled: bool = False
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:0.5b-instruct"
    ollama_timeout: float = 3.0


settings = Settings()

# Pastikan folder data ada saat aplikasi start.
DATA_DIR.mkdir(parents=True, exist_ok=True)
settings.upload_dir.mkdir(parents=True, exist_ok=True)
