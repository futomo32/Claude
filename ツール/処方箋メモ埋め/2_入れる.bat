@echo off
setlocal
rem ★このバッチは ツール\分類\ の下(2階層)にあるので、トキワ本体のフォルダ(2つ上)へ移動してから動く。
cd /d "%~dp0..\.."
title トキワ 処方箋メモ 書き込み

echo ============================================
echo   処方箋のメモを埋めます(書き込みます)
echo ============================================
echo.
echo  ★先に「1_下読み_変更しません.bat」で件数を確かめてください。
echo.
echo  ・書き込む直前に db\backups へバックアップを取ります
echo  ・すでにメモが入っている処方箋は触りません
echo  ・トキワは止めてから実行してください
echo.

set /p YN="進めてよければ yes と入れてください: "
if /i not "%YN%"=="yes" goto CANCEL

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto NOPYTHON
%PY% scripts\fill_rx_notes.py --apply
if errorlevel 1 goto FAILED
echo.
echo  終わりました。トキワを起動し、顧客詳細の「メガネ(処方箋)」で
echo  処方箋を開いてメモが出るか確かめてください。

echo.
pause
exit /b 0

:CANCEL
echo.
echo  やめました。データは変更していません。
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

:FAILED
echo.
echo  [エラー] 失敗しました。上の赤い文字をそのまま伝えてください。
echo.
pause
exit /b 1
