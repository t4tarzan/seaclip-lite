from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    github_token: str = ""
    github_org: str = "t4tarzan"
    claude_bin: str = "/opt/homebrew/bin/claude"
    claude_model: str = "sonnet"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3.5:35b"
    database_url: str = "sqlite+aiosqlite:///./seaclip.db"
    github_poll_interval_seconds: int = 30
    host: str = "0.0.0.0"
    port: int = 5200
    backup_dir: str = "./backups"
    # Multi-provider LLM settings (env-var fallbacks; DB HubSettings take priority)
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    openrouter_api_key: str = ""
    litellm_base_url: str = "http://localhost:4000/v1"
    litellm_api_key: str = ""
    default_provider: str = "claude_cli"
    default_model: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
