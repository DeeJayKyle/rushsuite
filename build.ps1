<#
  RushSuite one-click Windows build (PDF tools + Read & Listen in one app).
  Produces:  dist\RushSuite\RushSuite.exe  (+ runtime, app, models, llm, ffmpeg, extension folders)

  Usage (normally via build.bat, or GitHub Actions with -CI):
    powershell -ExecutionPolicy Bypass -File build.ps1 [-Clone] [-NoLLM] [-NoSelfTest] [-CI]
#>
param(
    [switch]$Clone,       # add "clone your voice" (XTTS, ~3 GB extra)
    [switch]$NoLLM,       # skip the 2.5 GB offline AI model (online AI still works)
    [switch]$NoSelfTest,
    [switch]$CI           # GitHub Actions: no desktop shortcut, self-test never fails the build
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Root  = Split-Path -Parent $MyInvocation.MyCommand.Path
$Cache = Join-Path $Root ".build_cache"
$Dist  = Join-Path $Root "dist\RushSuite"
$Runtime = Join-Path $Dist "runtime"
$Py = Join-Path $Runtime "python.exe"
New-Item -ItemType Directory -Force -Path $Cache, $Dist | Out-Null
Start-Transcript -Path (Join-Path $Root "build.log") -Force | Out-Null

function Step($n, $msg) { Write-Host ""; Write-Host "[$n/9] $msg" -ForegroundColor Yellow }
function Fail($msg) {
    Write-Host ""; Write-Host "BUILD FAILED: $msg" -ForegroundColor Red
    Write-Host "See build.log for details. Fix the problem and run build.bat again (finished steps are skipped)."
    Stop-Transcript | Out-Null; exit 1
}
function Download($url, $out) {
    if (Test-Path $out) { return }
    Write-Host "  downloading $url"
    $tmp = "$out.part"
    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    if ($curl) {
        & curl.exe -L --fail --retry 3 -o $tmp $url
        if ($LASTEXITCODE -ne 0) { Fail "download failed: $url" }
    } else {
        Invoke-WebRequest -Uri $url -OutFile $tmp -UseBasicParsing
    }
    Move-Item -Force $tmp $out
}

Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "  RushSuite build  (voice cloning: $Clone, offline AI: $(-not $NoLLM))" -ForegroundColor Cyan
Write-Host "  Needs ~10 GB free disk and internet ONCE."     -ForegroundColor Cyan
Write-Host "  After this, RushSuite runs fully offline."     -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan

# ---------------------------------------------------------------- 1. uv
Step 1 "Getting the 'uv' package manager"
$uvDir = Join-Path $Cache "uv"
$uv = Join-Path $uvDir "uv.exe"
if (-not (Test-Path $uv)) {
    $zip = Join-Path $Cache "uv.zip"
    Download "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip" $zip
    Expand-Archive -Force $zip $uvDir
    $found = Get-ChildItem $uvDir -Recurse -Filter uv.exe | Select-Object -First 1
    if (-not $found) { Fail "uv.exe not found after download" }
    if ($found.FullName -ne $uv) { Copy-Item $found.FullName $uv -Force }
}
$env:UV_CACHE_DIR = Join-Path $Cache "uv-cache"
$env:UV_LINK_MODE = "copy"
$env:UV_PYTHON_INSTALL_DIR = Join-Path $Cache "python"
$env:UV_HTTP_TIMEOUT = "600"

# ---------------------------------------------------------------- 2. portable python
Step 2 "Creating portable Python 3.11 runtime"
if (-not (Test-Path $Py)) {
    & $uv python install 3.11
    if ($LASTEXITCODE -ne 0) { Fail "could not download Python 3.11" }
    $pyHome = Get-ChildItem $env:UV_PYTHON_INSTALL_DIR -Directory | Where-Object { $_.Name -like "cpython-3.11*" } | Select-Object -First 1
    if (-not $pyHome) { Fail "portable Python not found" }
    & robocopy $pyHome.FullName $Runtime /E /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { Fail "copying Python runtime failed" }
    $global:LASTEXITCODE = 0
}
Get-ChildItem $Runtime -Recurse -Filter "EXTERNALLY-MANAGED" -ErrorAction SilentlyContinue | Remove-Item -Force
& $Py --version

# ---------------------------------------------------------------- 3. libraries
Step 3 "Installing engines (voices, speech recognition, OCR, Qt) - be patient"
$LogDir = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

# Runs uv with its full output captured into logs\<name>.txt AND shown here (so it lands in build.log).
function Uv-Install($name, [string[]]$pkgArgs) {
    $all = @("pip", "install", "--python", $Py, "--break-system-packages") + $pkgArgs
    $quoted = ($all | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }) -join " "
    $out = Join-Path $LogDir "$name.out.txt"
    $err = Join-Path $LogDir "$name.err.txt"
    Write-Host "  > uv $quoted"
    $p = Start-Process -FilePath $uv -ArgumentList $quoted -NoNewWindow -Wait -PassThru `
        -RedirectStandardOutput $out -RedirectStandardError $err
    $p.WaitForExit()
    $lines = @()
    if (Test-Path $out) { $lines += Get-Content $out }
    if (Test-Path $err) { $lines += Get-Content $err }
    $lines | Select-Object -Last 60 | ForEach-Object { Write-Host "    $_" }
    return $p.ExitCode
}

# Runs any program with full output saved to logs\<name>.*.txt and shown here (so it lands in build.log).
function Run-Logged($name, $exe, [string[]]$argList, [int]$tail = 80) {
    $quoted = ($argList | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }) -join " "
    $out = Join-Path $LogDir "$name.out.txt"
    $err = Join-Path $LogDir "$name.err.txt"
    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"
    $p = Start-Process -FilePath $exe -ArgumentList $quoted -NoNewWindow -Wait -PassThru `
        -RedirectStandardOutput $out -RedirectStandardError $err
    $p.WaitForExit()
    $lines = @()
    if (Test-Path $out) { $lines += Get-Content $out -Encoding UTF8 }
    if (Test-Path $err) { $lines += Get-Content $err -Encoding UTF8 | Where-Object { $_ -notmatch '^\s*\d+%\|' } }
    $lines | Select-Object -Last $tail | ForEach-Object { Write-Host "    $_" }
    return $p.ExitCode
}

