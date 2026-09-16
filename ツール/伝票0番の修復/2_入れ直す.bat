@echo off
setlocal
rem ★このバッチは ツール\分類\ の下(2階層)にあるので、トキワ本体のフォルダ(2つ上)へ移動してから動く。
cd /d "%~dp0..\.."
title トキワ 伝票0番の修復 実行

echo ============================================
echo   2011年より前の購入履歴を入れ直します(書き込み)
echo ============================================
echo.
echo  ★先に「1_下読み_変更しません.bat」で件数を確かめてください。
echo  ★トキワを止めてから実行してください。
echo.
echo  ・書き込む直前にDBのバックアップを自動で取ります
echo  ・伝票番号がある伝票(2011年以降・トキワの売上)には触りません
echo  ・在庫・ポイント・売掛・処方箋にも触りません
echo.
set "OK="
set /p OK="実行しますか？ (yes と入れると進みます): "
if /i not "%OK%"=="yes" goto CANCEL
echo.

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto NOPYTHON

%PY% scripts\fix_slip_zero.py --apply
if errorlevel 1 goto FAILED

echo.
echo  終わったらトキワを起動し、顧客詳細で古い購入履歴が
echo  出るようになったか確かめてください。

echo.
pause
exit /b 0

:CANCEL
echo.
echo  中止しました。データは変更していません。
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
