@echo off
setlocal
cd /d "%~dp0"
title トキワ 機器テスト

echo ==========================================
echo   トキワ 機器テスト（レシート/ドロワー）
echo ==========================================
echo.
echo  ※ このテストは COM ポートを直接使います。
echo     宝飾ナビが起動中だとポートが使用中で開けません。
echo     テスト中は宝飾ナビを終了してください。
echo.
pause

rem ---- Python を探す ----
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY ( where python3 >nul 2>nul && set "PY=python3" )
if not defined PY goto NOPY
%PY% --version
if errorlevel 1 goto NOPY
echo.

rem ---- pyserial を用意 ----
%PY% -c "import serial" 2>nul
if errorlevel 1 (
  echo pyserial を導入します（初回のみ・ネット接続が必要）...
  %PY% -m pip install pyserial
  if errorlevel 1 goto NOSERIAL
)

rem ---- テスト実行 ----
%PY% hardware\kiki_test.py
echo.
pause
endlocal
exit /b 0

:NOPY
echo.
echo [エラー] 使用できる Python が見つかりませんでした。
echo   python.org 版をインストールし「Add python.exe to PATH」にチェックしてください。
echo.
pause
endlocal
exit /b 1

:NOSERIAL
echo.
echo [エラー] pyserial の導入に失敗しました（ネット未接続などの可能性）。
echo   コマンドプロンプトで手動: pip install pyserial
echo.
pause
endlocal
exit /b 1
