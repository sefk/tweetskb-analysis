#!/usr/bin/env python3
"""
Extract and collate all user prompts from Claude Code session files for this project.

Usage:
    python extract_session_prompts.py [--output OUTPUT]

Output defaults to session_prompts.md in the project root.
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

SESSION_DIR = Path.home() / ".claude/projects/-Users-sefk-src-stanford-dataviz-tweetskb-analysis"
DEFAULT_OUTPUT = Path(__file__).parent / "session_prompts.md"

SKIP_PREFIXES = [
    "<local-command",
    "<command-name",
    "<command-message",
    "<command-args",
    "<system-reminder",
    "<local-command-stdout",
    "<local-command-caveat",
    "<user-prompt-submit-hook",
]


def extract_prompts(session_dir: Path) -> list[dict]:
    jsonl_files = sorted(session_dir.glob("*.jsonl"))
    prompts = []

    for fpath in jsonl_files:
        with open(fpath) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if entry.get("type") != "user":
                    continue
                if entry.get("isMeta"):
                    continue

                msg = entry.get("message", {})
                if msg.get("role") != "user":
                    continue

                content = msg.get("content", "")
                if not isinstance(content, str):
                    continue

                content = content.strip()
                if not content:
                    continue

                if any(content.startswith(p) for p in SKIP_PREFIXES):
                    continue
                if content.startswith("<") and content.endswith(">"):
                    continue

                ts = entry.get("timestamp", "")
                try:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    ts_fmt = dt.strftime("%Y-%m-%d %H:%M UTC")
                except Exception:
                    ts_fmt = ts

                prompts.append({
                    "timestamp": ts_fmt,
                    "session_id": fpath.stem,
                    "content": content,
                })

    prompts.sort(key=lambda x: x["timestamp"])
    return prompts, len(jsonl_files)


def write_markdown(prompts: list[dict], n_sessions: int, output: Path) -> None:
    with open(output, "w") as f:
        f.write("# TweetsKB Analysis — All User Prompts\n\n")
        f.write(f"Extracted from {n_sessions} session files. Total: {len(prompts)} prompts.\n\n")
        f.write("---\n\n")

        cur_session = None
        for i, p in enumerate(prompts, 1):
            if p["session_id"] != cur_session:
                cur_session = p["session_id"]
                f.write(f"\n## Session `{cur_session[:8]}`\n\n")

            f.write(f"### [{i}] {p['timestamp']}\n\n")
            f.write(p["content"])
            f.write("\n\n---\n\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help="Output markdown file (default: session_prompts.md)")
    args = parser.parse_args()

    if not SESSION_DIR.exists():
        print(f"Session directory not found: {SESSION_DIR}")
        raise SystemExit(1)

    prompts, n_sessions = extract_prompts(SESSION_DIR)
    write_markdown(prompts, n_sessions, args.output)

    print(f"Extracted {len(prompts)} prompts from {n_sessions} sessions.")
    print(f"Written to: {args.output}")


if __name__ == "__main__":
    main()
