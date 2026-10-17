# ============================================================================
#  server.ps1 — локальный сервер BudgetLIFE БЕЗ внешних зависимостей
# ----------------------------------------------------------------------------
#  Зачем: чтобы приложение запускалось двойным кликом по start.vbs на любом
#  компьютере с Windows — без установки Node.js, Python и чего-либо ещё.
#  В Windows есть PowerShell (с Windows 7) и .NET, этого достаточно.
#
#  Сервер повторяет правила стандарта SPECIALS (см. SPECIALS/README.md):
#    * порт только из своего блока ports.json (основной фиксирован — от него
#      зависит origin установленного PWA); занят — следующий порт блока;
#    * выбранный порт пишется в data\port.txt (первая строка — число, ниже JSON);
#    * обязательные маршруты /api/identity (личность) и /api/health (готовность)
#      — по ним лаунчер понимает, что сервер поднялся и что это именно мы;
#    * HTML, service worker и манифест отдаются с no-store;
#    * всё пишется в logs\server.log (ротация 1 МБ, хранятся 3 файла).
#
#  Запуск вручную (для отладки):
#    powershell -NoProfile -ExecutionPolicy Bypass -File server.ps1 -Port 5130
#
#  ВАЖНО: файл должен быть в UTF-8 с BOM, иначе Windows PowerShell 5.1
#  прочитает кириллицу как кракозябры.
# ============================================================================

param(
    [int]$Port = 0,                 # 0 = взять основной порт своего блока
    [string]$Address = '127.0.0.1', # только свой компьютер
    [string]$Dir = ''               # что раздавать (по умолчанию dist\)
)

$ErrorActionPreference = 'Stop'

# ── паспорт приложения ──────────────────────────────────────────────────────
$AppId      = 'budgetlife'
$AppName    = 'BudgetLIFE'
$AppVersion = '1.0.0'
$Engine     = 'powershell'
$FallbackBase = 5130
$FallbackSize = 10
$LockRangeStart = 18900
$LockRangeSpan  = 100

# ── пути ────────────────────────────────────────────────────────────────────
if ($PSScriptRoot) { $Root = $PSScriptRoot } else { $Root = Split-Path -Parent $MyInvocation.MyCommand.Definition }
$DataDir = Join-Path $Root 'data'
$LogsDir = Join-Path $Root 'logs'
if ([string]::IsNullOrEmpty($Dir)) { $DistDir = Join-Path $Root 'dist' } else { $DistDir = $Dir }
if (-not (Test-Path -LiteralPath $DataDir)) { New-Item -ItemType Directory -Path $DataDir -Force | Out-Null }
if (-not (Test-Path -LiteralPath $LogsDir)) { New-Item -ItemType Directory -Path $LogsDir -Force | Out-Null }
$LogPath  = Join-Path $LogsDir 'server.log'
$PortFile = Join-Path $DataDir 'port.txt'
$StartedAt = Get-Date

# ── логирование с ротацией ──────────────────────────────────────────────────
function Write-AppLog {
    param([string]$Message, [string]$Level = 'INFO')

    $line = '[' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + '] ' + $Level + ' ' + $Message
    try {
        if (Test-Path -LiteralPath $LogPath) {
            $item = Get-Item -LiteralPath $LogPath
            if ($item.Length -gt 1048576) {
                for ($i = 3; $i -ge 1; $i--) {
                    $from = $LogPath + '.' + $i
                    $to   = $LogPath + '.' + ($i + 1)
                    if (Test-Path -LiteralPath $from) { Move-Item -LiteralPath $from -Destination $to -Force }
                }
                Move-Item -LiteralPath $LogPath -Destination ($LogPath + '.1') -Force
            }
        }
        [System.IO.File]::AppendAllText($LogPath, $line + "`r`n", [System.Text.Encoding]::UTF8)
    } catch {
        # лог не должен ронять сервер
    }
    # Write-Host (не Write-Output!): строка не должна попадать в возвращаемое
    # значение функции, иначе она «сломает» результат (урок всех PS-скриптов)
    Write-Host $line
}

