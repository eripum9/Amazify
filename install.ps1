param(
    [switch] $NoPathUpdate,
    [switch] $NonEditable
)

$ErrorActionPreference = "Stop"

function Find-Python {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        return @($py.Source, "-3")
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        return @($python.Source)
    }

    throw "Python 3.10+ was not found on PATH. Install Python, then rerun this script."
}

function Invoke-InstallerPython {
    param([string[]] $Arguments)
    & $script:PythonExecutable @script:PythonPrefix @Arguments
}

function Get-NormalizedPath {
    param([string] $Path)
    if (-not $Path) {
        return ""
    }
    return [System.IO.Path]::GetFullPath($Path.Trim()).TrimEnd("\")
}

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonCommand = Find-Python
$script:PythonExecutable = $pythonCommand[0]
$script:PythonPrefix = @()
if ($pythonCommand.Length -gt 1) {
    $script:PythonPrefix = $pythonCommand[1..($pythonCommand.Length - 1)]
}

$version = Invoke-InstallerPython -Arguments @("-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
if ([version] $version -lt [version] "3.10") {
    throw "Amazify requires Python 3.10+. Detected Python $version."
}

$installArgs = @("-m", "pip", "install", "--user")
if ($NonEditable) {
    $installArgs += "--upgrade"
    $installArgs += $repoRoot
} else {
    $installArgs += "--upgrade"
    $installArgs += "--editable"
    $installArgs += $repoRoot
}

Write-Host "Installing Amazify for the current user..."
Invoke-InstallerPython -Arguments $installArgs

$scriptsDir = Invoke-InstallerPython -Arguments @("-c", "import os, site, sysconfig; print(sysconfig.get_path('scripts', scheme='nt_user') or os.path.join(site.USER_BASE, 'Scripts'))")
$scriptsDir = Get-NormalizedPath $scriptsDir

if (-not (Test-Path -LiteralPath $scriptsDir)) {
    New-Item -ItemType Directory -Force -Path $scriptsDir | Out-Null
}

if (-not $NoPathUpdate) {
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $entries = @()
    if ($userPath) {
        $entries = $userPath.Split(";") | Where-Object { $_ -and $_.Trim() }
    }
    $normalizedEntries = $entries | ForEach-Object { Get-NormalizedPath $_ }
    if ($normalizedEntries -notcontains $scriptsDir) {
        $nextPath = (@($entries) + $scriptsDir) -join ";"
        [Environment]::SetEnvironmentVariable("Path", $nextPath, "User")
        $env:Path = (@($env:Path.Split(";")) + $scriptsDir) -join ";"
        Write-Host "Added to user PATH: $scriptsDir"
    } else {
        Write-Host "User PATH already contains: $scriptsDir"
    }
}

$amazifyCommand = Join-Path $scriptsDir "amazify.exe"
if (-not (Test-Path -LiteralPath $amazifyCommand)) {
    $amazifyCommand = Join-Path $scriptsDir "amazify.cmd"
}

if (-not (Test-Path -LiteralPath $amazifyCommand)) {
    throw "Install finished, but the amazify command was not found in $scriptsDir."
}

Write-Host ""
Write-Host "Amazify is installed."
Write-Host "Command: amazify"
Write-Host "Path: $amazifyCommand"
Write-Host ""
Write-Host "Open a new terminal if the amazify command is not visible in this one yet."
