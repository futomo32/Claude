@echo off
setlocal
cd /d "%~dp0"
title トキワ カード書き込みテスト

echo ============================================
echo   トキワ カード書き込みテスト(TCP300II)
echo ============================================
echo.
echo  ★このツールはカードの磁気を【上書き】します。元に戻せません。
echo  ★必ず「消えても構わない予備カード」で実行してください。
echo  ★お客様の会員カードは絶対に使わないでください。
echo.
echo  ※ COM ポートを使うため、宝飾ナビを終了してから実行してください。
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
  rem ★ブロックの中の echo に半角の丸括弧を書かないこと(cmd がそこでブロックを閉じる)
  echo pyserial を導入します（初回のみ・ネット接続が必要）...
  %PY% -m pip install pyserial
  if errorlevel 1 goto NOSERIAL
)

%PY% hardware\card_write_test.py
echo.
pause
endlocal
exit /b 0

:NOPY
echo.
echo [エラー] 使用できる Python が見つかりませんでした。
echo   python.org でインストール時「Add python.exe to PATH」にチェックしてください。
echo.
pause
endlocal
exit /b 1

:NOSERIAL
echo.
echo [エラー] pyserial の導入に失敗しました(ネット未接続などの可能性)。
echo   コマンドプロンプトで手動: pip install pyserial
echo.
pause
endlocal
exit /b 1
