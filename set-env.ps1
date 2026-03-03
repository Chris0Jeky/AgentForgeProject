Get-Content .agentforge.env | ForEach-Object {
  if ($_ -match '^(\w+)=(.*)$') {
    [System.Environment]::SetEnvironmentVariable($matches[1], $matches[2])
  }
}
Write-Host "Loaded .agentforge.env into this process environment."
