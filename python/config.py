"""
Configuration management for Writer.

Handles loading API keys and settings from ~/.writer/config/writer.conf
"""

import configparser
from pathlib import Path
from typing import Optional
from dataclasses import dataclass


CONFIG_DIR = Path.home() / ".writer" / "config"
CONFIG_FILE = CONFIG_DIR / "writer.conf"


@dataclass
class AIConfig:
    """AI provider configuration."""
    provider: str = "openai"
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    openai_model: str = "gpt-4"
    claude_model: str = "claude-sonnet-4-20250514"


@dataclass
class DisplayConfig:
    """Display configuration."""
    suggestion_count: int = 3
    outline_ai_enhance: bool = True
    outline_refresh_interval: float = 2.0


@dataclass
class EditorConfig:
    """Editor context configuration."""
    context_lines_before: int = 50
    context_lines_after: int = 10
    writing_style: Optional[str] = None


@dataclass
class WebConfig:
    """Web interface configuration."""
    username: str = "writer"
    password: str = "changeme"
    host: str = "0.0.0.0"
    port: int = 8080
    documents_dir: str = "~/Documents/Writer"


@dataclass
class WriterConfig:
    """Complete Writer configuration."""
    ai: AIConfig
    display: DisplayConfig
    editor: EditorConfig
    web: WebConfig = None

    def __post_init__(self):
        if self.web is None:
            self.web = WebConfig()


def load_config() -> WriterConfig:
    """
    Load configuration from file.

    Returns:
        WriterConfig object with all settings
    """
    ai = AIConfig()
    display = DisplayConfig()
    editor = EditorConfig()

    if not CONFIG_FILE.exists():
        return WriterConfig(ai=ai, display=display, editor=editor, web=WebConfig())

    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)

    # Load AI config
    if 'ai' in config:
        ai_section = config['ai']
        ai.provider = ai_section.get('provider', ai.provider)
        ai.openai_api_key = ai_section.get('openai_api_key')
        ai.anthropic_api_key = ai_section.get('anthropic_api_key')
        ai.openai_model = ai_section.get('openai_model', ai.openai_model)
        ai.claude_model = ai_section.get('claude_model', ai.claude_model)

        # Don't use placeholder values
        if ai.openai_api_key and ai.openai_api_key.startswith('sk-your'):
            ai.openai_api_key = None
        if ai.anthropic_api_key and ai.anthropic_api_key.startswith('sk-ant-your'):
            ai.anthropic_api_key = None

    # Load display config
    if 'display' in config:
        display_section = config['display']
        display.suggestion_count = display_section.getint('suggestion_count', display.suggestion_count)
        display.outline_ai_enhance = display_section.getboolean('outline_ai_enhance', display.outline_ai_enhance)
        display.outline_refresh_interval = display_section.getfloat('outline_refresh_interval', display.outline_refresh_interval)

    # Load editor config
    if 'editor' in config:
        editor_section = config['editor']
        editor.context_lines_before = editor_section.getint('context_lines_before', editor.context_lines_before)
        editor.context_lines_after = editor_section.getint('context_lines_after', editor.context_lines_after)
        editor.writing_style = editor_section.get('writing_style')
        # Treat empty string as None
        if editor.writing_style and not editor.writing_style.strip():
            editor.writing_style = None

    # Load web config
    web = WebConfig()
    if 'web' in config:
        web_section = config['web']
        web.username = web_section.get('username', web.username)
        web.password = web_section.get('password', web.password)
        web.host = web_section.get('host', web.host)
        web.port = web_section.getint('port', web.port)
        web.documents_dir = web_section.get('documents_dir', web.documents_dir)

    return WriterConfig(ai=ai, display=display, editor=editor, web=web)


def get_api_key(provider: str, config: Optional[WriterConfig] = None) -> Optional[str]:
    """
    Get API key for the specified provider.

    Args:
        provider: "openai" or "claude"
        config: Optional config object (loads from file if not provided)

    Returns:
        API key string or None if not configured
    """
    if config is None:
        config = load_config()

    if provider == "openai":
        return config.ai.openai_api_key
    elif provider in ("claude", "anthropic"):
        return config.ai.anthropic_api_key
    else:
        return None


def validate_config(config: WriterConfig) -> list[str]:
    """
    Validate configuration and return list of issues.

    Args:
        config: Configuration to validate

    Returns:
        List of error messages (empty if valid)
    """
    issues = []

    # Check API key for selected provider
    if config.ai.provider == "openai" and not config.ai.openai_api_key:
        issues.append("OpenAI API key not configured (provider is set to 'openai')")
    elif config.ai.provider == "claude" and not config.ai.anthropic_api_key:
        issues.append("Anthropic API key not configured (provider is set to 'claude')")

    # Check display settings
    if not 1 <= config.display.suggestion_count <= 5:
        issues.append("suggestion_count must be between 1 and 5")

    return issues


if __name__ == "__main__":
    # Test configuration loading
    config = load_config()
    print(f"AI Provider: {config.ai.provider}")
    print(f"OpenAI Key: {'set' if config.ai.openai_api_key else 'not set'}")
    print(f"Anthropic Key: {'set' if config.ai.anthropic_api_key else 'not set'}")
    print(f"Suggestions: {config.display.suggestion_count}")

    issues = validate_config(config)
    if issues:
        print("\nConfiguration issues:")
        for issue in issues:
            print(f"  - {issue}")
    else:
        print("\nConfiguration valid!")
