@echo off
rem ---------------------------------------------------------------
rem  Kashikari note - starter for Windows (double-click this file)
rem  Messages below are printed by Node.js in Japanese.
rem ---------------------------------------------------------------
chcp 65001 >nul
cd /d "%~dp0"

where node >nul 2>nul
if errorlevel 1 (
  echo.
  echo  [!] Node.js is not installed.
  echo      Node.js が入っていません。
  echo.
  echo      https://nodejs.org/ja  から LTS 版を入れてから、
  echo      もう一度このファイルをダブルクリックしてください。
  echo.
  start https://nodejs.org/ja
  pause
  exit /b 1
)

node server.js
echo.
echo  サーバーを終了しました。
pause
