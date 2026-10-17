' ============================================================================
'  stop.vbs — корректная остановка ТОЛЬКО своего приложения
' ----------------------------------------------------------------------------
'  Идея из SHADOW GAME (stop_ar_servers.vbs): убивать процесс на порту можно
'  лишь тогда, когда его командная строка действительно относится к нашему
'  проекту. Иначе однажды будет убит чужой сервер, который просто занял порт.
'
'  Порядок действий:
'    1) читаем data\port.txt (первая строка — номер порта, так пишет appcore);
'    2) на этом порту ищем процессы-слушатели и проверяем их командную строку
'       (должна содержать путь нашей папки);
'    3) если порт неизвестен — ищем python-процессы, запущенные с нашим app.py;
'    4) результат пишем в logs\launch.log.
'
'  Внутри — PowerShell (так надёжнее и короче, чем netstat+taskkill в VBS).
'  Кавычки: в VBS удобнее собирать PS-строку через Chr(34), поэтому внутри
'  PowerShell используем только ОДИНАРНЫЕ кавычки.
' ============================================================================
Option Explicit

Dim fso, shell, appDir, portFile, logPath, ps, result

Set fso   = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

appDir   = fso.GetParentFolderName(WScript.ScriptFullName)
portFile = fso.BuildPath(fso.BuildPath(appDir, "data"), "port.txt")
logPath  = fso.BuildPath(fso.BuildPath(appDir, "logs"), "launch.log")

ps = _
"$appDir = '" & Replace(appDir, "'", "''") & "'; " & _
"$portFile = '" & Replace(portFile, "'", "''") & "'; " & _
"$killed = @(); " & _
"if (Test-Path $portFile) { " & _
"  $raw = (Get-Content $portFile -TotalCount 1).Trim(); " & _
"  if ($raw -match '^\d+$') { " & _
"    $port = [int]$raw; " & _
"    Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | ForEach-Object { " & _
"      $p = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $_.OwningProcess) -ErrorAction SilentlyContinue; " & _
"      if ($p -and $p.CommandLine -and ($p.CommandLine -like ('*' + $appDir + '*'))) { " & _
"        try { Invoke-CimMethod -InputObject $p -MethodName Terminate | Out-Null; $killed += [int]$p.ProcessId } catch {} } } } }; " & _
"if ($killed.Count -eq 0) { " & _
"  Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { " & _
"    $_.Name -like 'python*' -and $_.CommandLine -and " & _
"    ($_.CommandLine -like ('*' + $appDir + '*app.py*')) } | ForEach-Object { " & _
"    try { Invoke-CimMethod -InputObject $_ -MethodName Terminate | Out-Null; $killed += [int]$_.ProcessId } catch {} } }; " & _
"if ($killed.Count -gt 0) { Write-Output ('Остановлено: ' + (($killed | Sort-Object -Unique) -join ', ')) } " & _
"else { Write-Output 'Приложение не запущено (или остановить нечего)' }"

On Error Resume Next
result = shell.Run("powershell -NoProfile -ExecutionPolicy Bypass -Command " & _
                   Chr(34) & ps & Chr(34), 0, True)
If Err.Number <> 0 Then
    MsgBox "Не удалось остановить приложение: " & Err.Description, vbExclamation, "stop.vbs"
End If
On Error GoTo 0

' --- строка в лог (по ней видно, что остановка вообще выполнялась) ---------
On Error Resume Next
Dim logsDir, ts
logsDir = fso.GetParentFolderName(logPath)
If Not fso.FolderExists(logsDir) Then fso.CreateFolder(logsDir)
Set ts = fso.OpenTextFile(logPath, 8, True)
ts.WriteLine "[" & Now & "] stop.vbs: " & (result & "")
ts.Close
On Error GoTo 0

WScript.Quit 0
