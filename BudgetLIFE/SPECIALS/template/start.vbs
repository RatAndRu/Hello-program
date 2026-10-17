' ============================================================================
'  start.vbs — УНИВЕРСАЛЬНЫЙ тихий лаунчер (золотой стандарт SPECIALS)
' ----------------------------------------------------------------------------
'  Собрано из лучших версий всех проектов:
'    * LanguageYOI — поиск Python через `py -X.Y` без мигания окна и штамп
'      сборки именованного лаунчера (не запускаем недоделанный exe);
'    * Трекер     — список типовых путей pythonw.exe + аргументы командной строки
'      (нужно для URI-протокола: start.vbs "%1");
'    * DeployAgent — сначала именованный exe приложения (имя в диспетчере задач),
'      иначе pythonw.exe; относительные пути от папки скрипта;
'    * shedevrum_bot / swipe_review — понятное сообщение об ошибке вместо
'      «молча ничего не произошло»;
'    * DnD's — диагностическая строка в logs\launch.log.
'
'  ПРИНЦИПЫ:
'    1. НИКАКИХ жёстких путей (C:\AI_Projects\...) — только папка самого скрипта.
'       Проект можно переносить куда угодно.
'    2. Никогда не запускаем python.exe (он даст чёрное окно консоли) —
'       только pythonw.exe. Окно с консолью — это start_debug.bat.
'    3. Если Python не найден — MsgBox с инструкцией, а не тишина.
'    4. Любое своё действие пишем в logs\launch.log: потом видно, что и когда
'       запускалось (первый вопрос при «не работает»).
'    5. Аргументы (WScript.Arguments) передаются в app.py как есть — так URI
'       вида myapp://... доходят до уже запущенного приложения.
' ============================================================================
Option Explicit

Dim fso, shell, appDir, appPy, cmd, pyw, logLine

Set fso   = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

' --- 1. Папка проекта = папка этого скрипта (работает из любого места) -------
appDir = fso.GetParentFolderName(WScript.ScriptFullName)
appPy  = fso.BuildPath(appDir, "app.py")
shell.CurrentDirectory = appDir

If Not fso.FileExists(appPy) Then
    MsgBox "Не найден файл:" & vbCrLf & appPy & vbCrLf & vbCrLf & _
           "start.vbs должен лежать рядом с app.py.", vbCritical, "Запуск отменён"
    WScript.Quit 1
End If

' --- 2. Ищем, ЧЕМ запускать ---------------------------------------------------
pyw = FindPythonw()

If Len(pyw) = 0 Then
    MsgBox "Python не найден." & vbCrLf & vbCrLf & _
           "Установите Python с python.org и включите галочку" & vbCrLf & _
           """Add python.exe to PATH"", затем повторите запуск." & vbCrLf & vbCrLf & _
           "Если Python установлен в необычное место — запустите проект" & vbCrLf & _
           "файлом start_debug.bat и посмотрите logs\launch.log.", _
           vbCritical, "Python не найден"
    WriteLog appDir, "ОШИБКА: pythonw.exe не найден"
    WScript.Quit 1
End If

' --- 3. Собираем команду и запускаем скрыто ----------------------------------
cmd = """" & pyw & """ """ & appPy & """" & CollectArgs()

WriteLog appDir, "Запуск: " & cmd

On Error Resume Next
shell.Run cmd, 0, False
If Err.Number <> 0 Then
    MsgBox "Не удалось запустить приложение." & vbCrLf & vbCrLf & _
           "Команда: " & cmd & vbCrLf & _
           "Ошибка: " & Err.Description & vbCrLf & vbCrLf & _
           "Подробности: logs\launch.log", vbCritical, "Ошибка запуска"
    WriteLog appDir, "ОШИБКА запуска: " & Err.Description
    WScript.Quit 1
End If
On Error GoTo 0

WScript.Quit 0


