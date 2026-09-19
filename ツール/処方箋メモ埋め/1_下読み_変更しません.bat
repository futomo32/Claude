@echo off
setlocal
rem ★このバッチは ツール\分類\ の下(2階層)にあるので、トキワ本体のフォルダ(2つ上)へ移動してから動く。
cd /d "%~dp0..\.."
title トキワ 処方箋メモ 下読み

echo ============================================
echo   処方箋のメモを埋めます 下読み(変更しません)
echo ============================================
echo.
echo  宝飾ナビの「アイ備考2」を、処方箋のメモ欄に入れます。
echo  (紹介者・ご続柄・検査した人などの覚え書き)
echo.
echo  ・顧客ID/処方箋No/処方日/レンズ/フレーム の組み合わせで
echo    どの処方箋のメモかを決めます
echo  ・同じ組み合わせが2件以上あるものは、取り違えないよう入れません
echo  ・すでにメモが入っている処方箋は触りません
echo  ・中身が「0」だけのものは入れません
echo  ・★メモにはお名前が入るため、中身は画面に出しません
echo.
echo  これは下読みです。何件入るかを出すだけで、
echo  データは1文字も変更しません。
echo.

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto NOPYTHON
%PY% scripts\fill_rx_notes.py
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
