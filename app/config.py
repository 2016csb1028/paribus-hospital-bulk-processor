"""Application configuration, driven by environment variables."""
import os


class Settings:
    """Central settings object. Values can be overridden via environment variables."""

    # Base URL of the (given) Hospital Directory API
    HOSPITAL_API_BASE_URL: str = os.getenv(
        "HOSPITAL_API_BASE_URL", "https://hospital-directory.onrender.com"
    ).rstrip("/")

    # Hard limit imposed by the assignment
    MAX_CSV_ROWS: int = int(os.getenv("MAX_CSV_ROWS", "20"))

    # Max upload size in bytes (defensive; 20 rows should never be near this)
    MAX_UPLOAD_BYTES: int = int(os.getenv("MAX_UPLOAD_BYTES", str(1 * 1024 * 1024)))

    # Performance tuning
    CONCURRENCY: int = int(os.getenv("BULK_CONCURRENCY", "10"))
    REQUEST_TIMEOUT_SECONDS: float = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "30"))
    MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "3"))
    RETRY_BACKOFF_BASE_SECONDS: float = float(os.getenv("RETRY_BACKOFF_BASE_SECONDS", "0.5"))


settings = Settings()
