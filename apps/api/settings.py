"""Runtime paths and settings, resolved once.

Everything that touches the filesystem lives here so a test can point the whole app at a temporary
directory without monkey-patching six modules.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    db_path: Path
    jobs_dir: Path
    secrets_dir: Path
    studio_config: Path
    api_token: str = ""
    allow_origins: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_env(cls, *, root: Path | None = None) -> Settings:
        base = Path(root) if root else PROJECT_ROOT
        data = Path(os.environ.get("SHORTS_DATA_DIR", base / "data"))
        return cls(
            data_dir=data,
            db_path=Path(os.environ.get("SHORTS_DB_PATH", data / "factory.db")),
            jobs_dir=Path(os.environ.get("SHORTS_JOBS_DIR", data / "jobs")),
            secrets_dir=Path(os.environ.get("SHORTS_SECRETS_DIR", data / "secrets")),
            studio_config=Path(
                os.environ.get("SHORTS_STUDIO_CONFIG", base / "config" / "studio.json")
            ),
            api_token=os.environ.get("STUDIO_API_TOKEN", ""),
        )

    def ensure(self) -> Settings:
        for path in (self.data_dir, self.jobs_dir, self.secrets_dir, self.studio_config.parent):
            path.mkdir(parents=True, exist_ok=True)
        return self