# ── MIME-типы ───────────────────────────────────────────────────────────────
$MimeTypes = @{
    '.html' = 'text/html; charset=utf-8'
    '.htm'  = 'text/html; charset=utf-8'
    '.js'   = 'text/javascript; charset=utf-8'
    '.mjs'  = 'text/javascript; charset=utf-8'
    '.css'  = 'text/css; charset=utf-8'
    '.json' = 'application/json; charset=utf-8'
    '.webmanifest' = 'application/manifest+json; charset=utf-8'
    '.map'  = 'application/json; charset=utf-8'
    '.svg'  = 'image/svg+xml'
    '.png'  = 'image/png'
    '.jpg'  = 'image/jpeg'
    '.jpeg' = 'image/jpeg'
    '.gif'  = 'image/gif'
    '.webp' = 'image/webp'
    '.ico'  = 'image/x-icon'
    '.woff' = 'font/woff'
    '.woff2' = 'font/woff2'
    '.ttf'  = 'font/ttf'
    '.txt'  = 'text/plain; charset=utf-8'
    '.wasm' = 'application/wasm'
}

# ── свой блок портов из ports.json ──────────────────────────────────────────
function Get-PortBlock {
    $base = $FallbackBase
    $size = $FallbackSize
    $path = Join-Path $Root 'ports.json'
    if (Test-Path -LiteralPath $path) {
        try {
            $raw  = [System.IO.File]::ReadAllText($path, [System.Text.Encoding]::UTF8)
            $json = ConvertFrom-Json -InputObject $raw
            foreach ($block in @($json.blocks)) {
                if ($block.app_id -eq $AppId) {
                    $base = [int]$block.base
                    $size = [int]$block.size
                }
            }
        } catch {
            Write-AppLog ('ports.json не прочитан: ' + $_.Exception.Message) 'WARN'
        }
    }
    return @($base, $size)
}

# ── служебный порт-лок (защита от гонки при одновременном запуске) ──────────
function Get-LockPort {
    try {
        $sha   = [System.Security.Cryptography.SHA1]::Create()
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($AppId)
        $hash  = $sha.ComputeHash($bytes)
        return $LockRangeStart + ((($hash[0] * 256) + $hash[1]) % $LockRangeSpan)
    } catch {
        return $LockRangeStart
    }
}

# ── проверка личности: на порту именно НАШ сервер? ──────────────────────────
function Test-OurServer {
    param([int]$CheckPort)

    try {
        $url = 'http://' + $Address + ':' + $CheckPort + '/api/identity'
        $req = [System.Net.HttpWebRequest]::Create($url)
        $req.Timeout = 900
        $req.ReadWriteTimeout = 900
        $req.KeepAlive = $false
        $resp = $req.GetResponse()
        try {
            $sr = New-Object System.IO.StreamReader($resp.GetResponseStream(), [System.Text.Encoding]::UTF8)
            $body = $sr.ReadToEnd()
            $sr.Close()
            if ($body -match '"app_id"\s*:\s*"budgetlife"') { return $true }
        } finally {
            $resp.Close()
        }
    } catch {
        # порт занят чужим или никто не слушает — это не наш сервер
    }
    return $false
}

# ── HTTP-ответ ──────────────────────────────────────────────────────────────
function Send-HttpResponse {
    param($Stream, [int]$Code, [string]$Reason, [byte[]]$Body, [string]$ContentType, [string]$Cache, [switch]$HeadOnly)

    if ($null -eq $Body) { $Body = New-Object byte[] 0 }

    $sb = New-Object System.Text.StringBuilder
    [void]$sb.Append('HTTP/1.1 ' + $Code + ' ' + $Reason + "`r`n")
    [void]$sb.Append('Content-Type: ' + $ContentType + "`r`n")
    [void]$sb.Append('Content-Length: ' + $Body.Length + "`r`n")
    [void]$sb.Append('Cache-Control: ' + $Cache + "`r`n")
    [void]$sb.Append('Server: BudgetLIFE' + "`r`n")
    [void]$sb.Append('Connection: close' + "`r`n`r`n")

    $head = [System.Text.Encoding]::ASCII.GetBytes($sb.ToString())
    $Stream.Write($head, 0, $head.Length)
    if (-not $HeadOnly) {
        if ($Body.Length -gt 0) { $Stream.Write($Body, 0, $Body.Length) }
    }
    $Stream.Flush()
}

