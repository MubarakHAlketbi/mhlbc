#!/usr/bin/env python3
"""
logalyzer.py — SQLite-backed log analysis CLI for HashLink verbose parser logs.

Built for LLM-driven investigation: parses 500MB+ verbose logs into a queryable
SQLite database. Enables ad-hoc SQL queries, anomaly detection, and sample
extraction without burning tokens on raw log dumps.

Subcommands:
    index   LOG.md [--db DB] [--light]     Import log into SQLite
    query   DB "SQL" [--fmt json|table]    Run SQL, return results
    errors  DB [--context N]               Extract all errors with context
    stats   DB [--section TAG]             Section counts, timing, anomalies
    sample  DB --section TAG [--n N]       Extract representative samples

Schema (one table):
    entries(line, ts_sec, ts_raw, tag, scope, scope_idx, sub_idx,
            field, raw_bytes, decoded, msg)

Indexed on: tag, (tag, scope_idx), field, (scope, scope_idx)
"""

import argparse
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

# ── Regex patterns ──────────────────────────────────────────────────────────

# Line structure: [HH:MM:SS.mmm] [TAG] message
_LINE_RE = re.compile(
    r"^\[(?P<ts>\d{2}:\d{2}:\d{2}\.\d{3})\]\s+\[(?P<tag>\w+)\]\s+(?P<msg>.+)$"
)

# Scope prefixes in messages: func[78], type[2], opcode[3], global[0], native[5]
_SCOPE_RE = re.compile(
    r"(?P<scope>func|type|opcode|global|native|constant)\[(?P<idx>-?\d+)\]"
)

# Sub-index: regtype[M], field[M], proto[M], binding[M], constructor[M]
_SUBIDX_RE = re.compile(
    r"(?:regtype|field|proto|binding|constructor|arg|debug_file)\[(?P<sub>-?\d+)\]"
)

# VARINT raw/decoded: raw=[XX XX] decoded=N
_RAW_DECODED_RE = re.compile(
    r"raw=\[(?P<raw>[0-9a-fA-F ]*)\]\s+decoded=(?P<decoded>-?\d+)"
)

# Header key=value lines
_HEADER_KV_RE = re.compile(r"(?P<key>\w+)=(?P<value>\S+)")

# ── Helpers ──────────────────────────────────────────────────────────────────

def _ts_to_seconds(ts_str: str, base_ts: float | None = None) -> float:
    """Convert HH:MM:SS.mmm to seconds since midnight, or delta from base_ts."""
    h, m, s = ts_str.split(":")
    sec = int(h) * 3600 + int(m) * 60 + float(s)
    if base_ts is not None:
        return sec - base_ts
    return sec


def _parse_scope_and_field(msg: str) -> tuple[str | None, int | None, int | None, str | None]:
    """
    Extract (scope, scope_idx, sub_idx, field) from a VARINT message.
    Returns Nones for unscoped entries.

    Examples:
      "flags: raw=[01] decoded=1"          -> (None, None, None, "flags")
      "func[0].type: raw=[0e] decoded=14"  -> ("func", 0, None, "type")
      "func[78].regtype[7384840]: ..."     -> ("func", 78, 7384840, "regtype")
      "type[2].field[0].name: ..."         -> ("type", 2, 0, "field.name")
      "type[2].proto[0].findex: ..."       -> ("type", 2, 0, "proto.findex")
    """
    # Find the field name (everything before ": raw=" or ":")
    colon = msg.find(":")
    if colon == -1:
        return None, None, None, None

    path = msg[:colon].strip()
    scope_match = _SCOPE_RE.search(path)
    if not scope_match:
        # Unscoped VARINT (header-level): "flags", "nints", etc.
        return None, None, None, path

    scope = scope_match.group("scope")
    scope_idx = int(scope_match.group("idx"))

    # Remove the scope prefix: "func[78]." -> everything after
    after_scope = path[scope_match.end():]
    if after_scope.startswith("."):
        after_scope = after_scope[1:]

    # Check for sub-index: regtype[7384840] -> sub_idx=7384840, field_base="regtype"
    sub_match = _SUBIDX_RE.search(after_scope)
    sub_idx = None
    if sub_match:
        sub_idx = int(sub_match.group("sub"))
        # Remove sub-index part: "regtype[7384840]" -> just mark field as "regtype"
        field = sub_match.group(0).split("[")[0]
    else:
        # "type", "findex", "nregs", "kind", "name", "super", etc.
        field = after_scope

    return scope, scope_idx, sub_idx, field


