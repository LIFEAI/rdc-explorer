#Requires -Version 5.1
<#
.SYNOPSIS
    RDC Explorer Installer
.DESCRIPTION
    Downloads and installs RDC Explorer with Desktop and Start Menu shortcuts.
    Run by right-clicking and selecting "Run with PowerShell".
#>

$ErrorActionPreference = "Stop"
$Host.UI.RawUI.WindowTitle = "RDC Explorer Installer"

function Write-Step  { Write-Host " [..] $args" -ForegroundColor Cyan }
function Write-OK    { Write-Host " [OK] $args" -ForegroundColor Green }
function Write-Fail  { Write-Host " [ERROR] $args" -ForegroundColor Red }
function Write-Warn  { Write-Host " [WARN] $args" -ForegroundColor Yellow }

Clear-Host
Write-Host ""
Write-Host " ============================================================" -ForegroundColor DarkCyan
Write-Host "   RDC Explorer Installer" -ForegroundColor White
Write-Host "   Regenerative Development Corp" -ForegroundColor Gray
Write-Host " ============================================================" -ForegroundColor DarkCyan
Write-Host ""
Write-Host " This will install RDC Explorer to your computer." -ForegroundColor White
Write-Host " No Git or technical setup required." -ForegroundColor Gray
Write-Host ""
Read-Host " Press Enter to begin"

# ── Paths ─────────────────────────────────────────────────────
$InstallDir = "$env:LOCALAPPDATA\RDC_Explorer"
$TempDir    = "$env:TEMP\RDC_Explorer_Install"
$RepoZip    = "$TempDir\repo.zip"
$RepoUrl    = "https://github.com/LIFEAI/rdc-ai-dashboard/archive/refs/heads/main.zip"
$VenvDir    = "$InstallDir\venv"
$PythonW    = "$VenvDir\Scripts\pythonw.exe"
$PipExe     = "$VenvDir\Scripts\pip.exe"
$Launcher   = "$InstallDir\RDC_Explorer.bat"
$IconPath   = "$InstallDir\assets\icon.ico"
$StartDir   = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\RDC Explorer"
$Desktop    = [Environment]::GetFolderPath("Desktop")

Write-Step "Install location: $InstallDir"
Write-Host ""

# ── Python check ──────────────────────────────────────────────
Write-Step "Checking for Python..."
try {
    $pyVer = & python --version 2>&1
    Write-OK "Found $pyVer"
} catch {
    Write-Fail "Python is not installed."
    Write-Host ""
    Write-Host "  Please install Python 3.11+ from:" -ForegroundColor Yellow
    Write-Host "  https://www.python.org/downloads/" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  IMPORTANT: Check 'Add Python to PATH' during install," -ForegroundColor Yellow
    Write-Host "  then re-run this installer." -ForegroundColor Yellow
    Start-Process "https://www.python.org/downloads/"
    Read-Host "`n Press Enter to exit"
    exit 1
}

# ── Clean previous install ────────────────────────────────────
if (Test-Path $InstallDir) {
    Write-Step "Removing previous installation..."
    Remove-Item -Recurse -Force $InstallDir
}
if (Test-Path $TempDir) { Remove-Item -Recurse -Force $TempDir }
New-Item -ItemType Directory -Force $TempDir | Out-Null
New-Item -ItemType Directory -Force $InstallDir | Out-Null

# ── Download ──────────────────────────────────────────────────
Write-Step "Downloading RDC Explorer from GitHub..."
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $RepoUrl -OutFile $RepoZip -UseBasicParsing
    Write-OK "Download complete."
} catch {
    Write-Fail "Download failed: $_"
    Read-Host "`n Press Enter to exit"
    exit 1
}

# ── Extract ───────────────────────────────────────────────────
Write-Step "Extracting files..."
Expand-Archive -Path $RepoZip -DestinationPath $TempDir -Force
$Extracted = Get-ChildItem $TempDir -Directory | Select-Object -First 1
if (-not $Extracted) {
    Write-Fail "Extraction failed."
    Read-Host "`n Press Enter to exit"
    exit 1
}
Copy-Item -Recurse -Force "$($Extracted.FullName)\*" $InstallDir
Write-OK "Files installed."

