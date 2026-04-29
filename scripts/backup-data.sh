#!/bin/bash
# Snapshot ~/.claude/productivity/*.yaml to a timestamped folder so PR testing
# (or any code change) has a clean restore path.
#
# Usage:
#   scripts/backup-data.sh                 # default: ~/.claude/productivity-backups/<ts>/
#   scripts/backup-data.sh /custom/path    # override target root
#
# Restore is just `cp` from the snapshot back into ~/.claude/productivity/.

set -e

DATA_DIR="$HOME/.claude/productivity"
DEFAULT_BACKUP_ROOT="$HOME/.claude/productivity-backups"
BACKUP_ROOT="${1:-$DEFAULT_BACKUP_ROOT}"

if [ ! -d "$DATA_DIR" ]; then
    echo "No productivity data dir at $DATA_DIR — nothing to back up." >&2
    exit 1
fi

TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
TARGET="$BACKUP_ROOT/$TIMESTAMP"

mkdir -p "$TARGET"

shopt -s nullglob
FILES=("$DATA_DIR"/*.yaml)
shopt -u nullglob

if [ ${#FILES[@]} -eq 0 ]; then
    echo "No yaml files in $DATA_DIR — nothing to back up." >&2
    rmdir "$TARGET" 2>/dev/null || true
    exit 1
fi

cp "${FILES[@]}" "$TARGET/"

echo "Backed up ${#FILES[@]} file(s) to $TARGET"
echo
echo "To restore:"
echo "  cp $TARGET/*.yaml $DATA_DIR/"
