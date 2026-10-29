"""Paths, .env loading and campaign loading."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CACHE = DATA / "cache"
OUTPUT = ROOT / "output"
CAMPAIGNS = ROOT / "campaigns"
DEFAULTS = CAMPAIGNS / "_defaults.json"
DEFAULT_CAMPAIGN = CAMPAIGNS / "edxso_parenting_education.json"


def load_env(path: Path = ROOT / ".env") -> None:
    """Minimal .env reader so the project has zero third-party dependencies."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def env(name: str, default: str | None = None, required: bool = False) -> str | None:
    val = os.environ.get(name, default)
    if required and not val:
        raise SystemExit(f"Missing {name}. Copy .env.example to .env and fill it in.")
    return val


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def load_campaign(path: str | Path | None = None) -> dict:
    """Campaign file merged over campaigns/_defaults.json; `brand_safety_extra` is appended to the base blocklist."""
    c = _merge(json.loads(DEFAULTS.read_text(encoding="utf-8")),
               json.loads(Path(path or DEFAULT_CAMPAIGN).read_text(encoding="utf-8")))
    f = c["filters"]
    f["brand_safety_blocklist"] = f["brand_safety_blocklist"] + f.pop("brand_safety_extra", [])
    return c


def all_campaigns() -> list[dict]:
    return [load_campaign(p) for p in sorted(CAMPAIGNS.glob("*.json")) if not p.name.startswith("_")]


def stage_path(campaign: dict, stage: str) -> Path:
    return DATA / campaign["id"] / f"{stage}.json"


def save_stage(campaign: dict, stage: str, records) -> Path:
    p = stage_path(campaign, stage)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    return p


def load_stage(campaign: dict, stage: str):
    p = stage_path(campaign, stage)
    if not p.exists():
        raise SystemExit(f"{p} not found. Run the previous stage first (python -m outreach run).")
    return json.loads(p.read_text(encoding="utf-8"))


load_env()
for d in (DATA, CACHE, OUTPUT):
    d.mkdir(parents=True, exist_ok=True)
