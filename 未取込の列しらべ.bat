@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title トキワ 未取込の列しらべ

echo ============================================
echo   宝飾ナビの列で取り込み漏れが無いか調べます
echo ============================================
echo.
echo  値が入っているのにトキワへ持ってきていない列を、
echo  入力率の高い順に並べます。
echo.
echo  ・data\real\csv\ の CSV を読みます
echo  ・列名と件数だけを表示し、氏名や住所は伏せ字にします
echo  ・全列ぶんは data\real\未取込の列.txt に書き出します
echo.

rem ---- Python を探す（py 優先、無ければ python / python3）----
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY ( where python3 >nul 2>nul && set "PY=python3" )
if not defined PY goto NOPYTHON

echo --------------------------------------------
echo  1: 主要テーブルだけ調べる（おすすめ・速い）
echo  2: 全テーブルを調べる（時間がかかります）
echo --------------------------------------------
set "SEL=1"
set /p SEL="どちらにしますか？ (1/2) [1]: "

if "%SEL%"=="2" (
  %PY% scripts\diag_unused_columns.py --all
) else (
  %PY% scripts\diag_unused_columns.py
)
if errorlevel 1 goto FAILED
goto END

:NOPYTHON
echo.
echo  [エラー] Python が見つかりません。
echo  https://www.python.org/downloads/windows/ からインストールし、
echo  「Add python.exe to PATH」に必ずチェックを入れてください。
goto END

:FAILED
echo.
echo  [エラー] 実行に失敗しました。上の表示を確認してください。
echo  data\real\csv\ に CSV が置かれているか確かめてください。

:END
echo.
pause
