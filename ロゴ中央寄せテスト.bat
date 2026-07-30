@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title トキワ ロゴ中央寄せ確定テスト

echo ============================================
echo   ロゴ 中央寄せ確定テスト
echo ============================================
echo.
echo  ・目盛りとロゴ5パターンを1枚に印字します
echo  ・印字後、レシートの写真を撮って共有してください
echo  ・宝飾ナビが起動中だと印字できない場合があります
echo.

rem ---- Python を探す（py 優先、無ければ python / python3）----
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY ( where python3 >nul 2>nul && set "PY=python3" )
if not defined PY goto NOPYTHON

rem ---- Pillow（画像変換）を用意 ----
%PY% -c "import PIL" >nul 2>nul
if errorlevel 1 (
  echo Pillow を導入します（初回のみ・ネット接続が必要）...
  %PY% -m pip install pillow
  if errorlevel 1 goto NOPILLOW
)

%PY% "hardware\logo_center_test.py"
goto END

:NOPYTHON
echo.
echo [エラー] Python が見つかりません。
echo   python.org 版をインストールし「Add python.exe to PATH」にチェックしてください。
goto END

:NOPILLOW
echo.
echo [エラー] Pillow の導入に失敗しました（ネット未接続などの可能性）。
echo   コマンドプロンプトで手動: pip install pillow
goto END

:END
echo.
pause
