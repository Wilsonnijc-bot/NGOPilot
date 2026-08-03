@ECHO OFF
SETLOCAL

SET "WHEEL_NAME=ngopilot_mcp-0.1.0-py3-none-any.whl"
SET "WHEEL_PATH=%NGOPILOT_MCP_WHEEL%"

IF DEFINED WHEEL_PATH IF NOT EXIST "%WHEEL_PATH%" (
  ECHO NGOPilotMCP wheel not found at NGOPILOT_MCP_WHEEL=%WHEEL_PATH%. 1>&2
  EXIT /B 1
)
IF NOT DEFINED WHEEL_PATH IF EXIST "%~dp0..\%WHEEL_NAME%" SET "WHEEL_PATH=%~dp0..\%WHEEL_NAME%"
IF NOT DEFINED WHEEL_PATH IF EXIST "%~dp0..\..\..\..\..\MCPcode\dist\%WHEEL_NAME%" SET "WHEEL_PATH=%~dp0..\..\..\..\..\MCPcode\dist\%WHEEL_NAME%"

IF NOT DEFINED WHEEL_PATH (
  ECHO NGOPilotMCP wheel not found. Expected packaged %WHEEL_NAME%. 1>&2
  EXIT /B 1
)

IF NOT EXIST "%~dp0uvx.exe" (
  ECHO NGOPilotMCP requires the bundled uvx.exe launcher. 1>&2
  EXIT /B 1
)

IF NOT DEFINED NGOPILOT_MCP_STATE_DIR SET "NGOPILOT_MCP_STATE_DIR=%USERPROFILE%\.ngopilot-mcp"
IF NOT EXIST "%NGOPILOT_MCP_STATE_DIR%" MKDIR "%NGOPILOT_MCP_STATE_DIR%"
CD /D "%NGOPILOT_MCP_STATE_DIR%"

REM Keep bootstrap output off stdout because stdout is reserved for MCP messages.
"%~dp0uvx.exe" --python 3.12 --from "%WHEEL_PATH%" ngopilot-mcp bootstrap 1>&2
IF ERRORLEVEL 1 EXIT /B %ERRORLEVEL%

IF NOT EXIST "%NGOPILOT_MCP_STATE_DIR%\runtimes\careflow\.venv\Scripts\python.exe" (
  ECHO NGOPilotMCP bootstrap did not provision the careflow runtime. 1>&2
  EXIT /B 1
)
IF NOT EXIST "%NGOPILOT_MCP_STATE_DIR%\runtimes\rostercopiilot\.venv\Scripts\python.exe" (
  ECHO NGOPilotMCP bootstrap did not provision the rostercopiilot runtime. 1>&2
  EXIT /B 1
)

"%~dp0uvx.exe" --python 3.12 --from "%WHEEL_PATH%" ngopilot-mcp %*
EXIT /B %ERRORLEVEL%
