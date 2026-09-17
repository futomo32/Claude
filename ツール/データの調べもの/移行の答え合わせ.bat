@echo off
setlocal
rem ★このバッチは ツール\分類\ の下(2階層)にあるので、トキワ本体のフォルダ(2つ上)へ移動してから動く。
cd /d "%~dp0..\.."
title トキワ 移行の答え合わせ

echo ============================================
echo   移行の答え合わせ(入っていないものを探す)
echo ============================================
echo.
echo  元のCSVにあるのにトキワに入っていないものを、
echo  顧客・商品・売上・処方箋・ポイント・家族・メモの
echo  全部について数えます。
echo.
echo  ・読むだけです。データは1文字も変更しません
echo  ・お客様の氏名は表示しません(件数とキーだけ)
echo  ・意図的に入れていないもの(削除リスト・売掛)は別枠です
echo.
echo  ※20万行の表を読むので、数分かかることがあります。
echo.
pause

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto NOPYTHON

set "L="
set /p L="見つかったキーの例も並べますか？ (y/N): "
echo.
if /i "%L%"=="y" (
  %PY% scripts\diag_import_gaps.py --list
) else (
  %PY% scripts\diag_import_gaps.py
)
if errorlevel 1 goto FAILED

echo.
echo  ★が付いた行があれば、そのまま送ってください。
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
