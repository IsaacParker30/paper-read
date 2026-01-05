#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional, List, Tuple
from random import Random

DB_PATH_DEFAULT = Path.home() / ".paperforest.db"
MIN_WORDS = 100
RAND_SEED = 19

# ---------- DB ----------

def db_connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reading_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paper_title TEXT NOT NULL,
            paper_id TEXT,
            summary TEXT NOT NULL,
            word_count INTEGER NOT NULL,
            logged_on TEXT NOT NULL
        );
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_reading_log_logged_on
        ON reading_log (logged_on);
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_reading_log_paper_id
        ON reading_log (paper_id);
    """)
    conn.commit()
    return conn

# ---------- Core logic ----------

def word_count(text: str) -> int:
    return len([w for w in text.strip().split() if w])

def today_iso() -> str:
    return date.today().isoformat()

def parse_iso(d: str) -> date:
    return datetime.strptime(d, "%Y-%m-%d").date()

def add_log(conn: sqlite3.Connection, title: str, summary: str, paper_id: Optional[str], logged_on: Optional[str]) -> None:
    
    wc = word_count(summary)
    logged = logged_on or today_iso()

    #Retreive paper_id or create new one using date
    if paper_id is not None:
        paper_id = paper_id.strip()
    else:
        #Format as YYYYMMDDNUM where NUM is number of logs that day + 1
        rows = conn.execute(
            "SELECT COUNT(*) FROM reading_log WHERE logged_on = ?",
            (logged,),
        ).fetchone()
        num = rows[0] + 1
        paper_id = f"{logged.replace('-', '')}{num}"


    conn.execute(
        "INSERT INTO reading_log (paper_title, paper_id, summary, word_count, logged_on) VALUES (?, ?, ?, ?, ?)",
        (title.strip(), paper_id, summary.strip(), wc, logged),
    )
    conn.commit()

def get_distinct_days(conn: sqlite3.Connection) -> List[date]:
    rows = conn.execute("SELECT DISTINCT logged_on FROM reading_log ORDER BY logged_on ASC").fetchall()
    return [parse_iso(r[0]) for r in rows]

def compute_streaks(days: List[date]) -> Tuple[int, int]:
    """
    Returns (current_streak, longest_streak) based on distinct logged days.
    Streak rule: consecutive calendar days.
    """
    if not days:
        return (0, 0)

    day_set = set(days)
    # Longest streak
    longest = 1
    for d in days:
        if (d - timedelta(days=1)) not in day_set:
            # d is start of a streak
            run = 1
            cur = d
            while (cur + timedelta(days=1)) in day_set:
                cur += timedelta(days=1)
                run += 1
            longest = max(longest, run)

    # Current streak ends today or yesterday (if you haven't logged today yet, streak isn't extended)
    today = date.today()
    if today in day_set:
        end = today
    elif (today - timedelta(days=1)) in day_set:
        end = today - timedelta(days=1)
    else:
        return (0, longest)

    # Count backwards
    current = 1
    cur = end
    while (cur - timedelta(days=1)) in day_set:
        cur -= timedelta(days=1)
        current += 1

    return (current, longest)

def daily_counts(conn: sqlite3.Connection, last_n: int = 90) -> List[Tuple[date, int]]:
    # Returns list of (date, count) for last_n days
    cutoff = (date.today() - timedelta(days=last_n - 1)).isoformat()
    rows = conn.execute(
        "SELECT logged_on, COUNT(*) FROM reading_log WHERE logged_on >= ? GROUP BY logged_on ORDER BY logged_on ASC",
        (cutoff,),
    ).fetchall()
    return [(parse_iso(d), int(c)) for d, c in rows]

# ---------- Forest rendering (terminal) ----------
SEED_LIST=['🫘','🌰']
SAPLING_LIST= ["🌱"]*10 + ["🌿", "🍃","☘️"]*3 + ["🍀"]  
TREE_LIST = ["🌳", "🌲"]*4 + ["🍄","🍄‍🟫"] 
BUG_LIST=["🐛", "🐞", "🦋", "🐝", "🐜", "🦗", "🐌","🕷️"]
WOODLAND_ANIMAL_LIST = ["🐿️", "🦡", "🦔",  "🦌", "🐭", "🦊", "🐻", "🐺", "🦉", "🦅"]

def stage_for_count(n: int) -> str:
    # Return emoji for given count n
    if n <= 0:
        return '.'
    if n==1:
        rand= Random(RAND_SEED)
        return rand.choice(SEED_LIST)
    if n == 2:
        rand= Random(RAND_SEED)
        return rand.choice(SAPLING_LIST)
    if n == 3:
        rand= Random(RAND_SEED)
        return rand.choice(TREE_LIST)
    if n == 4:
        rand= Random(RAND_SEED)
        return rand.choice(BUG_LIST)
    else:
        rand= Random(RAND_SEED)
        return rand.choice(WOODLAND_ANIMAL_LIST)

def render_forest(conn: sqlite3.Connection, weeks: int = 12) -> str:
    """
    GitHub-style grid: columns are weeks, rows are weekdays (Mon..Sun).
    Each cell is either 0, or the streak stage emoji.
    0 = no log that day = "."
    1 = sapling
    2 = tree
    3 = bug
    4+ = woodland animal
    """

    end = date.today()
    start = end - timedelta(days=weeks * 7 - 1)
    # Build dict date->count
    counts = {d: 0 for d in (start + timedelta(days=i) for i in range((end - start).days + 1))}
    rows = conn.execute(
        "SELECT logged_on, COUNT(*) FROM reading_log WHERE logged_on BETWEEN ? AND ? GROUP BY logged_on",
        (start.isoformat(), end.isoformat()),
    ).fetchall()
    
    #Get counts
    for d_iso, c in rows:
        counts[parse_iso(d_iso)] = int(c)

    #Get streak for each day
    for d in counts.keys():
        day_streak = 0
        cur = d
        while (cur - timedelta(days=1)) in counts and counts[cur - timedelta(days=1)] > 0:
            cur -= timedelta(days=1)
            day_streak += 1
        counts[d] = day_streak + 1 if counts[d] > 0 else 0

    # Align start to Monday for nice grid
    # Our rows: Mon..Sun
    start_aligned = start - timedelta(days=(start.weekday() - 0) % 7)
    days_total = (end - start_aligned).days + 1
    cols = (days_total + 6) // 7

    # Build grid: 7 rows x cols
    grid = [[" " for _ in range(cols)] for _ in range(7)]
    for i in range(days_total):
        d = start_aligned + timedelta(days=i)
        col = i // 7
        row = d.weekday()  # Mon=0..Sun=6
        if d < start or d > end:
            grid[row][col] = " "
        else:
            grid[row][col] = stage_for_count(counts.get(d, 0))

    lines = []
    lines.append(f"PaperForest — last {weeks} weeks (Mon→Sun)")
    weekday_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    for r in range(7):
        lines.append(f"{weekday_labels[r]}  " + "".join(grid[r]))
    return "\n".join(lines)

# ---------- Commands ----------

def cmd_log(args: argparse.Namespace) -> None:
    conn = db_connect(args.db)
    summary = args.summary
    if summary is None:
        # read from stdin
        summary = ""
        print("Paste your 100+ word summary. End with Ctrl-D (Unix) / Ctrl-Z Enter (Windows):\n")

    wc = word_count(summary)
    while wc < MIN_WORDS:
        summary += input() + "\n"
        wc = word_count(summary)
        if wc < MIN_WORDS:
            print(f"Summary is {wc} words; minimum is {MIN_WORDS}.")

    add_log(conn, args.title, summary, args.paper_id, args.date)
    days = get_distinct_days(conn)
    cur, longest = compute_streaks(days)
    print("✅ Logged!")
    print(f"🔥 Current streak: {cur} day(s)")
    print(f"🏆 Longest streak: {longest} day(s)")
    print()
    print(render_forest(conn, weeks=args.weeks))

def cmd_stats(args: argparse.Namespace) -> None:
    conn = db_connect(args.db)
    total = conn.execute("SELECT COUNT(*) FROM reading_log").fetchone()[0]
    days = get_distinct_days(conn)
    cur, longest = compute_streaks(days)
    print(f"Total logs: {total}")
    print(f"Active days: {len(days)}")
    print(f"Current streak: {cur}")
    print(f"Longest streak: {longest}")
    print()
    print(render_forest(conn, weeks=args.weeks))

def cmd_list(args: argparse.Namespace) -> None:
    conn = db_connect(args.db)
    rows = conn.execute(
        "SELECT logged_on, paper_title, word_count, COALESCE(paper_id, '') FROM reading_log ORDER BY logged_on DESC, id DESC LIMIT ?",
        (args.limit,),
    ).fetchall()
    for logged_on, title, wc, pid in rows:
        pid_part = f" [{pid}]" if pid else ""
        print(f"{logged_on} — {wc}w — {title}{pid_part}")

def cmd_remove(args: argparse.Namespace) -> None:
    #Remove a log by title or id
    conn = db_connect(args.db)
    #check if id exists
    row = conn.execute(
        "SELECT COUNT(*) FROM reading_log WHERE paper_id = ?",
        (args.id,),
    ).fetchone()
    if row[0] == 0:
        print(f"❌ No log found with ID {args.id}.")
        return
    conn.execute(
        "DELETE FROM reading_log WHERE paper_id = ?",
        (args.id,),
    )
    conn.commit()
    print(f"✅ Removed log with ID {args.id}.")

def cmd_access(args: argparse.Namespace) -> None:
    conn = db_connect(args.db)
    row = conn.execute(
        "SELECT id, paper_title, summary, word_count, logged_on FROM reading_log WHERE paper_id = ? ORDER BY logged_on DESC LIMIT 1",
        (args.paper_id.strip(),),
    ).fetchone()
    if row is None:
        print(f"❌ No log found with Paper ID '{args.paper_id}'.")
        return
    log_id, title, summary, wc, logged_on = row
    print(f"Log ID: {log_id}")
    print(f"Title: {title}")
    print(f"Logged on: {logged_on}")
    print(f"Word count: {wc}")
    print("Summary:")
    print(summary)
    

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="paperforest", description="Gamify reading papers with a streak + forest.")
    p.add_argument("--db", type=Path, default=DB_PATH_DEFAULT, help=f"SQLite DB path (default: {DB_PATH_DEFAULT})")

    sub = p.add_subparsers(dest="cmd", required=True)

    logp = sub.add_parser("log", help="Log a paper you read")
    logp.add_argument("title", help="Paper title")
    logp.add_argument("--paper-id", help="Optional identifier (DOI, arXiv ID, Zotero key, etc.)")
    logp.add_argument("--summary", help="Summary text (if omitted, will read from stdin)")
    logp.add_argument("--date", help="Override date logged (YYYY-MM-DD). Default: today.")
    logp.add_argument("--weeks", type=int, default=12, help="Weeks to show in forest view")
    logp.set_defaults(func=cmd_log)

    statp = sub.add_parser("stats", help="Show streak + forest")
    statp.add_argument("--weeks", type=int, default=12)
    statp.set_defaults(func=cmd_stats)

    listp = sub.add_parser("list", help="List recent logs")
    listp.add_argument("--limit", type=int, default=10)
    listp.set_defaults(func=cmd_list)

    remp = sub.add_parser("remove", help="Remove a log by ID")
    remp.add_argument("id", type=int, help="Log ID to remove")
    remp.set_defaults(func=cmd_remove)

    accessp = sub.add_parser("access", help="Access a log by paper ID")
    accessp.add_argument("paper_id", help="Paper ID to access")
    accessp.set_defaults(func=cmd_access)

    return p

def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()
