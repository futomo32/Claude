@echo off
setlocal
rem ★このバッチは ツール\分類\ の下(2階層)にあるので、トキワ本体のフォルダ(2つ上)へ移動してから動く。
rem   ".." が1つだと ツール\ 止まりで server\ や db\ を見失う(2026-09-01 修正)
cd /d "%~dp0..\.."
title トキワ 売掛 1.入力用ファイルを作る

echo ============================================
echo   1. 売掛の入力用ファイルを作ります
echo ============================================
echo.
echo  data\real\売掛入力.csv を作ります。
echo  Excelでそのまま開けます。紙の台帳を見ながら打ち込んでください。
echo.
echo  すでにファイルがある場合は、打ち込んだ内容を守るため作りません。
echo.

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY ( where python3 >nul 2>nul && set "PY=python3" )
if not defined PY goto NOPYTHON

%PY% scripts\import_receivables.py --template
goto END

:NOPYTHON
echo.
echo  [エラー] Python が見つかりません。
echo  https://www.python.org/downloads/windows/ からインストールし、
echo  「Add python.exe to PATH」に必ずチェックを入れてください。

:END
echo.
pause
