python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
Write-Host "Installed AgentForge into .venv. Run: .\.venv\Scripts\Activate.ps1 && agentforge --help"
