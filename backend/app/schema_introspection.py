"""Database metadata extraction + foreign-key join graph.

Inspects the live database (SQLAlchemy reflection) so the app never assumes
an unknown schema. Builds:
  - TableInfo: columns with types, nullability, pk/fk flags, samples
  - JoinGraph: undirected graph of FK edges for join-path planning
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from .logging_config import log


@dataclass
class ColumnInfo:
    name: str
    type: str
    nullable: bool
    is_pk: bool = False
    is_fk: bool = False
    fk_target: Optional[str] = None  # "table.column"
    samples: List[str] = field(default_factory=list)


@dataclass
class TableInfo:
    name: str
    columns: List[ColumnInfo]
    primary_keys: List[str] = field(default_factory=list)
    foreign_keys: List[Dict] = field(default_factory=list)  # {cols, referred_table, referred_cols}
    row_count: int = -1

    @property
    def column_names(self) -> List[str]:
        return [c.name for c in self.columns]

    def describe(self) -> str:
        lines = [f"TABLE {self.name} ({len(self.columns)} cols, ~{self.row_count} rows)"]
        for c in self.columns:
            flags = []
            if c.is_pk:
                flags.append("PK")
            if c.is_fk:
                flags.append(f"FK->{c.fk_target}")
            lines.append(f"  - {c.name}: {c.type}{' NULL' if c.nullable else ' NOT NULL'} {' '.join(flags)}".rstrip())
        return "\n".join(lines)


@dataclass
class SchemaSnapshot:
    tables: Dict[str, TableInfo]
    join_edges: List[Tuple[str, str, str, str]]  # (t1, c1, t2, c2)

    def table_names(self) -> List[str]:
        return list(self.tables.keys())


def extract_schema(engine: Engine, sample_size: int = 3, table_prefix: str = "") -> SchemaSnapshot:
    insp = inspect(engine)
    tables: Dict[str, TableInfo] = {}
    edges: List[Tuple[str, str, str, str]] = []

    # Filter before per-table COUNT/sample work.  Shared databases may contain
    # thousands of unrelated tables and must not be scanned by this service.
    names = [n for n in insp.get_table_names() if not table_prefix or n.startswith(table_prefix)]
    for tname in sorted(names):
        cols_raw = insp.get_columns(tname)
        pk_raw = insp.get_pk_constraint(tname) or {}
        pk_cols = set(pk_raw.get("constrained_columns", []) or [])
        fk_raw = insp.get_foreign_keys(tname)
        fk_map: Dict[str, str] = {}
        for fk in fk_raw:
            ref_table = fk.get("referred_table")
            for lc, rc in zip(fk.get("constrained_columns", []), fk.get("referred_columns", [])):
                fk_map[lc] = f"{ref_table}.{rc}"
                edges.append((tname, lc, ref_table or "", rc))
        # row count + samples (bounded, read-only)
        row_count = -1
        samples: Dict[str, List[str]] = {}
        try:
            with engine.connect() as conn:
                from sqlalchemy import text
                rc = conn.execute(text(f'SELECT COUNT(*) FROM "{tname}"')).scalar()
                row_count = int(rc or 0)
                if row_count > 0:
                    srows = conn.execute(text(f'SELECT * FROM "{tname}" LIMIT {sample_size}')).mappings().all()
                    for r in srows:
                        for k, v in dict(r).items():
                            samples.setdefault(k, []).append("" if v is None else str(v)[:60])
        except Exception as e:
            log.warning("schema sample failed for %s: %s", tname, e)

        tinfo = TableInfo(
            name=tname,
            columns=[
                ColumnInfo(
                    name=c["name"],
                    type=str(c["type"]),
                    nullable=bool(c.get("nullable", True)),
                    is_pk=c["name"] in pk_cols,
                    is_fk=c["name"] in fk_map,
                    fk_target=fk_map.get(c["name"]),
                    samples=samples.get(c["name"], []),
                )
                for c in cols_raw
            ],
            primary_keys=sorted(pk_cols),
            foreign_keys=[
                {"cols": fk.get("constrained_columns"), "referred_table": fk.get("referred_table"),
                 "referred_cols": fk.get("referred_columns")}
                for fk in fk_raw
            ],
            row_count=row_count,
        )
        tables[tname] = tinfo
    log.info("extracted schema: %d tables", len(tables))
    return SchemaSnapshot(tables=tables, join_edges=edges)


def find_join_path(snapshot: SchemaSnapshot, source: str, target: str, max_depth: int = 4) -> List[Tuple[str, str, str, str]]:
    """BFS over join graph to find a join path between two tables."""
    from collections import deque
    adj: Dict[str, List[Tuple[str, Tuple[str, str, str, str]]]] = {}
    for t1, c1, t2, c2 in snapshot.join_edges:
        adj.setdefault(t1, []).append((t2, (t1, c1, t2, c2)))
        adj.setdefault(t2, []).append((t1, (t1, c1, t2, c2)))
    if source == target:
        return []
    q = deque([(source, [])])
    seen = {source}
    while q:
        node, path = q.popleft()
        if len(path) >= max_depth:
            continue
        for nxt, edge in adj.get(node, []):
            if nxt in seen:
                continue
            npath = path + [edge]
            if nxt == target:
                return npath
            seen.add(nxt)
            q.append((nxt, npath))
    return []


def render_join_graph(snapshot: SchemaSnapshot) -> str:
    lines = ["JOIN GRAPH:"]
    for t1, c1, t2, c2 in snapshot.join_edges:
        lines.append(f"  {t1}.{c1} -> {t2}.{c2}")
    return "\n".join(lines)
