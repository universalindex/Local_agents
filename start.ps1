# start.ps1

Write-Host "=== Starting Infrastructure ===" -ForegroundColor Cyan
# 1. Boot up your Docker containers (e.g., SearXNG, Open WebUI) in detached mode
docker compose up -d

Write-Host "=== Waiting for Containers ===" -ForegroundColor Cyan
# 2. Give the containers a few seconds to expose their ports
Start-Sleep -Seconds 3

Write-Host "=== Starting AI Middleware ===" -ForegroundColor Cyan
# 3. Activate your environment and start the Python server
# Notice we don't detach this one, so your terminal still sees all the FastAPI logs
conda run -n local_agents python core_backend/main.py

# 4. Cleanup (This only runs AFTER you press Ctrl+C to kill the Python server)
Write-Host "=== Shutting Down Infrastructure ===" -ForegroundColor Yellow
docker compose down