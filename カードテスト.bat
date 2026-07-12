@echo off
setlocal
cd /d "%~dp0"
title トキワ カード読み取りテスト

echo ============================================
echo   トキワ カード読み取りテスト（TCP300II）
echo ============================================
echo.
echo  ※ カードには書き込みません（読み取り専用）。
echo  ※ COM ポートを直接使うため、宝飾ナビを終了してから実行してください。
echo.
pause

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY ( where python3 >nul 2>nul && set "PY=python3" )
if not defined PY goto NOPY
%PY% --version
if errorlevel 1 goto NOPY
echo.

%PY% -c "import serial" 2>nul
if errorlevel 1 (
  echo pyserial を導入します（初回のみ・ネット接続が必要）...
  %PY% -m pip install pyserial
  if errorlevel 1 goto NOSERIAL
)

%PY% hardware\card_test.py
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
