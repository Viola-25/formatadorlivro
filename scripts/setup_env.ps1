<#
Script de configuração para Windows PowerShell:
- Cria uma virtualenv em .venv (se não existir)
- Instala dependências de requirements.txt na venv
- Mostra instruções rápidas para ativar a venv e executar o app
#>
param(
    [string]$VenvPath = ".venv",
    [string]$Requirements = "requirements.txt"
)

Write-Host "== Setup do Ambiente (PowerShell) ==" -ForegroundColor Cyan

if (-Not (Test-Path $VenvPath)) {
    Write-Host "Criando virtualenv em '$VenvPath'..." -ForegroundColor Yellow
    python -m venv $VenvPath
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Falha ao criar virtualenv. Verifique se o Python está no PATH."; exit 1
    }
} else {
    Write-Host "Virtualenv já existe em '$VenvPath'." -ForegroundColor Green
}

$pythonExe = Join-Path $VenvPath "Scripts\python.exe"
if (-Not (Test-Path $pythonExe)) {
    Write-Error "Executável Python não encontrado em $pythonExe. Verifique a virtualenv."; exit 1
}

Write-Host "Instalando dependências de '$Requirements'..." -ForegroundColor Yellow
& $pythonExe -m pip install --upgrade pip
& $pythonExe -m pip install -r $Requirements
if ($LASTEXITCODE -ne 0) {
    Write-Error "Falha ao instalar dependências. Verifique a saída acima."; exit 1
}

Write-Host "Dependências instaladas com sucesso." -ForegroundColor Green
Write-Host "Para ativar a venv (PowerShell):" -ForegroundColor Cyan
Write-Host "  .\$VenvPath\Scripts\Activate.ps1" -ForegroundColor White
Write-Host "Em seguida, execute o app:" -ForegroundColor Cyan
Write-Host "  streamlit run app.py" -ForegroundColor White
Write-Host "Se preferir rodar sem ativar, use:" -ForegroundColor Cyan
Write-Host "  .\$VenvPath\Scripts\python -m streamlit run app.py" -ForegroundColor White
