#!/usr/bin/env bash
# Run a SkillCrawl re-check non-interactively (for cron / Task Scheduler / CI).
# Usage: ./run_recheck.sh /path/to/your/project
# Flags below (-p, --allowedTools) are from the Claude Code CLI - confirm with `claude --help`
# on your installed version.
set -euo pipefail
PROJECT_DIR="${1:-$PWD}"
cd "$PROJECT_DIR"
LOG_DIR="$PROJECT_DIR/skillcrawl-reports"
mkdir -p "$LOG_DIR"

claude -p "/skillcrawl" \
  --allowedTools "Bash" "Read" "Write" "Edit" \
  >> "$LOG_DIR/scheduler.log" 2>&1

echo "[$(date)] recheck finished" >> "$LOG_DIR/scheduler.log"
