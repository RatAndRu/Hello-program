' ===========================================================================
'  start.vbs  —  запуск программы из этого репозитория (Windows)
' ---------------------------------------------------------------------------
'  Что делает:
'    1. находит Python (python / py);
'    2. запускает шахматы (папка chess).
'       • без ключей      -> красивое окно (tkinter), а если его нет — консоль;
'       • с ключом        -> консольный режим:   start.vbs --console
'    3. если Python не установлен — покажет понятное окно с подсказкой.
'
'  Использование: просто дважды кликните по этому файлу.
' ===========================================================================

Option Explicit

Dim fso, shell, root, scriptPath, excel  ' excel не используется, объявлен для совместимости

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

' ---- 1. Куда установлена программа -------------------------------------------------
root = fso.GetParentFolderName(WScript.ScriptFullName)
scriptPath = fso.BuildPath(fso.BuildPath(root, "chess"), "chess.py")

If Not fso.FileExists(scriptPath) Then
  MsgBox "Не найден файл:" & vbCrLf & scriptPath & vbCrLf & vbCrLf & _
         "Похоже, папка chess отсутствует. Скачайте репозиторий целиком.", _
         vbCritical, "Шахматы на Python"
  WScript.Quit 1
End If

' ---- 2. Консольный ли режим? -------------------------------------------------------
Dim wantConsole, i, arg
wantConsole = False
For i = 0 To WScript.Arguments.Count - 1
  arg = LCase(WScript.Arguments(i))
  If arg = "--console" Or arg = "-c" Then wantConsole = True
Next

' ---- 3. Ищем Python ----------------------------------------------------------------
Dim python, pythonw
python = ""
pythonw = ""

If CommandWorks("py -3") Then
  python = "py -3"
  pythonw = "py -3"
ElseIf CommandWorks("python") Then
  python = "python"
  pythonw = "python"
ElseIf CommandWorks("python3") Then
  python = "python3"
  pythonw = "python3"
End If

If python = "" Then
  MsgBox "Python не найден на этом компьютере." & vbCrLf & vbCrLf & _
         "1) Скачайте Python 3 с сайта https://www.python.org/downloads/" & vbCrLf & _
         "2) При установке поставьте галочку «Add python.exe to PATH»" & vbCrLf & _
         "3) Запустите start.vbs снова." & vbCrLf & vbCrLf & _
         "Игра не требует никаких дополнительных библиотек — только сам Python.", _
         vbExclamation, "Шахматы на Python"
  WScript.Quit 1
End If

' Для оконного режима используем pythonw — тогда не будет лишнего чёрного окна.
Dim guiCmd
If CommandWorks("pythonw") Then
  pythonw = "pythonw"
ElseIf python = "py -3" Then
  pythonw = "py -3w"        ' py -3w подходит не всем версиям — ниже есть проверка
  If Not CommandWorks("py -3w") Then pythonw = "py -3"
End If

' ---- 4. Запуск ---------------------------------------------------------------------
Dim cmd, rc
If wantConsole Then
  ' Консольный вариант: окно cmd остаётся открытым (/k), чтобы было видно результат.
  cmd = "cmd /k """"" & python & " """"" & scriptPath & """ --console"""""
  shell.Run cmd, 1, False
  WScript.Quit 0
Else
  ' Оконный вариант. Если что-то пойдёт не так — покажем окно с ошибкой.
  cmd = """" & pythonw & """ """ & scriptPath & """"
  On Error Resume Next
  rc = shell.Run(cmd, 1, True)
  If Err.Number <> 0 Then
    MsgBox "Не удалось запустить игру:" & vbCrLf & Err.Description, vbCritical, "Шахматы"
    WScript.Quit 1
  End If
  On Error GoTo 0
  If rc <> 0 Then
    MsgBox "Игра завершилась с кодом " & rc & "." & vbCrLf & vbCrLf & _
           "Попробуйте консольный режим — запустите start.vbs с ключом --console" & vbCrLf & _
           "или дважды кликните по chess\start_chess.bat", vbInformation, "Шахматы на Python"
  End If
End If

WScript.Quit 0

' ===========================================================================
'  Проверяет, доступна ли команда (например «python»).
'  Возвращает True, если команда запускается без ошибки.
' ===========================================================================
Function CommandWorks(ByVal testCmd)
  Dim code
  On Error Resume Next
  code = shell.Run("cmd /c " & testCmd & " --version >nul 2>&1", 0, True)
  If Err.Number <> 0 Then
    CommandWorks = False
    Err.Clear
  Else
    CommandWorks = (code = 0)
  End If
  On Error GoTo 0
End Function
