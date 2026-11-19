# Load before development commands; all task-created caches and temporary files stay in the workspace.
$TerraLocalRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$env:UV_CACHE_DIR = Join-Path $TerraLocalRoot '.cache\uv'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $TerraLocalRoot 'tools\local\python'
$env:PYINSTALLER_CONFIG_DIR = Join-Path $TerraLocalRoot '.cache\pyinstaller'
$env:JADX_CONFIG_DIR = Join-Path $TerraLocalRoot '.cache\jadx\config'
$env:JADX_CACHE_DIR = Join-Path $TerraLocalRoot '.cache\jadx\cache'
$env:PYTEST_ADDOPTS = '--basetemp="' + (Join-Path $TerraLocalRoot '.cache\pytest-tmp').Replace('\', '/') + '"'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:TMP = Join-Path $TerraLocalRoot '.cache\tmp'
$env:TEMP = $env:TMP
$env:TMPDIR = $env:TMP
$env:PYTHONPYCACHEPREFIX = Join-Path $TerraLocalRoot '.cache\pycache'
$env:PIP_CACHE_DIR = Join-Path $TerraLocalRoot '.cache\pip'
foreach ($TerraLocalDirectory in @($env:UV_PYTHON_INSTALL_DIR, $env:PYINSTALLER_CONFIG_DIR,
    $env:JADX_CONFIG_DIR, $env:JADX_CACHE_DIR, $env:TEMP, $env:PYTHONPYCACHEPREFIX, $env:PIP_CACHE_DIR)) {
    New-Item -ItemType Directory -Force -Path $TerraLocalDirectory | Out-Null
}
