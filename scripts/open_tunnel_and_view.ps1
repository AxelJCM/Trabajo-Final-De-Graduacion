param(
    [string]$PiHost = "192.168.1.77",
    [string]$PiUser = "axeljcm",
    [int]$LocalPort = 8000,
    [int]$RemotePort = 8000,
    [switch]$Quiet
)

# Opens an SSH local port forward (localhost:$LocalPort -> $PiHost:$RemotePort)
# and launches the Smart Mirror debug view through the tunnel.

function Write-Info($msg) { if (-not $Quiet) { Write-Host $msg -ForegroundColor Cyan } }
function Write-Warn($msg) { if (-not $Quiet) { Write-Host $msg -ForegroundColor Yellow } }
function Write-Err($msg)  { Write-Host $msg -ForegroundColor Red }

Write-Info "Opening SSH tunnel localhost:$LocalPort -> $PiHost:$RemotePort ..."

# Check if something already listens on LocalPort
$inUse = (Get-NetTCPConnection -State Listen -LocalPort $LocalPort -ErrorAction SilentlyContinue)
if ($inUse) {
    Write-Warn "Port $LocalPort is already in use locally. Use -LocalPort to pick a free port (e.g. 8888)."
}

# Start SSH tunnel in a detached window so it stays up
$sshArgs = "-N -L $LocalPort`:127.0.0.1:$RemotePort $PiUser@$PiHost"
try {
    $proc = Start-Process -FilePath "ssh" -ArgumentList $sshArgs -WindowStyle Hidden -PassThru
    Start-Sleep -Milliseconds 300
} catch {
    Write-Err "Failed to start ssh. Ensure OpenSSH Client is installed and 'ssh' is in PATH."
    exit 1
}

# Wait for the local port to accept connections (up to ~5s)
$ok = $false
for ($i=0; $i -lt 10; $i++) {
    try {
        $res = Test-NetConnection -ComputerName 127.0.0.1 -Port $LocalPort -WarningAction SilentlyContinue
        if ($res.TcpTestSucceeded) { $ok = $true; break }
    } catch {}
    Start-Sleep -Milliseconds 500
}

if (-not $ok) {
    Write-Warn "Tunnel may not be ready yet. Continuing anyway..."
}

Write-Info "Launching http://localhost:$LocalPort/debug/view"
Start-Process "http://localhost:$LocalPort/debug/view"

Write-Info "Tip: keep this PowerShell window open to keep the tunnel alive. To stop it, close this window or terminate the 'ssh' process."