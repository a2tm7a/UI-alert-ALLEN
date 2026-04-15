"""
URL and auth-session configuration for WatchDog.

Loads config/urls.yaml and provides:
  - UrlConfig.get_all_tasks()              → all (section, url) pairs for guest pass
  - UrlConfig.get_tasks_for_stream(stream) → stream-filtered pairs for auth passes
  - UrlConfig.auth_sessions               → ordered list of AuthSession entries
"""
import logging
import yaml
from typing import List, Optional, Tuple
from pydantic import BaseModel, Field

# Maps YAML stream names to auth_session.py profile keys expected by switch_profile().
STREAM_TO_PROFILE: dict[str, str] = {
    "JEE": "JEE",
    "NEET": "NEET",
    "Class 6-10": "Classes610",
}


class AuthSession(BaseModel):
    """One login session: stream × class (× optional board)."""

    stream: str
    class_: str = Field(alias="class")
    board: str = "CBSE"

    model_config = {"populate_by_name": True}

    @property
    def auth_profile(self) -> str:
        """Return the profile key expected by AuthSession.switch_profile()."""
        profile = STREAM_TO_PROFILE.get(self.stream)
        if profile is None:
            raise ValueError(
                f"Unknown stream '{self.stream}'. "
                f"Valid options: {list(STREAM_TO_PROFILE)}"
            )
        return profile


class UrlEntry(BaseModel):
    """One URL entry with its page section and optional stream tags."""

    url: str
    section: str
    streams: List[str] = []


class UrlConfig(BaseModel):
    """
    Full URL + auth-session configuration.

    Execution contract:
      1. Guest pass   — get_all_tasks() → run all checks on all URLs
      2. Auth passes  — for each session in auth_sessions:
                          set WATCHDOG_PROFILE_CLASS = session.class_
                          call switch_profile(session.auth_profile)
                          run all checks on get_tasks_for_stream(session.stream)
    """

    version: int = 1
    auth_sessions: List[AuthSession] = []
    urls: List[UrlEntry] = []

    def get_all_tasks(self) -> List[Tuple[str, str]]:
        """Return (section, url) tuples for all URLs. Used by the guest pass."""
        return [(entry.section, entry.url) for entry in self.urls]

    def get_tasks_for_stream(self, stream: str) -> List[Tuple[str, str]]:
        """Return (section, url) tuples for URLs tagged with the given stream."""
        return [
            (entry.section, entry.url)
            for entry in self.urls
            if stream in entry.streams
        ]

    @classmethod
    def load(cls, path: str = "config/urls.yaml") -> "UrlConfig":
        """
        Load UrlConfig from a YAML file.

        Returns an empty config on FileNotFoundError so the scraper degrades
        gracefully when the config file is missing (e.g. first-run setup).
        Raises on malformed YAML so misconfigurations surface immediately.
        """
        try:
            with open(path, encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
            if not data:
                logging.warning("URL config %s is empty — no URLs or sessions loaded", path)
                return cls()
            return cls.model_validate(data)
        except FileNotFoundError:
            logging.warning(
                "URL config %s not found — no URLs or auth sessions loaded", path
            )
            return cls()
