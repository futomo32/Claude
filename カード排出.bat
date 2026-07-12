@echo off
setlocal
cd /d "%~dp0"
title TCP300II カード排出

echo ============================================
echo   TCP300II カード排出ツール
echo ============================================
echo.
echo  中に残ったカードを取り出します。書き込みはしません。
echo  ※ 宝飾ナビ等が起動中なら終了してから実行してください。
echo.
pause

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY ( where python3 >nul 2>nul && set "PY=python3" )
if not defined PY (
  echo [エラー] Python が見つかりませんでした。
  pause
  exit /b 1
)

%PY% hardware\card_eject.py
endlocal
exit /b 0
