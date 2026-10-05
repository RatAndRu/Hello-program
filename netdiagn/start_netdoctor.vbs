' ===========================================================================
'  start_netdoctor.vbs  —  основной запуск NET DOCTOR (Windows, двойной клик)
' ---------------------------------------------------------------------------
'  Что делает:
'    1. находит Python (py -3 / python / python3);
'    2. открывает окно консоли и запускает net_doctor.py с теми ключами,
'       которые переданы этому файлу;
'    3. окно консоли остаётся открытым, чтобы можно было прочитать вердикт
'       и отчёт netdoctor_report.txt;
'    4. если Python не найден — показывает понятное окно с подсказкой.
'
'  Почему .vbs, а не .bat:
'    .bat-файл с кириллицей ломается в cmd.exe, если в нём есть смена кодовой
'    страницы (chcp): консоль начинает выполнять ОБРЫВКИ строк и выдаёт ошибки
'    вида «'on' is not recognized as an internal or external command»,
'    «'тайте' is not recognized...». VBScript от кодировок и переводов строк не
'    зависит, поэтому русские окна и пути с кириллицей работают надёжно.
'
'  Ключи передаются так же, как у net_doctor.py, например:
'     start_netdoctor.vbs --check-port 5000 --phone 192.168.0.61
'     start_netdoctor.vbs --fix
'     start_netdoctor.vbs --no-server
'  (проще всего: правый клик по файлу -> «Создать ярлык», затем в свойствах
'   ярлыка дописать ключи в поле «Объект»)
' ===========================================================================

Option Explicit

Dim fso, shell, root, scriptPath, py, i, args, cmd, q

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
q = Chr(34)   ' кавычка: так проще собирать командную строку и не запутаться

' ---- 1. Куда установлена программа ----------------------------------------
root = fso.GetParentFolderName(WScript.ScriptFullName)
scriptPath = fso.BuildPath(root, "net_doctor.py")

If Not fso.FileExists(scriptPath) Then
  MsgBox "Не найден файл:" & vbCrLf & scriptPath & vbCrLf & vbCrLf & _
         "Похоже, файл net_doctor.py отсутствует." & vbCrLf & _
         "Скачайте папку netdiagn целиком.", _
         vbCritical, "NET DOCTOR"
  WScript.Quit 1
End If

' ---- 2. Ищем Python --------------------------------------------------------
py = ""

If CommandWorks("py -3 --version") Then
  py = "py -3"
ElseIf CommandWorks("python -c ""import sys; sys.exit(0 if sys.version_info >= (3,) else 1)""") Then
  ' именно проверка версии: команда "python" на старых машинах может быть Python 2
  py = "python"
ElseIf CommandWorks("python3 --version") Then
  py = "python3"
End If

If py = "" Then
  MsgBox "Python не найден на этом компьютере." & vbCrLf & vbCrLf & _
         "1) Скачайте Python 3 с сайта https://www.python.org/downloads/" & vbCrLf & _
         "2) При установке поставьте галочку «Add python.exe to PATH»" & vbCrLf & _
         "3) Запустите start_netdoctor.vbs снова." & vbCrLf & vbCrLf & _
         "NET DOCTOR не требует дополнительных библиотек — только сам Python.", _
         vbExclamation, "NET DOCTOR"
  WScript.Quit 1
End If

' ---- 3. Ключи, переданные этому файлу --------------------------------------
args = ""
For i = 0 To WScript.Arguments.Count - 1
  args = args & " " & QuoteArg(WScript.Arguments(i))
Next

' ---- 4. Рабочая папка: сюда же ляжет netdoctor_report.txt -------------------
On Error Resume Next
shell.CurrentDirectory = root
On Error GoTo 0

' ---- 5. Собираем команду и запускаем в отдельном окне консоли ---------------
'  Получается примерно так:  cmd /k "py -3 "C:\...\net_doctor.py" --fix"
'  cmd снимает внешние кавычки и выполняет:  py -3 "C:\...\net_doctor.py" --fix
'  Ключ /k оставляет окно открытым после завершения NET DOCTOR.
cmd = "cmd /k " & q & py & " " & q & scriptPath & q & args & q

On Error Resume Next
shell.Run cmd, 1, False
If Err.Number <> 0 Then
  MsgBox "Не удалось запустить NET DOCTOR:" & vbCrLf & Err.Description, _
         vbCritical, "NET DOCTOR"
  WScript.Quit 1
End If
On Error GoTo 0

WScript.Quit 0

' ===========================================================================
'  Проверяет, доступна ли команда (например «python --version»).
'  Возвращает True, если команда запускается без ошибки.
' ===========================================================================
Function CommandWorks(ByVal testCmd)
  Dim code
  On Error Resume Next
  code = shell.Run("cmd /c " & testCmd & " >nul 2>&1", 0, True)
  If Err.Number <> 0 Then
    CommandWorks = False
    Err.Clear
  Else
    CommandWorks = (code = 0)
  End If
  On Error GoTo 0
End Function

' ===========================================================================
'  Оборачивает аргумент в кавычки, если он содержит пробелы, и удваивает уже
'  имеющиеся кавычки (правила командной строки Windows).
' ===========================================================================
Function QuoteArg(ByVal value)
  value = Replace(value, q, q & q)
  If InStr(value, " ") > 0 Or InStr(value, vbTab) > 0 Or value = "" Then
    QuoteArg = q & value & q
  Else
    QuoteArg = value
  End If
End Function
