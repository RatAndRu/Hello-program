Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
' pythonw запускает без консольного окна. Если pystray не установлен, лучше запусти сначала install_tray_deps.bat
cmd = "pythonw """ & folder & "\tray_server.py"""
WshShell.Run cmd, 0, False
