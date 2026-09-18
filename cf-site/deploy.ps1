param()

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
npx --yes wrangler deploy
