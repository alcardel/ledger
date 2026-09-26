from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
ROOT = Path(__file__).resolve().parents[2]
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / '.env', extra='ignore')
    database_url: str = 'postgresql+psycopg://workbench_app:local_app_password@localhost:55432/workbench'
    redis_url: str = 'redis://localhost:56379/0'
    storage_dir: str = str(ROOT / 'data/documents')
    auth_mode: str = 'workos'
    demo_token: str = ''
    workos_client_id: str = ''
    workos_api_key: str = ''
    workos_redirect_uri: str = 'http://localhost:8000/api/v1/auth/callback'
    frontend_url: str = 'http://localhost:3000'
    session_secret: str = ''
    jev_api_key: str = ''
    jev_model: str = 'jev-latest'
    ollama_url: str = 'http://localhost:11434'
    ollama_model: str = 'qwen3-vl:4b'
    decision_provider: str = 'local'
    decision_model: str = 'qwen3:8b'
    extraction_provider: str = 'auto'
    gemini_api_key: str = ''
    gemini_model: str = 'gemini-2.5-flash'

settings = Settings()