$constraints = Join-Path $Root "constraints.txt"
$code = Uv-Install "02-core" @("-r", (Join-Path $Root "requirements-core.txt"), "-c", $constraints)
if ($code -ne 0) { Fail "core library install failed (see logs\02-core.err.txt)" }
$code = Uv-Install "03-voices" @("kokoro-onnx>=0.4", "-c", $constraints)
if ($code -ne 0) { Fail "voice engine install failed (see logs\03-voices.err.txt)" }

$warn = @()
if ((Uv-Install "03b-pdf-extra" @("pdf2docx>=0.5.8", "pymupdf4llm", "-c", $constraints)) -ne 0) { $warn += "high-fidelity PDF to Word / Markdown (optional)" }
if ((Uv-Install "04-stt" @("faster-whisper>=1.0", "-c", $constraints)) -ne 0) { $warn += "speech recognition (logs\04-stt.err.txt)" }
if ((Uv-Install "05-ocr" @("rapidocr_onnxruntime>=1.3", "-c", $constraints)) -ne 0) {
    if ((Uv-Install "05-ocr-b" @("rapidocr", "onnxruntime", "-c", $constraints)) -ne 0) { $warn += "OCR (logs\05-ocr.err.txt)" }
}
if ((Uv-Install "06-piper" @("piper-tts>=1.2", "-c", $constraints)) -ne 0) { $warn += "extra Piper voices (optional)" }
if ((Uv-Install "07-web" @("trafilatura", "-c", $constraints)) -ne 0) { $warn += "better web-article extraction (optional)" }
if ($Clone) {
    $ok = (Uv-Install "08-torch" @("torch==2.5.1", "torchaudio==2.5.1")) -eq 0
    if ($ok) {
        $ok = $false
        foreach ($spec in @("coqui-tts>=0.24.2", "coqui-tts>=0.24.2,<0.27")) {
            if ((Uv-Install "08-clone" @($spec, "-c", $constraints)) -eq 0) { $ok = $true; break }
        }
    }
    if (-not $ok) { $warn += "voice cloning (logs\08-clone.err.txt)"; $Clone = $false }
}
$null = Run-Logged "09-check" $uv @("pip", "check", "--python", $Py) 30
foreach ($w in $warn) { Write-Host "  WARNING: not installed: $w" -ForegroundColor DarkYellow }

# ---------------------------------------------------------------- 4. app code
Step 4 "Copying RushSuite app"
$AppDst = Join-Path $Dist "app"
if (Test-Path $AppDst) { Remove-Item -Recurse -Force $AppDst }
& robocopy (Join-Path $Root "app") $AppDst /E /XD __pycache__ /NFL /NDL /NJH /NJS /NP | Out-Null
& robocopy (Join-Path $Root "tools") (Join-Path $Dist "tools") /E /XD __pycache__ /NFL /NDL /NJH /NJS /NP | Out-Null
& robocopy (Join-Path $Root "extension") (Join-Path $Dist "extension") /E /NFL /NDL /NJH /NJS /NP | Out-Null
$global:LASTEXITCODE = 0
Copy-Item (Join-Path $Root "README.md") $Dist -Force

# ---------------------------------------------------------------- 5. ffmpeg
Step 5 "Adding ffmpeg (needed for MP3 and M4A)"
$ffDst = Join-Path $Dist "ffmpeg\ffmpeg.exe"
if (-not (Test-Path $ffDst)) {
    try {
        $ffZip = Join-Path $Cache "ffmpeg.zip"
        Download "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" $ffZip
        $ffTmp = Join-Path $Cache "ffmpeg"
        Expand-Archive -Force $ffZip $ffTmp
        $exe = Get-ChildItem $ffTmp -Recurse -Filter ffmpeg.exe | Select-Object -First 1
        New-Item -ItemType Directory -Force -Path (Split-Path $ffDst) | Out-Null
        Copy-Item $exe.FullName $ffDst -Force
        $probe = Get-ChildItem $ffTmp -Recurse -Filter ffprobe.exe | Select-Object -First 1
        if ($probe) { Copy-Item $probe.FullName (Join-Path (Split-Path $ffDst) "ffprobe.exe") -Force }
    } catch {
        Fail "could not download ffmpeg ($_) - check internet and retry"
    }
}

