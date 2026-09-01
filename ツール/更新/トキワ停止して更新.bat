@echo off
setlocal enabledelayedexpansion
rem ★このバッチは ツール\分類\ の下(2階層)にあるので、トキワ本体のフォルダ(2つ上)へ移動してから動く。
rem   ".." が1つだと ツール\ 止まりで server\ や db\ を見失う(2026-09-01 修正)
cd /d "%~dp0..\.."
title Tokiwa Update

echo ============================================
echo   トキワ 停止して更新（pull）します
echo ============================================
echo.
echo  ・起動中のトキワ サーバーを止めて、その黒い画面も閉じます
echo    （Ctrl+C も キー押して閉じる も不要になります）
echo  ・そのあと最新版を取り込みます（git pull）
echo  ・お店のデータ（db フォルダ）には触りません
echo.

rem ---- 1) サーバーの黒い画面を閉じる（起動ランチャー/店内共有/機器あり）----
echo サーバーを停止しています...
taskkill /F /T /FI "WINDOWTITLE eq トキワ 起動ランチャー*" >nul 2>nul
taskkill /F /T /FI "WINDOWTITLE eq トキワ 店内共有で起動" >nul 2>nul

rem ---- 2) 念のため、残っている app.py の Python も止める ----
where powershell >nul 2>nul && powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*server*app.py*' } | ForEach-Object { taskkill /F /T /PID $_.ProcessId }" >nul 2>nul

rem 止めた直後の後始末が終わるのを少しだけ待つ
timeout /t 1 /nobreak >nul
echo 停止しました。
echo.

rem ---- 3) 最新版を取り込む（失敗したら 2,4,8,16秒 待って再挑戦）----
where git >nul 2>nul
if errorlevel 1 (
  echo [エラー] git が見つかりません。GitHub Desktop で pull してください。
  goto END
)
for /f "delims=" %%b in ('git rev-parse --abbrev-ref HEAD') do set "BR=%%b"
if not defined BR (
  echo [エラー] このフォルダは git の管理下ではないようです。
  goto END
)
echo 最新版を取り込みます（ブランチ: !BR!）...
set RETRY=0
:PULL
git pull origin !BR!
if not errorlevel 1 goto PULLED
set /a RETRY+=1
if !RETRY! GEQ 5 goto PULLFAIL
set /a "WAIT=1<<RETRY"
echo 取り込みに失敗しました。!WAIT!秒待ってもう一度試します（!RETRY!/4回目）...
timeout /t !WAIT! /nobreak >nul
goto PULL

:PULLED
echo.
echo ============================================
echo   更新が終わりました
echo ============================================
echo.
echo  サーバーは止まったままです。使うときは いつものバッチ
echo  （トキワ起動 / 店内共有で起動 / 機器ありで起動）を
echo  ダブルクリックしてください。
goto END

:PULLFAIL
echo.
echo [エラー] 4回試しましたが取り込めませんでした。
echo  ネットにつながっているか確認してください。
echo  上に出ている英語のメッセージの写真を送ってもらえれば調べます。

:END
echo.
pause
