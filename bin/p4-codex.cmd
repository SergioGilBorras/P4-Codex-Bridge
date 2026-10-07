@echo off
setlocal
set "_P4_CODEX_PYTHON=%~dp0python.exe"
if not exist "%_P4_CODEX_PYTHON%" (
    echo p4-codex.cmd must be installed beside the Python interpreter of its environment. 1>&2
    echo Use "python -m p4_codex_bridge" with the intended interpreter. 1>&2
    exit /b 9009
)
"%_P4_CODEX_PYTHON%" -m p4_codex_bridge %*
exit /b %ERRORLEVEL%
