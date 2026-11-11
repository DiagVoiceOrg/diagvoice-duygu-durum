"""
registry.yaml okuma, yol çözme ve SHA256 doğrulama.

SHA256 sonuçları (yol, boyut, mtime) anahtarıyla önbelleğe yazılır; dosya değişmediği sürece
yeniden açılışta tekrar hesaplanmaz.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

BACKEND_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REGISTRY = BACKEND_ROOT / "registry.yaml"


@dataclass
class Artifact:
    name: str
    path: Path
    sha256: Optional[str]
    env: Optional[str]


@dataclass
class ModelEntry:
    id: str
    title: str
    version: str
    group: str
    module: str
    artifacts: list[Artifact]
    env: dict[str, str] = field(default_factory=dict)
    env_dirs: dict[str, Path] = field(default_factory=dict)
    env_urls: dict[str, str] = field(default_factory=dict)
    sys_path: list[Path] = field(default_factory=list)
    startup: list[str] = field(default_factory=list)
    require: list[str] = field(default_factory=list)
    lifespan: Optional[str] = None
    health: Optional[str] = None
    enabled: bool = True
    v1: Optional[dict[str, Any]] = None


@dataclass
class Registry:
    path: Path
    model_root: Path
    models: dict[str, ModelEntry]
    pipelines: dict[str, list[str]]

    def group(self, name: str) -> list[ModelEntry]:
        return [m for m in self.models.values() if m.group == name and m.enabled]


def _resolve(root: Path, p: str) -> Path:
    q = Path(p)
    return q if q.is_absolute() else (root / q)


def load(path: Optional[str | Path] = None) -> Registry:
    path = Path(path or os.environ.get("REGISTRY_PATH") or DEFAULT_REGISTRY)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw_root = os.environ.get("MODEL_ROOT") or data.get("model_root") or str(BACKEND_ROOT / "models")
    root = Path(str(raw_root).replace("{backend}", str(BACKEND_ROOT)))
    models: dict[str, ModelEntry] = {}
    for mid, m in (data.get("models") or {}).items():
        arts = [
            Artifact(name=an, path=_resolve(root, a["path"]), sha256=(a.get("sha256") or None), env=a.get("env"))
            for an, a in (m.get("artifacts") or {}).items()
        ]
        models[mid] = ModelEntry(
            id=mid,
            title=m.get("title", mid),
            version=str(m.get("version", "")),
            group=m.get("group", "gpu"),
            module=m["module"],
            artifacts=arts,
            env={k: str(v).replace("{backend}", str(BACKEND_ROOT)).replace("{model_root}", str(root))
                 for k, v in (m.get("env") or {}).items()},
            env_dirs={k: _resolve(root, v) for k, v in (m.get("env_dirs") or {}).items()},
            env_urls={k: str(v) for k, v in (m.get("env_urls") or {}).items()},
            sys_path=[_resolve(BACKEND_ROOT, p) for p in (m.get("sys_path") or [])],
            startup=list(m.get("startup") or []),
            require=list(m.get("require") or []),
            lifespan=m.get("lifespan"),
            health=m.get("health"),
            enabled=bool(m.get("enabled", True)),
            v1=m.get("v1"),
        )
    pipelines = {k: list(v) for k, v in (data.get("pipelines") or {}).items()}
    for name, ids in pipelines.items():
        missing = [i for i in ids if i not in models]
        if missing:
            raise ValueError(f"registry: '{name}' pipeline'ında tanımsız model: {missing}")
    return Registry(path=path, model_root=root, models=models, pipelines=pipelines)


# --------------------------------------------------------------------------- SHA256
def _cache_path() -> Path:
    return Path(os.environ.get("DV_SHA_CACHE") or (BACKEND_ROOT / ".cache" / "dv_sha256.json"))


def _read_cache() -> dict:
    try:
        return json.loads(_cache_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_cache(c: dict) -> None:
    try:
        p = _cache_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(c, indent=1), encoding="utf-8")
    except Exception:
        pass


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify(entry: ModelEntry) -> list[str]:
    """Hata listesi döner (boş = tamam)."""
    errors: list[str] = []
    cache = _read_cache()
    changed = False
    for a in entry.artifacts:
        if not a.path.is_file():
            errors.append(f"{a.name}: dosya yok ({a.path})")
            continue
        if not a.sha256:
            continue
        st = a.path.stat()
        key = f"{a.path}|{st.st_size}|{int(st.st_mtime)}"
        digest = cache.get(key)
        if digest is None:
            digest = sha256_file(a.path)
            cache[key] = digest
            changed = True
        if digest != a.sha256:
            errors.append(f"{a.name}: SHA256 uyuşmuyor ({a.path.name}: {digest[:12]}… ≠ {a.sha256[:12]}…)")
    if changed:
        _write_cache(cache)
    return errors
