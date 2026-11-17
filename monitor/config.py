"""Settings from the environment and series definitions from config/terms.toml."""

from __future__ import annotations

import os
import re
import tomllib
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from monitor import ROOT

FAMILIES = ("anti-trans", "framing")
FAMILY_LABELS = {"anti-trans": "Anti-trans terms", "framing": "Framing terms"}
MIN_PRECISION = 0.70
MAX_QUERY_LENGTH = 1024
QUERY_SUFFIX = " lang:en -is:retweet"

METRICS = (
    ("posts", "POSTS / H"),
    ("reposts", "REPOSTS / H"),
    ("replies", "REPLIES / H"),
    ("repost-share", "% REPOSTS"),
)


def load_dotenv(path: Path = ROOT / ".env") -> None:
    """Minimal .env reader: KEY=VALUE lines, existing environment wins."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def slug(text: str) -> str:
    # Accents are dropped first, so "fútbol" becomes "futbol" rather than "f-tbol".
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")


@dataclass(frozen=True)
class Settings:
    db_path: Path
    x_bearer_token: str
    x_max_requests_per_day: int
    usage_file: Path
    public_url: str

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        env = os.environ.get

        def path(name: str, default: str) -> Path:
            p = Path(env(name, default))
            return p if p.is_absolute() else ROOT / p

        return cls(
            db_path=path("MONITOR_DB", "data/monitor.db"),
            x_bearer_token=env("X_BEARER_TOKEN", ""),
            x_max_requests_per_day=int(env("X_MAX_REQUESTS_PER_DAY", "150")),
            usage_file=path("TWITTER_USAGE_FILE", "data/x_usage.json"),
            public_url=env("MONITOR_PUBLIC_URL", "").rstrip("/"),
        )


@dataclass(frozen=True)
class Term:
    id: str
    label: str
    family: str  # "anti-trans" | "framing" | "context"
    query: str
    source: str
    source_url: str
    precision: float | None
    precision_n: int | None
    precision_ci: tuple[float, float] | None
    added: str


@dataclass(frozen=True)
class SeriesSpec:
    key: str
    label: str
    unit: str
    family: str  # "anti-trans" | "framing" | "context" | "probe"
    term_id: str | None
    metric: str  # "posts" | "reposts" | "replies" | "repost-share"
    query: str
    endpoint: str  # "recent" | "all"


@dataclass(frozen=True)
class Config:
    terms: tuple[Term, ...]
    series: tuple[SeriesSpec, ...]
    probe_query: str
    family_queries: dict[str, str]


def _parse_term(raw: dict) -> Term:
    for field in ("id", "label", "family", "query", "source", "source_url", "added"):
        if not str(raw.get(field, "")).strip():
            raise ValueError(f"term {raw.get('id', '?')!r} is missing {field}")
    if raw["family"] not in (*FAMILIES, "context"):
        raise ValueError(f"term {raw['id']!r} has unknown family {raw['family']!r}")
    ci = raw.get("precision_ci")
    term = Term(
        id=raw["id"], label=raw["label"], family=raw["family"], query=raw["query"],
        source=raw["source"], source_url=raw["source_url"],
        precision=raw.get("precision"), precision_n=raw.get("precision_n"),
        precision_ci=(float(ci[0]), float(ci[1])) if ci else None, added=str(raw["added"]),
    )
    if term.family in FAMILIES and (term.precision is None or term.precision < MIN_PRECISION):
        raise ValueError(
            f"term {term.id!r} is in family {term.family!r} but its precision is "
            f"{term.precision}; a family term needs at least {MIN_PRECISION}"
        )
    return term


def load_config(directory: Path = ROOT / "config") -> Config:
    data = tomllib.loads((Path(directory) / "terms.toml").read_text(encoding="utf-8"))
    probe_query = data["probe"]["query"]
    terms = tuple(_parse_term(raw) for raw in data.get("term", []))
    ids = [t.id for t in terms]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate term id in terms.toml")

    family_queries: dict[str, str] = {}
    for family in FAMILIES:
        members = [t for t in terms if t.family == family]
        if not members:
            continue
        query = "(" + " OR ".join(t.query for t in members) + ")"
        length = len(query + QUERY_SUFFIX)
        if length > MAX_QUERY_LENGTH:
            raise ValueError(
                f"family {family!r} query is {length} characters with filters; "
                f"the limit is {MAX_QUERY_LENGTH}"
            )
        family_queries[family] = query

    series: list[SeriesSpec] = []
    for t in terms:
        for metric, unit in METRICS:
            series.append(SeriesSpec(
                key=f"x.{slug(t.query)}.en.{metric}", label=t.label, unit=unit, family=t.family,
                term_id=t.id, metric=metric, query=t.query, endpoint="recent",
            ))
    for family, query in family_queries.items():
        series.append(SeriesSpec(
            key=f"x.family.{family}.en.posts", label=FAMILY_LABELS[family], unit="POSTS / H",
            family=family, term_id=None, metric="posts", query=query, endpoint="all",
        ))
    series.append(SeriesSpec(
        key="x.probe.en.posts", label="Probe", unit="POSTS / H", family="probe",
        term_id=None, metric="posts", query=probe_query, endpoint="all",
    ))
    return Config(terms=terms, series=tuple(series), probe_query=probe_query, family_queries=family_queries)
