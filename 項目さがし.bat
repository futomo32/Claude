@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title トキワ 項目さがし

echo ============================================
echo   実データの「この値はどの列?」を探します
echo ============================================
echo.
echo  値札タグに刷られている番号などが、宝飾ナビの
echo  どの列に入っているかを調べるツールです。
echo.
echo  ・data\real\ の CSV と xlsx を全部見ます
echo  ・一致した行の中身だけを表示します
echo  ・氏名/住所/電話などの列は伏せ字にします
echo.

rem ---- Python を探す（py 優先、無ければ python / python3）----
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY ( where python3 >nul 2>nul && set "PY=python3" )
if not defined PY goto NOPYTHON

echo --------------------------------------------
set "KEY="
set /p KEY="行を探すキー（例: 商品番号 20368）: "
if not defined KEY goto NOKEY

set "VAL="
set /p VAL="その行のどの列か調べたい値（例: UA-3602／不要なら空Enter）: "
echo.

%PY% scripts\find_column.py %KEY% %VAL%
if errorlevel 1 goto FAILED

echo.
echo  見つからないときは、値の一部だけで試すか、
echo  下の「部分一致でもう一度」を実行してください。
echo.
set "AGAIN="
set /p AGAIN="部分一致でもう一度探しますか？ (y/N): "
if /i "%AGAIN%"=="y" (
  echo.
  %PY% scripts\find_column.py %KEY% %VAL% --contains
)
goto END

:NOKEY
echo.
echo  [中止] キーが入力されませんでした。
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
echo  data\real\ に CSV / xlsx が置かれているか確かめてください。

:END
echo.
pause
