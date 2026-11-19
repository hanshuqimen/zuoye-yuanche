param([switch]$Clean)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'env.ps1')
Set-Location -LiteralPath $TerraLocalRoot
$TerraLocalPython = Join-Path $TerraLocalRoot '.venv\Scripts\python.exe'
$TerraLocalArguments = @('-m', 'tools.build_release')
if ($Clean) { $TerraLocalArguments += '--clean' }
& $TerraLocalPython @TerraLocalArguments
if ($LASTEXITCODE -ne 0) { throw 'Isolated release build failed; previous installations were preserved' }
