@echo off
setlocal
rem ★このバッチは ツール\分類\ の下(2階層)にあるので、トキワ本体のフォルダ(2つ上)へ移動してから動く。
cd /d "%~dp0..\.."
title トキワ ポイント履歴の日付を直す

echo ============================================
echo   ポイント履歴の日付を直します(書き込み)
echo ============================================
echo.
echo  ★先に「1_下読み_変更しません.bat」で件数を確かめてください。
echo  ★トキワを止めてから実行してください。
echo.
echo  書き込む直前に、DBのバックアップを自動で取ります。
echo  少しでも食い違うお客様は触りません(飛ばします)。
echo.
set "OK="
set /p OK="実行しますか？ (yes と入れると進みます): "
if /i not "%OK%"=="yes" goto CANCEL
echo.

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto NOPYTHON

%PY% scripts\fix_point_dates.py --apply
if errorlevel 1 goto FAILED

echo.
pause
exit /b 0

:NOPYTHON
echo.
echo  [エラー] Python が見つかりません。
echo  Microsoft Store から「Python 3」を入れてから、もう一度実行してください。
echo.
pause
exit /b 1

:CANCEL
echo.
echo  中止しました。データは変更していません。
echo.
pause
exit /b 0

:FAILED
echo.
echo  [エラー] 書き込みに失敗しました。上の赤い文字をそのまま伝えてください。
echo  バックアップは db\backups\ に残っています。
echo.
pause
exit /b 1
