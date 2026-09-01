@echo off
setlocal
rem ★このバッチは ツール\分類\ の下(2階層)にあるので、トキワ本体のフォルダ(2つ上)へ移動してから動く。
rem   ".." が1つだと ツール\ 止まりで server\ や db\ を見失う(2026-09-01 修正)
cd /d "%~dp0..\.."
title トキワ 売掛 3.取り込む

echo ============================================
echo   3. 売掛を取り込みます
echo ============================================
echo.
echo  ★先に「2.下読み」で件数と合計を確かめてください。
echo.
echo  ・取り込む前に db\tokiwa.db のバックアップを自動で取ります
echo  ・顧客が決まらない行は取り込みません
echo  ・最後に yes と入力するまで実行されません
echo.
echo  ★トキワを止めてから実行してください。
echo.
pause

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY ( where python3 >nul 2>nul && set "PY=python3" )
if not defined PY goto NOPYTHON

%PY% scripts\import_receivables.py --commit
goto END

:NOPYTHON
echo.
echo  [エラー] Python が見つかりません。
echo  https://www.python.org/downloads/windows/ からインストールし、
echo  「Add python.exe to PATH」に必ずチェックを入れてください。

:END
echo.
pause
