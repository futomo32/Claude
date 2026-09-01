@echo off
setlocal
rem ★このバッチは ツール\分類\ の下(2階層)にあるので、トキワ本体のフォルダ(2つ上)へ移動してから動く。
rem   ".." が1つだと ツール\ 止まりで server\ や db\ を見失う(2026-09-01 修正)
cd /d "%~dp0..\.."
title トキワ 売掛 2.下読み

echo ============================================
echo   2. 下読みします(まだ取り込みません)
echo ============================================
echo.
echo  data\real\売掛入力.csv を読んで、次のことを調べます。
echo.
echo  ・何件・合計いくらになるか  ← 紙の合計と突き合わせてください
echo  ・顧客が決まらない行はどれか
echo  ・同じ内容を二重に書いていないか
echo.
echo  ★この段階ではデータは一切変わりません。
echo.

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY ( where python3 >nul 2>nul && set "PY=python3" )
if not defined PY goto NOPYTHON

%PY% scripts\import_receivables.py
goto END

:NOPYTHON
echo.
echo  [エラー] Python が見つかりません。
echo  https://www.python.org/downloads/windows/ からインストールし、
echo  「Add python.exe to PATH」に必ずチェックを入れてください。

:END
echo.
pause
