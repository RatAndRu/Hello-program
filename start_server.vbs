Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
cmd = "cmd /k cd /d """ & folder & """ && python -m http.server 8080"
WshShell.Run cmd, 1, False
WScript.Sleep 800
WshShell.Run "http://localhost:8080", 1, False
