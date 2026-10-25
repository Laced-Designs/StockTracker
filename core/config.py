from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MP_", env_file=".env", extra="ignore")
    database_path: str = "data/history.duckdb"
    demo: bool = False
    alpha_vantage_key: str = ""
    sec_user_agent: str = ""
    alpaca_key: str = ""
    alpaca_secret: str = ""
    window: int = 30
    neighbors: int = 12
    alert_threshold: float = 0.75
