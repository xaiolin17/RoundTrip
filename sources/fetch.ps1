param([string]$ListFile, [string]$OutDir = "D:\RoundTrip\sources")
$ProgressPreference = 'SilentlyContinue'
$ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$lines = Get-Content $ListFile | Where-Object { $_ -match '\S' -and $_ -notmatch '^\s*#' }
foreach ($line in $lines) {
  $parts = $line -split '\s*\|\s*', 2
  $name = $parts[0].Trim()
  $url  = $parts[1].Trim()
  $out  = Join-Path $OutDir $name
  if (Test-Path $out) { Write-Output "SKIP $name (exists)"; continue }
  try {
    $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 90 -UserAgent $ua `
         -Headers @{ "Accept" = "text/html,application/xhtml+xml,application/pdf,*/*"; "Accept-Language" = "en-GB,en;q=0.9" } -ErrorAction Stop
    $bytes = [System.Text.Encoding]::Default.GetBytes([string]$r.Content)
    if ($r.Content -is [byte[]]) { $bytes = $r.Content }
    [System.IO.File]::WriteAllBytes($out, $bytes)
    Write-Output ("OK   {0,-34} {1,9} bytes  {2}" -f $name, $bytes.Length, $r.Headers['Content-Type'])
  } catch {
    Write-Output ("FAIL {0,-34} {1}" -f $name, $_.Exception.Message)
  }
  Start-Sleep -Milliseconds 400
}
