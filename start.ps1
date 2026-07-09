# start.ps1

# Track whether Docker was already up before we launched this environment
$DockerWasRunning = $false

try {
    Write-Host "=== Verifying Docker Daemon ===" -ForegroundColor Cyan
    $DockerStatus = docker desktop status 2>$null
    
    if ($DockerStatus -eq "running") {
        Write-Host "Docker Desktop was already running. Will preserve environment on exit." -ForegroundColor Green
        $DockerWasRunning = $true
    } else {
        Write-Host "Docker is stopped. Booting Docker Engine..." -ForegroundColor Yellow
        docker desktop start
        
        # Poll the socket interface until it establishes a connection
        while ((docker desktop status 2>$null) -ne "running") {
            Write-Host "Waiting for Docker daemon to initialize..." -ForegroundColor DarkGray
            Start-Sleep -Seconds 3
        }
        Write-Host "Docker Engine Active." -ForegroundColor Green
    }

    Write-Host "=== Starting Infrastructure ===" -ForegroundColor Cyan
    docker compose up -d

    Write-Host "=== Waiting for Containers ===" -ForegroundColor Cyan
    Start-Sleep -Seconds 5

    Write-Host "=== Starting AI Middleware ===" -ForegroundColor Cyan
    conda run -n local_agents --no-capture-output python -u main.py
}
finally {
    Write-Host "=== Shutting Down Infrastructure ===" -ForegroundColor Yellow
    docker compose down
    
    # Only tear down the engine if this specific script instance spun it up
    if (-not $DockerWasRunning) {
        Write-Host "=== Stopping Docker Desktop Backend ===" -ForegroundColor Yellow
        docker desktop stop --force
        
        Write-Host "=== Reclaiming Virtualization Memory ===" -ForegroundColor Yellow
        wsl --shutdown
    } else {
        Write-Host "=== Preserving Background Docker & WSL Engine ===" -ForegroundColor Green
    }
}