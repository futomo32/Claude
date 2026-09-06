@echo off
setlocal
rem ★このバッチは ツール\分類\ の下(2階層)にあるので、トキワ本体のフォルダ(2つ上)へ移動してから動く。
cd /d "%~dp0..\.."
title トキワ ポイント履歴の日付 下読み

echo ============================================
echo   ポイント履歴の日付 下読み(変更しません)
echo ============================================
echo.
echo  ポイント履歴の日付を「お買上げ日」から
echo  宝飾ナビと同じ「処理日時」に直します。
echo.
echo  これは下読みです。何件直るかを出すだけで、
echo  データは1文字も変更しません。
echo.

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto NOPYTHON

%PY% scripts\fix_point_dates.py
if errorlevel 1 goto FAILED

echo.
echo  件数を確かめたら「2_日付を直す.bat」に進んでください。

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
echo  [エラー] 下読みに失敗しました。上の赤い文字をそのまま伝えてください。
echo.
pause
exit /b 1
