@echo off
setlocal
REM ============================================================
REM  Install pre-commit hook for "收口即审计" consistency audit.
REM  Run once after clone (Windows). For macOS/Linux see docs.
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
  echo [install-hooks] ERROR: failed to copy hook.
  exit /b 1
)

REM Fix: clear a possibly broken core.hooksPath (e.g. pointing at a file)
git config --unset core.hooksPath 2>nul

echo [install-hooks] OK: pre-commit hook installed to %HOOKS_DIR%\pre-commit
echo [install-hooks] Consistency audit will now run on every commit.
echo [install-hooks] To skip once:  git commit --no-verify
echo [install-hooks]                  or set SKIP_CONSISTENCY_AUDIT=1
endlocal
