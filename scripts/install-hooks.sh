#!/usr/bin/env bash
# Install git hooks (macOS / Linux):
#   - pre-commit  : "收口即审计" consistency audit
#   - commit-msg  : Conventional Commits 提交信息规范 lint
set -e
REPO="$(cd "$(dirname "$0")/.." && pwd)"
HOOKS_DIR="$REPO/.git/hooks"
mkdir -p "$HOOKS_DIR"
cp "$REPO/scripts/git-hooks/pre-commit" "$HOOKS_DIR/pre-commit"
chmod +x "$HOOKS_DIR/pre-commit"
cp "$REPO/scripts/git-hooks/commit-msg" "$HOOKS_DIR/commit-msg"
chmod +x "$HOOKS_DIR/commit-msg"
# Clear a possibly broken core.hooksPath (e.g. pointing at a file)
git -C "$REPO" config --unset core.hooksPath 2>/dev/null || true
echo "[install-hooks] OK: pre-commit hook installed to $HOOKS_DIR/pre-commit"
echo "[install-hooks] OK: commit-msg hook installed to $HOOKS_DIR/commit-msg"
echo "[install-hooks] Consistency audit + commit-msg lint will now run on every commit."
echo "[install-hooks] To skip once: git commit --no-verify"
echo "[install-hooks]   skip audit only : SKIP_CONSISTENCY_AUDIT=1 git commit ..."
echo "[install-hooks]   skip lint  only : SKIP_COMMIT_MSG_LINT=1 git commit ..."