function Get-ReasonPhrase {
    param([int]$Code)

    switch ($Code) {
        200 { return 'OK' }
        403 { return 'Forbidden' }
        404 { return 'Not Found' }
        405 { return 'Method Not Allowed' }
        500 { return 'Internal Server Error' }
        503 { return 'Service Unavailable' }
        default { return 'OK' }
    }
}

function Send-Json {
    param($Stream, [int]$Code, [string]$Text, [switch]$HeadOnly)

    $body = [System.Text.Encoding]::UTF8.GetBytes($Text)
    Send-HttpResponse -Stream $Stream -Code $Code -Reason (Get-ReasonPhrase -Code $Code) -Body $body -ContentType 'application/json; charset=utf-8' -Cache 'no-store' -HeadOnly:$HeadOnly
}

# ── политика кеширования (как в server.js) ──────────────────────────────────
function Get-CacheHeader {
    param([string]$RequestPath)

    if ($RequestPath.StartsWith('/assets/')) { return 'public, max-age=31536000, immutable' }
    if ($RequestPath -eq '/' -or $RequestPath.EndsWith('.html') -or $RequestPath.EndsWith('/sw.js') -or $RequestPath.EndsWith('.webmanifest')) {
        return 'no-store'
    }
    return 'public, max-age=60'
}

