@echo off
setlocal
rem ★このバッチは ツール\分類\ の下(2階層)にあるので、トキワ本体のフォルダ(2つ上)へ移動してから動く。
cd /d "%~dp0..\.."
title トキワ 納品書Noさがし

echo ============================================
echo   納品書No(仕入伝票番号)の項目をさがします
echo ============================================
echo.
echo  宝飾ナビの「仕入商品登録・修正・削除」の画面を開いて、
echo  そこに出ている値をそのまま入れてください。
echo.
echo  ・読むだけです。データは1文字も変更しません
echo  ・お客様の情報は表示しません
echo.
echo  【入れるもの】
echo   商品番号 … 画面の右上「商品番号」の欄(例 21454)
echo   納品書No … 画面の左下あたり「納品書No」の欄(例 121463)
echo.
echo  どちらか片方でも動きます。
echo   両方あり     … その商品の行の中で、納品書Noが入っている列を確定します(一番確実)
echo   納品書Noだけ … その値を探します
echo   両方なし     … 納品書Noらしい列の候補を並べます
echo.

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto NOPYTHON

echo --------------------------------------------
set "PNO="
set /p PNO="商品番号（例 21454／不要なら空Enter）: "
set "SLIP="
set /p SLIP="納品書No（例 121463／不要なら空Enter）: "
echo.

if not defined PNO if not defined SLIP goto CANDIDATES
if not defined PNO goto VALUEONLY

if defined SLIP (
  %PY% scripts\find_slip_no.py --product "%PNO%" --find "納品書No=%SLIP%"
) else (
  %PY% scripts\find_slip_no.py --product "%PNO%"
)
if errorlevel 1 goto FAILED
goto RETRY

:VALUEONLY
%PY% scripts\find_slip_no.py --value "%SLIP%"
if errorlevel 1 goto FAILED
goto RETRY

:CANDIDATES
%PY% scripts\find_slip_no.py
if errorlevel 1 goto FAILED
goto END

:RETRY
echo.
echo  見つからなかった場合は、商品・仕入まわり以外の表も探せます。
echo  （114表ぜんぶを見るので数分かかります）
echo.
set "AGAIN="
set /p AGAIN="全部の表でもう一度探しますか？ (y/N): "
if /i not "%AGAIN%"=="y" goto EXTRA
echo.
if defined PNO if defined SLIP (
  %PY% scripts\find_slip_no.py --all --product "%PNO%" --find "納品書No=%SLIP%"
) else (
  if defined SLIP ( %PY% scripts\find_slip_no.py --all --value "%SLIP%" ) else ( %PY% scripts\find_slip_no.py --all --product "%PNO%" )
)

:EXTRA
if not defined PNO goto END
echo.
echo  ほかの項目も同じやり方で調べられます(仕入品番・伝票日付・支払方法など)。
echo  画面に出ている値を入れると、その列名も分かります。
echo.
set "L1="
set /p L1="ほかに調べたい項目名（例 仕入品番／終わるなら空Enter）: "
if not defined L1 goto END
set "V1="
set /p V1="その値（例 3S848）: "
if not defined V1 goto END
echo.
%PY% scripts\find_slip_no.py --product "%PNO%" --find "%L1%=%V1%"
goto EXTRA

:NOPYTHON
echo.
echo  [エラー] Python が見つかりません。
echo  https://www.python.org/downloads/windows/ からインストールし、
echo  「Add python.exe to PATH」に必ずチェックを入れてください。
goto END

:FAILED
echo.
echo  [エラー] 実行に失敗しました。上の表示を確認してください。
echo  data\real\csv\ に宝飾ナビのCSVが置かれているか確かめてください。

:END
echo.
pause
