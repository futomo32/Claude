@echo off
rem ==============================================================
rem  Kashikari note - starter for Windows
rem  Double-click this file to start the server.
rem  (This file must keep CRLF line endings and ASCII only.)
rem  Japanese messages are printed by Node.js itself.
rem ==============================================================
setlocal
cd /d "%~dp0"

where node >nul 2>nul
if errorlevel 1 goto NONODE

chcp 65001 >nul
node server.js
echo.
echo Server stopped.  -  sabaa wo shuuryou shimashita.
echo.
pause
exit /b 0

:NONODE
echo.
echo  [!] Node.js is not installed on this PC.
echo      Node.js ga hairtte imasen.
echo.
echo      Please install the LTS version from:
echo        https://nodejs.org/ja
echo      ...then double-click this file again.
echo.
start https://nodejs.org/ja
pause
exit /b 1
