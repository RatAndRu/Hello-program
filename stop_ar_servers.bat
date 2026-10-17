@echo off
chcp 65001 >nul
echo Останавливаю только серверы Shadow Morse AR / python http.server на порту 8080...
powershell -NoProfile -ExecutionPolicy Bypass -Command "^$port=8080; ^$conns=Get-NetTCPConnection -LocalPort ^$port -State Listen -ErrorAction SilentlyContinue; foreach(^$c in ^$conns){ ^$pidNum=^$c.OwningProcess; ^$p=Get-CimInstance Win32_Process -Filter \"ProcessId=^$pidNum\" -ErrorAction SilentlyContinue; if(^$p){ ^$cmd=[string]^$p.CommandLine; ^$name=[string]^$p.Name; if(((^$name -match 'python|py\.exe') -and (^$cmd -match 'http\.server') -and (^$cmd -match '8080')) -or (^$cmd -match 'tray_server\.py')){ try{ Invoke-CimMethod -InputObject ^$p -MethodName Terminate ^| Out-Null; Write-Host \"Stopped PID ^$pidNum\" }catch{} } } }"
echo Готово.
pause
