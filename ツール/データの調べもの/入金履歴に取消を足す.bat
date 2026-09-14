@echo off
setlocal
rem ★このバッチは ツール\分類\ の下(2階層)にあるので、トキワ本体のフォルダ(2つ上)へ移動してから動く。
cd /d "%~dp0..\.."
title トキワ 入金履歴に取消の行を足す

echo ============================================
echo   入金履歴に「取消」の行を足します
echo ============================================
echo.
echo  売上を打ち直した時、取り消した方の「掛売」が
echo  入金履歴に残ってしまった分の後始末です。
echo.
echo  ・売掛残高には触りません(請求額は変わりません)
echo  ・同じ取消の行が既にあれば入れません
echo  ・まず下読み、よければ書き込み(バックアップ自動)
echo.
echo  【入れるもの】画面の「入金管理」を見ながら入力してください
echo   顧客ID … 名前の下の「顧客ID 01-8689」の部分
echo   商品名 … 入金履歴に残っている行の商品名
echo   金額   … その行の購入金額(プラスで入れる)
echo.

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto NOPYTHON

set "CID="
set /p CID="顧客ID (例 01-8689): "
if not defined CID goto CANCEL
set "NM="
set /p NM="商品名 (例 K18/SVブレス): "
if not defined NM goto CANCEL
set "AMT="
set /p AMT="金額 (例 50000): "
if not defined AMT goto CANCEL
echo.

%PY% scripts\add_void_entry.py --customer "%CID%" --name "%NM%" --amount "%AMT%"
if errorlevel 1 goto FAILED

echo.
set "OK="
set /p OK="この内容で入れますか？ (yes と入れると進みます): "
if /i not "%OK%"=="yes" goto CANCEL
echo.
%PY% scripts\add_void_entry.py --customer "%CID%" --name "%NM%" --amount "%AMT%" --apply
if errorlevel 1 goto FAILED

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
