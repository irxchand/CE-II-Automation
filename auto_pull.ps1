while ($true) {
    Write-Host "Checking for updates on GitHub..."
    git pull
    Start-Sleep -Seconds 60
}
