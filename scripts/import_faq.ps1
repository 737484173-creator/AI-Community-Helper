$ErrorActionPreference = "Stop"
$ExcelPath = if ($args.Count -ge 1) { $args[0] } else { "C:/Users/Administrator/Desktop/SDK.xlsx" }
python manage.py import-faq $ExcelPath

