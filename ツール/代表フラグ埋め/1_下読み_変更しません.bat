@echo off
setlocal
rem ★このバッチは ツール\分類\ の下(2階層)にあるので、トキワ本体のフォルダ(2つ上)へ移動してから動く。
cd /d "%~dp0..\.."
title トキワ 代表フラグ 下読み

echo ============================================
echo   顧客の代表フラグを埋めます 下読み(変更しません)
echo ============================================
echo.
echo  宝飾ナビの「代表フラグ」を顧客に入れます。
echo  家族に1通だけDMを出す時の絞り込みに使います。
echo  
echo  ・印が付いている人だけに入れます(付いていない人は触りません)
echo  ・トキワで印を付け直した人は上書きしません
echo.
echo  これは下読みです。何件入るかを出すだけで、
echo  データは1文字も変更しません。
echo.

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto NOPYTHON
%PY% scripts\fill_family_rep.py
if errorlevel 1 goto FAILED
echo.
echo  件数を確かめたら「2_入れる.bat」に進んでください。

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