# ── обработка одного запроса ────────────────────────────────────────────────
function Invoke-Request {
    param($Stream, [string]$RequestLine)

    $parts = $RequestLine.Split(' ')
    $method = 'GET'
    $rawUrl = '/'
    if ($parts.Length -ge 1) { $method = $parts[0] }
    if ($parts.Length -ge 2) { $rawUrl = $parts[1] }

    $requestPath = '/'
    try {
        $uri = New-Object System.Uri('http://localhost' + $rawUrl)
        $requestPath = [System.Uri]::UnescapeDataString($uri.AbsolutePath)
    } catch {
        $requestPath = ($rawUrl.Split('?'))[0]
    }

    if ($method -ne 'GET' -and $method -ne 'HEAD') {
        Send-Json -Stream $Stream -Code 405 -Text '{"error":"Метод не поддерживается"}'
        return
    }
    $isHead = ($method -eq 'HEAD')

    # 1. Личность приложения (по ней лаунчер понимает, что сервер — наш)
    if ($requestPath -eq '/api/identity') {
        $lines = @()
        $lines += '{'
        $lines += '  "app_id": "' + $AppId + '",'
        $lines += '  "name": "' + $AppName + '",'
        $lines += '  "version": "' + $AppVersion + '",'
        $lines += '  "engine": "' + $Engine + '",'
        $lines += '  "pid": ' + $PID + ','
        $lines += '  "port": ' + $Script:ChosenPort + ','
        $lines += '  "host": "' + $Address + '",'
        $lines += '  "url": "http://' + $Address + ':' + $Script:ChosenPort + '/",'
        $lines += '  "data_dir": "' + ($DataDir -replace '\\', '\\') + '",'
        $lines += '  "dist": "' + ($DistDir -replace '\\', '\\') + '",'
        $lines += '  "started_at": "' + (Get-Date -Date $StartedAt -Format 'yyyy-MM-ddTHH:mm:ss') + '"'
        $lines += '}'
        Send-Json -Stream $Stream -Code 200 -Text ([string]::Join("`r`n", $lines)) -HeadOnly:$isHead
        return
    }

    # 2. Готовность (её ждёт start.vbs перед открытием окна)
    if ($requestPath -eq '/api/health') {
        $uptime = [int]((Get-Date) - $StartedAt).TotalMilliseconds
        $ready = 'false'
        if (Test-Path -LiteralPath (Join-Path $DistDir 'index.html')) { $ready = 'true' }
        $text = '{"ok":true,"app_id":"' + $AppId + '","version":"' + $AppVersion + '","engine":"' + $Engine + '","port":' + $Script:ChosenPort + ',"uptime_ms":' + $uptime + ',"dist_ready":' + $ready + '}'
        Send-Json -Stream $Stream -Code 200 -Text $text -HeadOnly:$isHead
        return
    }

    if ($requestPath.StartsWith('/api/')) {
        Send-Json -Stream $Stream -Code 404 -Text ('{"error":"Неизвестный маршрут API","path":"' + $requestPath + '"}') -HeadOnly:$isHead
        return
    }

    # 3. Статика из dist\
    $rootFull = [System.IO.Path]::GetFullPath($DistDir)
    $relative = $requestPath.TrimStart('/')
    if ([string]::IsNullOrEmpty($relative)) { $relative = 'index.html' }
    $full = [System.IO.Path]::GetFullPath((Join-Path $DistDir $relative))

    if (-not $full.StartsWith($rootFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        Send-Json -Stream $Stream -Code 403 -Text '{"error":"Доступ запрещён"}' -HeadOnly:$isHead
        return
    }

    if (Test-Path -LiteralPath $full -PathType Container) { $full = Join-Path $full 'index.html' }

    if (-not (Test-Path -LiteralPath $full -PathType Leaf)) {
        # SPA-fallback: у адреса нет расширения — отдаём index.html (роутер React разберётся)
        if ([string]::IsNullOrEmpty([System.IO.Path]::GetExtension($requestPath))) {
            $full = Join-Path $DistDir 'index.html'
        }
    }

    if (-not (Test-Path -LiteralPath $full -PathType Leaf)) {
        if (-not (Test-Path -LiteralPath (Join-Path $DistDir 'index.html'))) {
            $html = '<meta charset="utf-8"><title>BudgetLIFE</title><div style="font:16px system-ui;padding:40px;max-width:640px">' +
                    '<h1>Сборка не найдена</h1><p>Папка <code>dist\</code> пуста. Запустите <code>npm run build</code> ' +
                    '(или Обновить.cmd) и обновите страницу.</p></div>'
            $bytes = [System.Text.Encoding]::UTF8.GetBytes($html)
            Send-HttpResponse -Stream $Stream -Code 503 -Reason 'Service Unavailable' -Body $bytes -ContentType 'text/html; charset=utf-8' -Cache 'no-store' -HeadOnly:$isHead
            return
        }
        Send-Json -Stream $Stream -Code 404 -Text ('{"error":"Файл не найден","path":"' + $requestPath + '"}') -HeadOnly:$isHead
        return
    }

    try {
        $bytes = [System.IO.File]::ReadAllBytes($full)
        $ext = [System.IO.Path]::GetExtension($full).ToLowerInvariant()
        $contentType = 'application/octet-stream'
        if ($MimeTypes.ContainsKey($ext)) { $contentType = $MimeTypes[$ext] }
        Send-HttpResponse -Stream $Stream -Code 200 -Reason 'OK' -Body $bytes -ContentType $contentType -Cache (Get-CacheHeader -RequestPath $requestPath) -HeadOnly:$isHead
    } catch {
        Write-AppLog ('Ошибка отдачи ' + $full + ': ' + $_.Exception.Message) 'ERROR'
        Send-Json -Stream $Stream -Code 500 -Text '{"error":"Не удалось прочитать файл"}' -HeadOnly:$isHead
    }
}

# =============================== СТАРТ ======================================
Write-AppLog ('=== ' + $AppName + ' ' + $AppVersion + ' (PowerShell-сервер) ===')
Write-AppLog ('pid=' + $PID + ' папка=' + $Root + ' dist=' + $DistDir)

$block = Get-PortBlock
$blockBase = $block[0]
$blockSize = $block[1]
Write-AppLog ('блок портов=' + $blockBase + '-' + ($blockBase + $blockSize - 1) + ' (' + $AppId + ')')

$candidates = New-Object System.Collections.ArrayList
if ($Port -gt 0) { [void]$candidates.Add($Port) }
for ($i = 0; $i -lt $blockSize; $i++) {
    $candidate = $blockBase + $i
    if (-not $candidates.Contains($candidate)) { [void]$candidates.Add($candidate) }
}

# Порт-лок: если он занят, значит другой экземпляр уже запускается
$lockPort = Get-LockPort
$lock = $null
try {
    $lock = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Parse('127.0.0.1'), $lockPort)
    $lock.ExclusiveAddressUse = $true
    $lock.Start()
    Write-AppLog ('порт-лок ' + $lockPort + ' занят нами')
} catch {
    Write-AppLog ('порт-лок ' + $lockPort + ' занят — проверяю, нет ли уже запущенного экземпляра') 'WARN'
    foreach ($candidate in $candidates) {
        if (Test-OurServer -CheckPort $candidate) {
            Write-AppLog ('уже запущено на порту ' + $candidate + ' — выходим')
            exit 0
        }
    }
    Write-AppLog 'своего сервера нет, продолжаем запуск' 'WARN'
}

