$ErrorActionPreference = "Stop"
$ReportType = if ($args.Count -ge 1) { $args[0] } else { "daily" }
python manage.py report $ReportType

