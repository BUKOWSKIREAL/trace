#!/usr/bin/env pwsh
# Build Trace for Windows:
#   1. Sync Python dependencies with uv.
#   2. Build the Electron Console as win-unpacked.
#   3. Build Trace.exe and TraceBridge.exe with PyInstaller.
#   4. Copy the Electron Console beside the portable app folder.
#   5. Verify the portable app folder and TraceBridge MCP handshake.

[CmdletBinding()]
param(
    [ValidateSet("x64", "ia32", "arm64")]
    [string]$Arch = "x64"
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Resolve-Path (Join-Path $ScriptDir "..")
Set-Location $Root

$AppName = "Trace"
$ElectronAppName = "Trace Console"
$ElectronDistDir = Join-Path $Root "electron_app\dist"
$DistAppDir = Join-Path $Root "dist\Trace"
$ElectronOutName = if ($Arch -eq "x64") { "win-unpacked" } else { "win-$Arch-unpacked" }
$ExpectedElectronOutDir = Join-Path $ElectronDistDir $ElectronOutName

Write-Host "=== Trace Windows packaging ==="
Write-Host "project: $Root"
Write-Host "arch: $Arch"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv is required. Install it first, then rerun this script."
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "npm is required to build the bundled Electron console."
}

Write-Host "[1/6] Sync Python environment"
uv sync --frozen

Write-Host "[2/6] Build Electron console for Windows"
Push-Location (Join-Path $Root "electron_app")
try {
    npm install
    if (Test-Path $ExpectedElectronOutDir) {
        Remove-Item $ExpectedElectronOutDir -Recurse -Force
    }
    npm run build:renderer
    npx electron-builder --win --dir "--$Arch"
}
finally {
    Pop-Location
}

$ElectronOutDir = $ExpectedElectronOutDir
if (-not (Test-Path $ElectronOutDir)) {
    throw "Electron build did not create expected folder: $ElectronOutDir"
}

$ElectronExe = Join-Path $ElectronOutDir "$ElectronAppName.exe"
if (-not (Test-Path $ElectronExe)) {
    throw "Electron build did not create expected executable: $ElectronExe"
}

Write-Host "[3/6] Build Python tray app with PyInstaller"
if (Test-Path $DistAppDir) {
    Remove-Item $DistAppDir -Recurse -Force
}
$env:TRACE_ELECTRON_WIN_DIR = $ElectronOutDir
uv run python -m PyInstaller --noconfirm --clean Trace-windows.spec

Write-Host "[4/6] Stage bundled Electron console beside portable app"
$BundledElectronDir = Join-Path $DistAppDir "electron"
if (Test-Path $BundledElectronDir) {
    Remove-Item $BundledElectronDir -Recurse -Force
}
Copy-Item -Path $ElectronOutDir -Destination $BundledElectronDir -Recurse

Write-Host "[5/6] Verify Windows portable folder"
$TraceExe = Join-Path $DistAppDir "Trace.exe"
$BridgeExe = Join-Path $DistAppDir "TraceBridge.exe"
$BundledElectronExe = Join-Path $DistAppDir "electron\Trace Console.exe"
foreach ($Required in @($TraceExe, $BridgeExe, $BundledElectronExe)) {
    if (-not (Test-Path $Required)) {
        throw "Missing packaged file: $Required"
    }
}

$BridgeWorkspace = Join-Path $DistAppDir "__bridge_mcp_check_workspace"
if (Test-Path $BridgeWorkspace) {
    Remove-Item $BridgeWorkspace -Recurse -Force
}
New-Item -ItemType Directory -Path $BridgeWorkspace | Out-Null
try {
    $Initialize = @{
        jsonrpc = "2.0"
        id = 1
        method = "initialize"
        params = @{
            protocolVersion = "2024-11-05"
            capabilities = @{}
            clientInfo = @{
                name = "Trace Windows packaging"
                version = "0"
            }
        }
    } | ConvertTo-Json -Depth 8 -Compress
    $Initialized = @{
        jsonrpc = "2.0"
        method = "notifications/initialized"
        params = @{}
    } | ConvertTo-Json -Depth 8 -Compress
    $ToolsList = @{
        jsonrpc = "2.0"
        id = 2
        method = "tools/list"
        params = @{}
    } | ConvertTo-Json -Depth 8 -Compress
    $Payload = ""
    foreach ($Message in @($Initialize, $Initialized, $ToolsList)) {
        $Length = [Text.Encoding]::UTF8.GetByteCount($Message)
        $Payload += "Content-Length: $Length`r`n`r`n$Message"
    }

    $StartInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $StartInfo.FileName = $BridgeExe
    $StartInfo.ArgumentList.Add("mcp.trace_server")
    $StartInfo.ArgumentList.Add("--workspace")
    $StartInfo.ArgumentList.Add($BridgeWorkspace)
    $StartInfo.RedirectStandardInput = $true
    $StartInfo.RedirectStandardOutput = $true
    $StartInfo.RedirectStandardError = $true
    $StartInfo.UseShellExecute = $false
    $BridgeProcess = [System.Diagnostics.Process]::Start($StartInfo)
    try {
        $PayloadBytes = [Text.Encoding]::UTF8.GetBytes($Payload)
        $BridgeProcess.StandardInput.BaseStream.Write($PayloadBytes, 0, $PayloadBytes.Length)
        $BridgeProcess.StandardInput.Close()
        $BridgeOutput = $BridgeProcess.StandardOutput.ReadToEnd()
        $BridgeError = $BridgeProcess.StandardError.ReadToEnd()
        if (-not $BridgeProcess.WaitForExit(10000)) {
            $BridgeProcess.Kill()
            throw "TraceBridge MCP handshake timed out"
        }
        $BridgeExitCode = $BridgeProcess.ExitCode
    }
    finally {
        if ($null -ne $BridgeProcess) {
            $BridgeProcess.Dispose()
        }
    }
    if ($BridgeExitCode -ne 0) {
        throw "TraceBridge MCP handshake exited with $($BridgeExitCode): $BridgeError"
    }
    if ($BridgeOutput -notmatch "trace_record_files") {
        throw "TraceBridge MCP handshake did not return trace_record_files"
    }
}
finally {
    if (Test-Path $BridgeWorkspace) {
        Remove-Item $BridgeWorkspace -Recurse -Force
    }
}

Write-Host "[6/6] Done"
Write-Host "portable app: $DistAppDir"
Write-Host "run: $TraceExe"
