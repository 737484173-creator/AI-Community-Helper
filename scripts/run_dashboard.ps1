$ErrorActionPreference = "Stop"
$Port = if ($args.Count -ge 1) { $args[0] } else { "8502" }
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PythonPath = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "Project Python environment not found. Create .venv and install requirements.txt first."
}
& $PythonPath manage.py dashboard --port $Port
