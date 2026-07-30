@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title トキワ レシート桁数テスト

echo ============================================
echo   レシート桁数（印字幅）確定テスト
echo ============================================
echo.
echo  ・28～36桁の線を1枚に印字します
echo  ・「END」まで1行で収まった最大の桁数を教えてください
echo  ・宝飾ナビが起動中だと印字できない場合があります
echo.

rem ---- Python を探す（py 優先、無ければ python / python3）----
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY ( where python3 >nul 2>nul && set "PY=python3" )
if not defined PY goto NOPYTHON

%PY% "hardware\width_test.py"
goto END

:NOPYTHON
echo.
echo [エラー] Python が見つかりません。
echo   python.org 版をインストールし「Add python.exe to PATH」にチェックしてください。
goto END

:END
echo.
pause