' ============================================================================
'  FindPythonw — возвращает путь к pythonw.exe или "" (пустая строка)
' ============================================================================
Function FindPythonw()
    Dim exePath, candidates, pyDir, i, ver, tmpFile, line, f, base

    FindPythonw = ""

    ' 3.1 Именованный exe приложения: «SpecialsDemo.exe» + штамп «.launcher».
    '     Его создаёт само приложение (appcore/windowing.py) при первом запуске.
    '     Ищем именно ШТАМП, а рядом с ним — одноимённый exe: так имя exe и имя
    '     папки могут не совпадать (урок LanguageYOI: без штампа можно было
    '     запустить недописанную копию и получить «молча ничего не произошло»).
    For Each f In fso.GetFolder(appDir).Files
        If LCase(fso.GetExtensionName(f.Name)) = "launcher" Then
            base = fso.GetBaseName(f.Name)
            exePath = fso.BuildPath(appDir, base & ".exe")
            If fso.FileExists(exePath) Then
                FindPythonw = exePath
                Exit Function
            End If
        End If
    Next

    ' 3.2 Официальный лаунчер `py`: находим интерпретатор без окна консоли.
    '     Пишем результат во временный файл (вывод скрытого процесса иначе не
    '     прочитать) — приём LanguageYOI, флаг 0 = окно не показывать.
    tmpFile = shell.ExpandEnvironmentStrings("%TEMP%") & "\_appcore_py_check.txt"
    On Error Resume Next
    If fso.FileExists(tmpFile) Then fso.DeleteFile tmpFile
    On Error GoTo 0

    Dim versions
    versions = Array("-3.12-64", "-3.12", "-3.13", "-3.13-64", "-3.11", "-3.14", "-3.14-64")
    For Each ver In versions
        On Error Resume Next
        shell.Run "cmd /c py " & ver & " -c ""import sys;print(sys.executable)"" > """ & _
                  tmpFile & """ 2>nul", 0, True
        On Error GoTo 0
        If fso.FileExists(tmpFile) Then
            line = ReadFirstLine(tmpFile)
            If Len(line) > 0 Then
                pyDir = fso.GetParentFolderName(line)
                If fso.FileExists(fso.BuildPath(pyDir, "pythonw.exe")) Then
                    FindPythonw = fso.BuildPath(pyDir, "pythonw.exe")
                    DeleteQuietly tmpFile
                    Exit Function
                End If
            End If
        End If
    Next
    DeleteQuietly tmpFile

    ' 3.3 Типовые места установки (урок Трекера: пользователь ставит Python
    '     то в AppData, то в C:\PythonXX, то в Program Files).
    Dim local, pf
    local = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%")
    pf    = shell.ExpandEnvironmentStrings("%ProgramFiles%")

    candidates = Array( _
        local & "\Programs\Python\Python313\pythonw.exe", _
        local & "\Programs\Python\Python312\pythonw.exe", _
        local & "\Programs\Python\Python311\pythonw.exe", _
        local & "\Programs\Python\Python314\pythonw.exe", _
        local & "\Python\pythoncore-3.13-64\pythonw.exe", _
        local & "\Python\pythoncore-3.12-64\pythonw.exe", _
        "C:\Python313\pythonw.exe", _
        "C:\Python312\pythonw.exe", _
        "C:\Python311\pythonw.exe", _
        pf & "\Python313\pythonw.exe", _
        pf & "\Python312\pythonw.exe", _
        pf & "\Python311\pythonw.exe" _
    )
    For i = 0 To UBound(candidates)
        If fso.FileExists(candidates(i)) Then
            FindPythonw = candidates(i)
            Exit Function
        End If
    Next

    ' 3.4 Последний шанс: pythonw.exe из PATH (ищем через `where`, не запуская его!)
    tmpFile = shell.ExpandEnvironmentStrings("%TEMP%") & "\_appcore_where.txt"
    On Error Resume Next
    shell.Run "cmd /c where pythonw.exe > """ & tmpFile & """ 2>nul", 0, True
    On Error GoTo 0
    If fso.FileExists(tmpFile) Then
        line = ReadFirstLine(tmpFile)
        If Len(line) > 0 And fso.FileExists(line) Then
            FindPythonw = line
        End If
    End If
    DeleteQuietly tmpFile
End Function


' Все аргументы командной строки → одна строка в кавычках (для URI myapp://…)
Function CollectArgs()
    Dim result, i
    result = ""
    For i = 0 To WScript.Arguments.Count - 1
        result = result & " """ & WScript.Arguments(i) & """"
    Next
    CollectArgs = result
End Function


' Первая непустая строка файла (utf-8/ansi — читаем как ansi, путь без кириллицы)
Function ReadFirstLine(path)
    Dim ts, line
    ReadFirstLine = ""
    On Error Resume Next
    Set ts = fso.OpenTextFile(path, 1, False)
    If Err.Number <> 0 Then Exit Function
    Do While Not ts.AtEndOfStream
        line = Trim(ts.ReadLine)
        If Len(line) > 0 Then
            ReadFirstLine = line
            Exit Do
        End If
    Loop
    ts.Close
    On Error GoTo 0
End Function


' Строка диагностики в logs\launch.log (с автообрезкой, чтобы файл не рос вечно)
Sub WriteLog(dir, message)
    Dim logsDir, logPath, ts, size
    On Error Resume Next
    logsDir = fso.BuildPath(dir, "logs")
    If Not fso.FolderExists(logsDir) Then fso.CreateFolder(logsDir)
    logPath = fso.BuildPath(logsDir, "launch.log")
    If fso.FileExists(logPath) Then
        size = fso.GetFile(logPath).Size
        If size > 262144 Then fso.DeleteFile logPath      ' 256 КБ — с запасом
    End If
    Set ts = fso.OpenTextFile(logPath, 8, True)
    ts.WriteLine "[" & Now & "] " & message
    ts.Close
    On Error GoTo 0
End Sub


Sub DeleteQuietly(path)
    On Error Resume Next
    If fso.FileExists(path) Then fso.DeleteFile path
    On Error GoTo 0
End Sub
