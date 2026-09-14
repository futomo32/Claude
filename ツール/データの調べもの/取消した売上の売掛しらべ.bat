@echo off
setlocal
rem ★このバッチは ツール\分類\ の下(2階層)にあるので、トキワ本体のフォルダ(2つ上)へ移動してから動く。
cd /d "%~dp0..\.."
title トキワ 取消した売上の売掛しらべ

echo ============================================
echo   取消した売上に残っている売掛をしらべます
echo ============================================
echo.
echo  レジで取り消した(返品した)売上なのに、売掛が
echo  残っていないかを数えます。残っていると請求して
echo  しまう(二重請求)ので、その件数と金額を出します。
echo.
echo  ・読むだけです。データは1文字も変更しません
echo  ・お客様の氏名は表示しません(顧客IDと金額だけ)
echo.

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto NOPYTHON

set "L="
set /p L="対象の売掛IDも並べますか？ (y/N): "
echo.
if /i "%L%"=="y" (
  %PY% scripts\diag_voided_receivables.py --list
) else (
  %PY% scripts\diag_voided_receivables.py
)
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

:FAILED
echo.
echo  [エラー] 失敗しました。上の赤い文字をそのまま伝えてください。
echo.
pause
exit /b 1
