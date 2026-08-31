@echo off
setlocal
cd /d "%~dp0"
title トキワ 停止

echo ============================================
echo   トキワ サーバーを停止します
echo ============================================
echo.
echo  ・本番運用で起動した場合、画面が出ないので閉じて止められません。
echo    このバッチで止めてください。
echo  ・お店のデータには触りません。
echo.

rem ---- 黒い画面つきで起動していた場合(旧バッチ)はウィンドウごと閉じる ----
taskkill /F /T /FI "WINDOWTITLE eq トキワ サーバー*" >nul 2>nul
taskkill /F /T /FI "WINDOWTITLE eq トキワ 起動ランチャー*" >nul 2>nul

rem ---- 画面なしで動いている本体を止める(pythonw は画面もタイトルも持たないため、
rem      実行中のコマンドの中身で探す。トキワのサーバーだけを狙って止める)----
where powershell >nul 2>nul
if errorlevel 1 goto NOPS
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*server*app.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>nul
goto CHECK

:NOPS
echo  [注意] PowerShell が見つかりません。タスクマネージャーで python を終了してください。
goto END

:CHECK
timeout /t 2 /nobreak >nul
powershell -NoProfile -Command "$c=New-Object Net.Sockets.TcpClient; try{$c.Connect('127.0.0.1',8760);$c.Close();exit 0}catch{exit 1}" >nul 2>nul
if errorlevel 1 goto STOPPED
echo  [注意] まだ 8760番 が使われています。
echo         少し待ってからもう一度実行するか、PCを再起動してください。
goto END

:STOPPED
echo  停止しました。

:END
echo.
pause
endlocal