# ── Python venv ───────────────────────────────────────────────
Write-Step "Setting up Python environment (first time, ~2 minutes)..."
& python -m venv $VenvDir
if ($LASTEXITCODE -ne 0) {
    Write-Fail "Failed to create Python environment."
    Read-Host "`n Press Enter to exit"
    exit 1
}
Write-OK "Python environment ready."

# ── Install dependencies ──────────────────────────────────────
Write-Step "Installing dependencies..."
& $PipExe install --upgrade pip -q
& $PipExe install -r "$InstallDir\requirements.txt" -q
& $PipExe install pillow -q
Write-OK "Dependencies installed."

# ── Generate icons ────────────────────────────────────────────
Write-Step "Generating icons..."
& "$VenvDir\Scripts\python.exe" "$InstallDir\assets\create_icon.py" 2>$null
Write-OK "Icons ready."

# ── Launcher script ───────────────────────────────────────────
Write-Step "Creating launcher..."
$LauncherContent = "@echo off`r`ncd /d `"$InstallDir`"`r`nset QT_QPA_PLATFORM_PLUGIN_PATH=`"$VenvDir\Lib\site-packages\PyQt6\Qt6\plugins\platforms`"`r`nstart `"`" `"$VenvDir\Scripts\python.exe`" `"$InstallDir\src\rdc_dashboard.py`"`r`n"
Set-Content -Path $Launcher -Value $LauncherContent -Encoding ASCII

# ── Desktop shortcut ──────────────────────────────────────────
Write-Step "Creating Desktop shortcut..."
$WS = New-Object -ComObject WScript.Shell
$Shortcut = $WS.CreateShortcut("$Desktop\RDC Explorer.lnk")
$Shortcut.TargetPath      = $Launcher
$Shortcut.WorkingDirectory = $InstallDir
$Shortcut.IconLocation    = $IconPath
$Shortcut.Description     = "RDC Explorer"
$Shortcut.Save()
Write-OK "Desktop shortcut created."

# ── Start Menu ────────────────────────────────────────────────
Write-Step "Creating Start Menu entry..."
New-Item -ItemType Directory -Force $StartDir | Out-Null

$SM = $WS.CreateShortcut("$StartDir\RDC Explorer.lnk")
$SM.TargetPath       = $Launcher
$SM.WorkingDirectory = $InstallDir
$SM.IconLocation     = $IconPath
$SM.Description      = "RDC Explorer"
$SM.Save()

# Uninstaller
$UninstallScript = @"
@echo off
echo Uninstalling RDC Explorer...
rmdir /s /q "$InstallDir"
del /f /q "$Desktop\RDC Explorer.lnk"
rmdir /s /q "$StartDir"
echo Done.
pause
"@
Set-Content -Path "$StartDir\Uninstall RDC Explorer.bat" -Value $UninstallScript -Encoding ASCII
Write-OK "Start Menu entry created."

# ── Cleanup ───────────────────────────────────────────────────
Remove-Item -Recurse -Force $TempDir -ErrorAction SilentlyContinue

# ── Done ──────────────────────────────────────────────────────
Write-Host ""
Write-Host " ============================================================" -ForegroundColor DarkCyan
Write-Host "   Installation complete!" -ForegroundColor Green
Write-Host ""
Write-Host "   RDC Explorer is installed." -ForegroundColor White
Write-Host "   Launch it from your Desktop or Start Menu." -ForegroundColor White
Write-Host " ============================================================" -ForegroundColor DarkCyan
Write-Host ""

$Launch = Read-Host " Launch RDC Explorer now? (Y/N)"
if ($Launch -match "^[Yy]") {
    Start-Process "cmd.exe" -ArgumentList "/c `"$Launcher`"" -WorkingDirectory $InstallDir
}

Write-Host ""
Write-Host " Life before Profits." -ForegroundColor DarkGray
Write-Host ""
Read-Host " Press Enter to exit"