# ---------------------------------------------------------------- 6. offline AI engine + models
Step 6 "Offline AI engine (llama.cpp) and models (one time, ~4 GB)"
$llmDir = Join-Path $Dist "llm"
if (-not $NoLLM -and -not (Get-ChildItem $llmDir -Recurse -Filter llama-server.exe -ErrorAction SilentlyContinue)) {
    try {
        $rel = Invoke-RestMethod -Uri "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest" -UseBasicParsing
        $asset = $rel.assets | Where-Object { $_.name -match "bin-win-cpu-x64\.zip$" } | Select-Object -First 1
        if (-not $asset) { $asset = $rel.assets | Where-Object { $_.name -match "bin-win-avx2-x64\.zip$" } | Select-Object -First 1 }
        if (-not $asset) { throw "no Windows CPU build found in release $($rel.tag_name)" }
        $zip = Join-Path $Cache $asset.name
        Download $asset.browser_download_url $zip
        New-Item -ItemType Directory -Force -Path $llmDir | Out-Null
        Expand-Archive -Force $zip $llmDir
        Write-Host "  llama.cpp $($rel.tag_name) installed"
    } catch {
        Write-Host "  WARNING: offline AI engine not installed ($_). Online AI keys still work." -ForegroundColor DarkYellow
    }
}
$dlArgs = @("-u", (Join-Path $Dist "tools\download_models.py"))
if ($NoLLM) { $dlArgs += "--no-llm" }
if ($Clone) { $dlArgs += "--clone" }
Write-Host "  (large downloads - 10-40 minutes depending on your connection; full log: logs\06-models.out.txt)"
$code = Run-Logged "06-models" $Py $dlArgs
if ($code -ne 0) { Fail "essential model download failed - send logs\06-models.out.txt and logs\06-models.err.txt" }

# ---------------------------------------------------------------- 7. launcher exe
Step 7 "Compiling RushSuite.exe launcher"
$csc = Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if (-not (Test-Path $csc)) { $csc = Join-Path $env:WINDIR "Microsoft.NET\Framework\v4.0.30319\csc.exe" }
if (-not (Test-Path $csc)) { Fail ".NET Framework 4 compiler (csc.exe) not found - enable .NET Framework 4.8 in Windows Features" }
$exeOut = Join-Path $Dist "RushSuite.exe"
& $csc /nologo /target:winexe /optimize+ "/out:$exeOut" "/win32icon:$(Join-Path $Root 'app\assets\icon.ico')" `
    /r:System.Windows.Forms.dll (Join-Path $Root "launcher\Launcher.cs")
if ($LASTEXITCODE -ne 0) { Fail "launcher compile failed" }

# debug launcher with a console window (shows errors)
@"
@echo off
cd /d "%~dp0"
set PYTHONNOUSERSITE=1
set PYTHONPATH=
"%~dp0runtime\python.exe" "%~dp0app\main.py" %*
pause
"@ | Set-Content -Encoding ASCII (Join-Path $Dist "RushSuite (debug console).bat")

@"
@echo off
cd /d "%~dp0"
"%~dp0runtime\python.exe" "%~dp0tools\selftest.py"
pause
"@ | Set-Content -Encoding ASCII (Join-Path $Dist "Run self-test.bat")

# ---------------------------------------------------------------- 8. self test
Step 8 "Self-test (checks every engine runs on this PC)"
if (-not $NoSelfTest) {
    $code = Run-Logged "10-selftest" $Py @("-u", (Join-Path $Dist "tools\selftest.py")) 120
    if ($code -ne 0) {
        Write-Host "  Some checks failed - send logs\10-selftest.*.txt. The app may still work for the passing features." -ForegroundColor DarkYellow
    }
}

# ---------------------------------------------------------------- 9. shortcut
Step 9 "Creating desktop shortcut"
if (-not $CI) { try {
    $ws = New-Object -ComObject WScript.Shell
    $lnk = $ws.CreateShortcut((Join-Path ([Environment]::GetFolderPath("Desktop")) "RushSuite.lnk"))
    $lnk.TargetPath = $exeOut
    $lnk.WorkingDirectory = $Dist
    $lnk.IconLocation = "$exeOut,0"
    $lnk.Save()
} catch { Write-Host "  (shortcut skipped)" } }

$size = [math]::Round(((Get-ChildItem $Dist -Recurse -File | Measure-Object Length -Sum).Sum / 1GB), 2)
Write-Host ""
Write-Host "==============================================" -ForegroundColor Green
Write-Host "  DONE!  $exeOut" -ForegroundColor Green
Write-Host "  Folder size: $size GB. Copy the whole dist\RushSuite folder to move it to another PC." -ForegroundColor Green
Write-Host "==============================================" -ForegroundColor Green
Stop-Transcript | Out-Null
