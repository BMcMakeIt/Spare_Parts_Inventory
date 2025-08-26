param(
  [string]$InitSqlPath = "db\init.sql",
  [string]$IndexesSqlPath = "db\20_indexes.sql"
)

$ErrorActionPreference = "Stop"

function Invoke-PsqlFile([string]$path) {
  if (-not (Test-Path $path)) {
    Write-Host "Skipping: $path (not found)"
    return
  }
  Write-Host "Applying $path ..."
  Get-Content -Raw $path | docker compose exec -T db psql -U inv -d inventory -v ON_ERROR_STOP=1 -f -
}

Write-Host "== Checking containers =="
docker compose ps

Write-Host "`n== Current tables =="
docker compose exec db psql -U inv -d inventory -c "\dt" | Out-Host

Invoke-PsqlFile $InitSqlPath
Invoke-PsqlFile $IndexesSqlPath

Write-Host "`n== Tables after apply =="
docker compose exec db psql -U inv -d inventory -c "\dt" | Out-Host

Write-Host "`nDone."
