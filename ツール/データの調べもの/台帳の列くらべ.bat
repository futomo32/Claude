@echo off
setlocal
rem ★このバッチは ツール\分類\ の下(2階層)にあるので、トキワ本体のフォルダ(2つ上)へ移動してから動く。
rem   ".." が1つだと ツール\ 止まりで server\ や db\ を見失う(2026-09-01 修正)
cd /d "%~dp0..\.."
title トキワ 台帳の列くらべ

echo ============================================
echo   11台帳(xlsx)とCSVを突き合わせます
echo ============================================
echo.
echo  台帳にしか無い情報が無いかを調べます。
echo  「CSVの方が情報が多いはず」を実際に確かめるための道具です。
echo.
echo  ・列名ではなく、中に入っている値そのもので突き合わせます
echo  ・表示するのは列名だけです。お客様の情報は表示しません
echo  ・114テーブルあると数分かかります
echo.
echo  【結果の読み方】
echo   ○ 対応あり     … CSV側にも同じ値がある。心配なし
echo   ─ 判定できない … その列が空で、照合する値が無い
echo   ★ 見つからない … 漏れの候補。ただし下の2つが混ざります
echo        ・計算で作った列（経過月・粗利率など）
echo        ・2つの列を繋げた列（商品キーなど）
echo.
echo  ★の一覧はそのまま送ってください。仕分けします。
echo.

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY ( where python3 >nul 2>nul && set "PY=python3" )
if not defined PY goto NOPYTHON

%PY% -c "import openpyxl" >nul 2>nul
if errorlevel 1 goto NOOPENPYXL

%PY% scripts\diag_xlsx_vs_csv.py
if errorlevel 1 goto FAILED
goto END

:NOPYTHON
echo.
echo  [エラー] Python が見つかりません。
echo  https://www.python.org/downloads/windows/ からインストールし、
echo  「Add python.exe to PATH」に必ずチェックを入れてください。
goto END

:NOOPENPYXL
echo.
echo  [エラー] xlsx を読む部品 openpyxl が入っていません。
echo  下のコマンドをコマンドプロンプトで実行してから、もう一度お試しください。
echo.
echo      python -m pip install openpyxl
echo.
goto END

:FAILED
echo.
echo  [エラー] 実行に失敗しました。上の表示を確認してください。
echo  11台帳が data\real\xlsx\ に、CSVが data\real\csv\ にあるか確かめてください。

:END
echo.
pause