def _parse_raw_decoded(msg: str) -> tuple[str | None, int | None]:
    """Extract (raw_bytes_hex, decoded_value) from a VARINT message."""
    m = _RAW_DECODED_RE.search(msg)
    if m:
        return m.group("raw") or None, int(m.group("decoded"))
    return None, None


# ── Indexer ──────────────────────────────────────────────────────────────────

def index_log(log_path: str, db_path: str, light: bool = False) -> tuple[int, float]:
    """
    Parse log file line-by-line and insert into SQLite.

    Returns (total_lines, elapsed_seconds).
    """
    import time
    t0 = time.time()

    log_file = Path(log_path)
    if not log_file.exists():
        print(f"ERROR: Log file not found: {log_path}", file=sys.stderr)
        sys.exit(1)

    # Remove existing DB
    Path(db_path).unlink(missing_ok=True)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA cache_size=-64000")  # 64MB cache

    # Schema
    conn.execute("""
        CREATE TABLE entries (
            line       INTEGER PRIMARY KEY,
            ts_sec     REAL,
            ts_raw     TEXT,
            tag        TEXT NOT NULL,
            scope      TEXT,
            scope_idx  INTEGER,
            sub_idx    INTEGER,
            field      TEXT,
            raw_bytes  TEXT,
            decoded    INTEGER,
            msg        TEXT
        )
    """)

    # Indexes — created after bulk insert for speed
    _create_indexes = """
        CREATE INDEX IF NOT EXISTS idx_tag ON entries(tag);
        CREATE INDEX IF NOT EXISTS idx_tag_scope ON entries(tag, scope_idx);
        CREATE INDEX IF NOT EXISTS idx_field ON entries(field);
        CREATE INDEX IF NOT EXISTS idx_scope ON entries(scope, scope_idx);
        CREATE INDEX IF NOT EXISTS idx_ts ON entries(ts_sec);
    """

    base_ts: float | None = None
    batch: list[tuple] = []
    total = 0
    skipped_varint = 0

    with open(log_path, "r", encoding="utf-8", errors="replace") as fh:
        for line_num, raw_line in enumerate(fh, 1):
            line = raw_line.rstrip("\n\r")
            if not line:
                continue

            m = _LINE_RE.match(line)
            if not m:
                # Non-log lines (separator bars, etc.)
                continue

            ts_raw = m.group("ts")
            tag = m.group("tag")
            msg = m.group("msg")

            # Compute seconds
            if base_ts is None:
                base_ts = _ts_to_seconds(ts_raw)
            ts_sec = _ts_to_seconds(ts_raw, base_ts)

            scope: str | None = None
            scope_idx: int | None = None
            sub_idx: int | None = None
            field: str | None = None
            raw_bytes: str | None = None
            decoded: int | None = None

            # Parse VARINT lines for structured data
            if tag == "VARINT":
                scope, scope_idx, sub_idx, field = _parse_scope_and_field(msg)
                raw_bytes, decoded = _parse_raw_decoded(msg)

                # Light mode: skip regtype lines (they dominate the log)
                if light and field == "regtype":
                    skipped_varint += 1
                    continue

                # Light mode: skip type-scoped VARINTs outside func context
                if light and scope == "type":
                    skipped_varint += 1
                    continue

            elif tag in ("HEADER", "FUNC", "TYPE", "OPCODE"):
                sm = _SCOPE_RE.search(msg)
                if sm:
                    scope = sm.group("scope")
                    scope_idx = int(sm.group("idx"))

            batch.append((
                line_num, ts_sec, ts_raw, tag,
                scope, scope_idx, sub_idx, field,
                raw_bytes, decoded, msg,
            ))
            total += 1

            # Batch insert every 5000 rows
            if len(batch) >= 5000:
                conn.executemany(
                    "INSERT INTO entries VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    batch,
                )
                batch.clear()

    # Final batch
    if batch:
        conn.executemany(
            "INSERT INTO entries VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            batch,
        )

    # Create indexes
    conn.executescript(_create_indexes)
    conn.commit()

    # Store metadata
    conn.execute("""
        CREATE TABLE IF NOT EXISTS meta (
            key   TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    conn.execute(
        "INSERT OR REPLACE INTO meta VALUES ('source', ?)", (str(log_file.resolve()),)
    )
    conn.execute(
        "INSERT OR REPLACE INTO meta VALUES ('total_lines', ?)", (str(total),)
    )
    conn.execute(
        "INSERT OR REPLACE INTO meta VALUES ('skipped_varint_light', ?)", (str(skipped_varint),)
    )
    
    # Extract parser version and source file from APP entries
    for row in conn.execute(
        "SELECT msg FROM entries WHERE tag='APP' AND (msg LIKE 'Parser version:%' OR msg LIKE 'File:%')"
    ).fetchall():
        msg = row[0]
        if msg.startswith("Parser version:"):
            ver = msg.split("Parser version:", 1)[1].strip()
            conn.execute("INSERT OR REPLACE INTO meta VALUES ('parser_version', ?)", (ver,))
        elif msg.startswith("File:"):
            fname = msg.split("File:", 1)[1].strip()
            conn.execute("INSERT OR REPLACE INTO meta VALUES ('source_file', ?)", (fname,))
    
    conn.commit()
    conn.close()

    elapsed = time.time() - t0
    return total, elapsed


# ── Query ────────────────────────────────────────────────────────────────────

def run_query(db_path: str, sql: str, fmt: str = "json") -> None:
    """Execute SQL against the DB, output results."""
    if not Path(db_path).exists():
        print(f"ERROR: Database not found: {db_path}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.execute(sql)

    rows = cur.fetchall()
    if not rows:
        print(json.dumps({"count": 0, "rows": []}))
        conn.close()
        return

    if fmt == "json":
        result = {
            "count": len(rows),
            "rows": [dict(r) for r in rows],
        }
        print(json.dumps(result, indent=2, default=str))
    elif fmt == "table":
        # Print as simple aligned table
        cols = [d[0] for d in cur.description]
        # Compute column widths
        widths = [len(c) for c in cols]
        for row in rows:
            for i, val in enumerate(row):
                widths[i] = max(widths[i], len(str(val)))
        # Header
        header = " | ".join(c.ljust(w) for c, w in zip(cols, widths))
        sep = "-+-".join("-" * w for w in widths)
        print(header)
        print(sep)
        for row in rows:
            print(" | ".join(str(v).ljust(w) for v, w in zip(row, widths)))
        print(f"\n{len(rows)} row(s)")
    else:
        print(f"ERROR: Unknown format: {fmt}", file=sys.stderr)
        sys.exit(1)

    conn.close()


# ── Errors ───────────────────────────────────────────────────────────────────

def show_errors(db_path: str, context: int = 10) -> None:
    """Show all ERROR lines with surrounding context."""
    if not Path(db_path).exists():
        print(f"ERROR: Database not found: {db_path}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    errors = conn.execute("SELECT line, msg FROM entries WHERE tag='ERROR'").fetchall()

    if not errors:
        print(json.dumps({"errors": 0, "items": []}))
        conn.close()
        return

    result_items = []
    for err in errors:
        err_line = err["line"]
        lo, hi = max(1, err_line - context), err_line + context

        context_rows = conn.execute(
            "SELECT line, tag, msg FROM entries WHERE line BETWEEN ? AND ? ORDER BY line",
            (lo, hi),
        ).fetchall()

        items = []
        for r in context_rows:
            item = {"line": r["line"], "tag": r["tag"], "msg": r["msg"]}
            if r["line"] == err_line:
                item["error"] = True
            items.append(item)

        result_items.append({
            "error_line": err_line,
            "error_msg": err["msg"],
            "context": items,
        })

    print(json.dumps({"errors": len(errors), "items": result_items}, indent=2))
    conn.close()


# ── Stats ────────────────────────────────────────────────────────────────────

def show_stats(db_path: str, section: str | None = None) -> None:
    """Show section counts, timing, and anomaly detection."""
    if not Path(db_path).exists():
        print(f"ERROR: Database not found: {db_path}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Metadata
    meta_rows = conn.execute("SELECT key, value FROM meta").fetchall()
    meta = dict(meta_rows)

    # Section counts
    tag_filter = f"WHERE tag = '{section}'" if section else ""
    counts = conn.execute(
        f"SELECT tag, COUNT(*) as cnt FROM entries {tag_filter} GROUP BY tag ORDER BY cnt DESC"
    ).fetchall()

    result = {
        "meta": {
            k: meta.get(k, "")
            for k in ["parser_version", "source_file", "source", "total_lines"]
        },
        "sections": [{"tag": r["tag"], "count": r["cnt"]} for r in counts],
    }

    # Timing per section
    timing = conn.execute("""
        SELECT tag,
               MIN(ts_sec) as start_s,
               MAX(ts_sec) as end_s,
               ROUND(MAX(ts_sec) - MIN(ts_sec), 3) as duration_s
        FROM entries
        GROUP BY tag
        ORDER BY duration_s DESC
    """).fetchall()
    result["timing"] = [dict(r) for r in timing]

    # Anomaly detection
    anomalies = []

    # 1. Functions with suspicious regtype counts
    suspicious = conn.execute("""
        SELECT scope_idx as func_idx, COUNT(*) as regtype_count
        FROM entries
        WHERE tag='VARINT' AND scope='func' AND field='regtype'
        GROUP BY scope_idx
        HAVING regtype_count > 1000
        ORDER BY regtype_count DESC
    """).fetchall()
    if suspicious:
        anomalies.append({
            "type": "high_regtype_count",
            "description": "Functions with >1000 regtype entries (likely parse errors)",
            "items": [dict(r) for r in suspicious],
        })

    # 2. Functions with negative nops
    neg_nops = conn.execute("""
        SELECT scope_idx as func_idx
        FROM entries
        WHERE tag='VARINT' AND scope='func' AND field='nops' AND decoded < 0
    """).fetchall()
    if neg_nops:
        anomalies.append({
            "type": "negative_nops",
            "description": "Functions with negative nops (invalid)",
            "items": [dict(r) for r in neg_nops],
        })

    # 3. Functions with zero nops
    zero_nops = conn.execute("""
        SELECT scope_idx as func_idx
        FROM entries
        WHERE tag='VARINT' AND scope='func' AND field='nops' AND decoded = 0
    """).fetchall()
    if zero_nops:
        anomalies.append({
            "type": "zero_nops",
            "description": "Functions with zero opcodes",
            "items": [dict(r) for r in zero_nops],
        })

    # 4. Out-of-range opcodes
    oor_ops = conn.execute("""
        SELECT line, msg
        FROM entries
        WHERE tag='OPCODE' AND msg LIKE '%out-of-range%'
        LIMIT 20
    """).fetchall()
    if oor_ops:
        anomalies.append({
            "type": "out_of_range_opcodes",
            "description": f"Out-of-range opcodes (showing first 20 of many)",
            "count": conn.execute(
                "SELECT COUNT(*) FROM entries WHERE tag='OPCODE' AND msg LIKE '%out-of-range%'"
            ).fetchone()[0],
            "items": [dict(r) for r in oor_ops],
        })

    result["anomalies"] = anomalies
    anomaly_summary: dict = {"total_types": len(anomalies),
                              "total_items": sum(len(a.get("items", [])) for a in anomalies)}
    result["anomaly_summary"] = anomaly_summary

    print(json.dumps(result, indent=2))
    conn.close()


# ── Sample ───────────────────────────────────────────────────────────────────

def show_sample(db_path: str, section_tag: str, n: int = 10) -> None:
    """Extract a representative sample of entries for a given section."""
    if not Path(db_path).exists():
        print(f"ERROR: Database not found: {db_path}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Get count
    count_row = conn.execute(
        "SELECT COUNT(*) FROM entries WHERE tag = ?", (section_tag,)
    ).fetchone()
    total = count_row[0]

    if total == 0:
        print(json.dumps({"section": section_tag, "total": 0, "samples": []}))
        conn.close()
        return

    # Evenly sample across the range: first, last, and n-2 evenly spaced
    if n >= total:
        rows = conn.execute(
            "SELECT * FROM entries WHERE tag = ? ORDER BY line", (section_tag,)
        ).fetchall()
    else:
        step = max(1, total // (n - 1))
        lines = []
        # Get the line numbers to sample
        all_lines = conn.execute(
            "SELECT line FROM entries WHERE tag = ? ORDER BY line", (section_tag,)
        ).fetchall()
        line_nums = [r[0] for r in all_lines]
        indices = [0]  # first
        for i in range(1, n - 1):
            idx = min(i * step, total - 1)
            if idx not in indices:
                indices.append(idx)
        indices.append(total - 1)  # last
        indices = sorted(set(indices))

        rows = conn.execute(
            f"SELECT * FROM entries WHERE line IN ({','.join('?' for _ in indices)}) ORDER BY line",
            [line_nums[i] for i in indices],
        ).fetchall()

    result = {
        "section": section_tag,
        "total": total,
        "samples": [dict(r) for r in rows],
    }
    print(json.dumps(result, indent=2, default=str))
    conn.close()


def show_info(db_path: str) -> None:
    """Display metadata/version info for a database."""
    if not Path(db_path).exists():
        print(f"ERROR: Database not found: {db_path}", file=sys.stderr)
        sys.exit(1)
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT key, value FROM meta ORDER BY key").fetchall()
    conn.close()
    if not rows:
        print(json.dumps({"db": db_path, "meta": {}}, indent=2))
        return
    meta = dict(rows)
    meta["db"] = db_path
    meta["db_size_mb"] = round(os.path.getsize(db_path) / (1024 * 1024), 1)
    print(json.dumps(meta, indent=2))


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="logalyzer — SQLite-backed log analyzer for HL verbose parser logs",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # index
    p_idx = sub.add_parser("index", help="Import log into SQLite")
    p_idx.add_argument("log", help="Path to verbose log .md file")
    p_idx.add_argument("--db", default=None, help="Output DB path (default: <log>.db)")
    p_idx.add_argument("--light", action="store_true",
                       help="Skip regtype and type-scoped VARINT lines (smaller DB)")

    # query
    p_q = sub.add_parser("query", help="Run SQL query against DB")
    p_q.add_argument("db", help="Path to SQLite DB")
    p_q.add_argument("sql", help="SQL query string (or path to .sql file)")
    p_q.add_argument("--fmt", choices=["json", "table"], default="json",
                     help="Output format (default: json)")

    # errors
    p_e = sub.add_parser("errors", help="Extract errors with context")
    p_e.add_argument("db", help="Path to SQLite DB")
    p_e.add_argument("--context", type=int, default=10,
                     help="Lines of context before/after error (default: 10)")

    # stats
    p_s = sub.add_parser("stats", help="Section counts, timing, anomalies")
    p_s.add_argument("db", help="Path to SQLite DB")
    p_s.add_argument("--section", default=None,
                     help="Filter to specific section tag")

    # sample
    p_sm = sub.add_parser("sample", help="Extract sample entries")
    p_sm.add_argument("db", help="Path to SQLite DB")
    p_sm.add_argument("--section", required=True, help="Section tag to sample")
    p_sm.add_argument("--n", type=int, default=10, help="Number of samples (default: 10)")

    # info
    p_i = sub.add_parser("info", help="Show metadata/version info for a database")
    p_i.add_argument("db", help="Path to SQLite DB")

    args = parser.parse_args()

    if args.command == "index":
        db_path = args.db or (Path(args.log).stem + ".db")
        print(f"Indexing {args.log} -> {db_path} ...", file=sys.stderr)
        total, elapsed = index_log(args.log, db_path, light=args.light)
        db_size_mb = os.path.getsize(db_path) / (1024 * 1024)
        print(
            f"Done. {total} lines indexed in {elapsed:.1f}s. "
            f"DB size: {db_size_mb:.0f} MB.",
            file=sys.stderr,
        )

    elif args.command == "query":
        sql = args.sql
        if os.path.isfile(sql):
            with open(sql) as f:
                sql = f.read()
        run_query(args.db, sql, fmt=args.fmt)

    elif args.command == "errors":
        show_errors(args.db, context=args.context)

    elif args.command == "stats":
        show_stats(args.db, section=args.section)

    elif args.command == "sample":
        show_sample(args.db, args.section, n=args.n)

    elif args.command == "info":
        show_info(args.db)


if __name__ == "__main__":
    main()
