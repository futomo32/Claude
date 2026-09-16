@echo off
setlocal
rem ★このバッチは ツール\分類\ の下(2階層)にあるので、トキワ本体のフォルダ(2つ上)へ移動してから動く。
cd /d "%~dp0..\.."
title トキワ 伝票0番の修復 下読み

echo ============================================
echo   2011年より前の購入履歴を入れ直します 下読み
echo ============================================
echo.
echo  宝飾ナビは2011年から伝票番号を振り始めており、
echo  それ以前の売上は伝票番号が「0」です。
echo  取込がこの0を番号として扱ったため、全顧客の
echo  古い売上が1枚の伝票にまとまり、他のお客様から
echo  2011年より前の購入履歴が消えていました。
echo.
echo  これは下読みです。何件消して何件入れ直すかを
echo  出すだけで、データは1文字も変更しません。
echo.

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto NOPYTHON

%PY% scripts\fix_slip_zero.py
if errorlevel 1 goto FAILED

echo.
echo  件数を確かめたら「2_入れ直す.bat」に進んでください。

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
