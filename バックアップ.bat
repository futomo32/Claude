@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title トキワ バックアップ

echo ============================================
echo   トキワ データのバックアップ
echo ============================================
echo.
echo  ・営業中（トキワ起動中）でも安全に実行できます
echo  ・店内（db\backups）に保存し、設定した店外の保存先にも複製します
echo  ・保存先と世代数はトキワの「設定 → バックアップ」で指定します
echo.

rem ---- Python を探す（py 優先、無ければ python / python3）----
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY ( where python3 >nul 2>nul && set "PY=python3" )
if not defined PY goto NOPYTHON

%PY% "scripts\backup_db.py" %1
if errorlevel 1 goto FAILED

echo.
echo バックアップが完了しました。
goto END

:FAILED
echo.
echo [失敗] バックアップを取れませんでした。上のメッセージを確認してください。
echo   ・保存先のドライブ（外付けHDD等）が接続されているか
echo   ・db\tokiwa.db があるか
goto END

:NOPYTHON
echo.
echo [エラー] Python が見つかりません。Python をインストールしてください。
goto END

:END
echo.
echo ※Windowsのタスクスケジューラに登録すると、閉店後の自動実行ができます。
echo   手順は docs\backup.md を参照してください。
echo.
pause
