@echo off
setlocal
REM ============================================================
REM  Install git hooks (Windows). For macOS/Linux see install-hooks.sh
REM    - pre-commit : "收口即审计" consistency audit
REM    - commit-msg : Conventional Commits 提交信息规范 lint
REM  Run once after clone.
REM ============================================================
set "SCRIPT_DIR=%~dp0"
REM repo root = scripts\..
set "REPO=%SCRIPT_DIR%.."
set "HOOKS_DIR=%REPO%\.git\hooks"

if not exist "%HOOKS_DIR%" (
  echo [install-hooks] ERROR: .git\hooks not found. Are you inside the git repo?
  exit /b 1
)

copy /Y "%SCRIPT_DIR%git-hooks\pre-commit" "%HOOKS_DIR%\pre-commit" >nul
if errorlevel 1 (
  echo [install-hooks] ERROR: failed to copy pre-commit hook.
  exit /b 1
)

copy /Y "%SCRIPT_DIR%git-hooks\commit-msg" "%HOOKS_DIR%\commit-msg" >nul
if errorlevel 1 (
  echo [install-hooks] ERROR: failed to copy commit-msg hook.
  exit /b 1
)

REM Fix: clear a possibly broken core.hooksPath (e.g. pointing at a file)
git config --unset core.hooksPath 2>nul

echo [install-hooks] OK: pre-commit hook installed to %HOOKS_DIR%\pre-commit
echo [install-hooks] OK: commit-msg hook installed to %HOOKS_DIR%\commit-msg
echo [install-hooks] Consistency audit + commit-msg lint will now run on every commit.
echo [install-hooks] To skip once:  git commit --no-verify
echo [install-hooks]   skip audit only : set SKIP_CONSISTENCY_AUDIT=1
echo [install-hooks]   skip lint  only : set SKIP_COMMIT_MSG_LINT=1
endlocal