# Слушаем порт из своего блока
$listener = $null
$Script:ChosenPort = 0
foreach ($candidate in $candidates) {
    try {
        $probe = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Parse($Address), $candidate)
        $probe.ExclusiveAddressUse = $true
        $probe.Start()
        $listener = $probe
        $Script:ChosenPort = $candidate
        break
    } catch {
        Write-AppLog ('порт ' + $candidate + ' занят: ' + $_.Exception.Message) 'WARN'
        if (Test-OurServer -CheckPort $candidate) {
            Write-AppLog ('уже запущено на порту ' + $candidate + ' — второй экземпляр не нужен')
            if ($null -ne $lock) { $lock.Stop() }
            exit 0
        }
    }
}

if ($Script:ChosenPort -eq 0) {
    Write-AppLog ('в блоке ' + $blockBase + '-' + ($blockBase + $blockSize - 1) + ' нет свободного порта') 'ERROR'
    if ($null -ne $lock) { $lock.Stop() }
    exit 1
}

if ($Script:ChosenPort -ne $blockBase -and $Script:ChosenPort -ne $Port) {
    Write-AppLog ('основной порт занят — работаем на ' + $Script:ChosenPort) 'WARN'
}

# Фиксируем порт для лаунчера, ярлыков и диагностики
try {
    $payload = '{"port":' + $Script:ChosenPort + ',"app_id":"' + $AppId + '","pid":' + $PID + ',"host":"' + $Address + '","engine":"' + $Engine + '","url":"http://' + $Address + ':' + $Script:ChosenPort + '/","updated_at":"' + (Get-Date -Format 'yyyy-MM-ddTHH:mm:ss') + '"}'
    [System.IO.File]::WriteAllText($PortFile, $Script:ChosenPort + "`r`n" + $payload + "`r`n", [System.Text.Encoding]::UTF8)
} catch {
    Write-AppLog ('не удалось записать port.txt: ' + $_.Exception.Message) 'WARN'
}

Write-AppLog ('Готово: http://' + $Address + ':' + $Script:ChosenPort + '/')
if (-not (Test-Path -LiteralPath (Join-Path $DistDir 'index.html'))) {
    Write-AppLog 'ВНИМАНИЕ: dist\index.html не найден — выполните npm run build' 'WARN'
}

# Основной цикл: принимаем по одному соединению и отвечаем.
# Connection: close — браузер сам открывает новое соединение на следующий файл.
try {
    while ($true) {
        $client = $null
        try {
            $client = $listener.AcceptTcpClient()
            $client.NoDelay = $true
            $client.ReceiveTimeout = 5000
            $client.SendTimeout = 20000
            $stream = $client.GetStream()
            $reader = New-Object System.IO.StreamReader($stream, [System.Text.Encoding]::ASCII)

            $requestLine = $reader.ReadLine()
            if (-not [string]::IsNullOrWhiteSpace($requestLine)) {
                while ($true) {
                    $header = $reader.ReadLine()
                    if ($null -eq $header) { break }
                    if ($header -eq '') { break }
                }
                Invoke-Request -Stream $stream -RequestLine $requestLine
            }
        } catch {
            # «Пустое» соединение (предподключение браузера) и обрывы — норма
            $message = ''
            if ($null -ne $_.Exception) { $message = $_.Exception.Message }
            if ($message -notmatch 'времени|time|timeout|удаленный хост|forcibly') {
                Write-AppLog ('запрос: ' + $message) 'WARN'
            }
        } finally {
            if ($null -ne $client) {
                try { $client.Close() } catch { }
            }
        }
    }
} finally {
    Write-AppLog 'сервер останавливается'
    try { $listener.Stop() } catch { }
    try { if ($null -ne $lock) { $lock.Stop() } } catch { }
    try { if (Test-Path -LiteralPath $PortFile) { Remove-Item -LiteralPath $PortFile -Force } } catch { }
}
