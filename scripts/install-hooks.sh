#!/usr/bin/env bash
# Install pre-commit hook for "收口即审计" consistency audit (macOS / Linux).
set -e
REPO="$(cd "$(dirname "$0")/.." && pwd)"
HOOKS_DIR="$REPO/.git/hooks"
mkdir -p "$HOOKS_DIR"
cp "$REPO/scripts/git-hooks/pre-commit" "$HOOKS_DIR/pre-commit"
chmod +x "$HOOKS_DIR/pre-commit"
# Clear a possibly broken core.hooksPath (e.g. pointing at a file)
git -C "$REPO" config --unset core.hooksPath 2>/dev/null || true
echo "[install-hooks] OK: pre-commit hook installed to $HOOKS_DIR/pre-commit"
echo "[install-hooks] Consistency audit will now run on every commit."
echo "[install-hooks] To skip once: git commit --no-verify  (or SKIP_CONSISTENCY_AUDIT=1)"
