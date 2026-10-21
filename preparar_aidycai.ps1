$ErrorActionPreference = "Stop"

try {
    $repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
    $venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
    $pythonCommand = $null
    $pythonPrefix = @()

    $candidates = @()
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        $candidates += [PSCustomObject]@{ Command = $pyLauncher.Source; Prefix = @("-3") }
    }
    $pythonLauncher = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonLauncher) {
        $candidates += [PSCustomObject]@{ Command = $pythonLauncher.Source; Prefix = @() }
    }

    foreach ($candidate in $candidates) {
        $prefix = $candidate.Prefix
        & $candidate.Command @prefix -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            $pythonCommand = $candidate.Command
            $pythonPrefix = $candidate.Prefix
            break
        }
    }
    if (-not $pythonCommand) {
        throw "Se requiere Python 3.12 o posterior. Instala Python y vuelve a ejecutar este archivo."
    }

    if (-not (Test-Path -LiteralPath $venvPython)) {
        Write-Host "Creando el entorno virtual..."
        & $pythonCommand @pythonPrefix -m venv (Join-Path $repoRoot ".venv")
        if ($LASTEXITCODE -ne 0) { throw "No se pudo crear el entorno virtual." }
    }

    Write-Host "Instalando AIDYCAI y sus dependencias gráficas..."
    & $venvPython -m pip install -e "$($repoRoot)[gui]"
    if ($LASTEXITCODE -ne 0) { throw "Falló la instalación de dependencias." }

    $iconSource = Join-Path $repoRoot "assets\aidycai.ico"
    if (-not (Test-Path -LiteralPath $iconSource)) {
        throw "No se encontró el logo de AIDYCAI: $iconSource"
    }
    $dataRoot = Join-Path $env:LOCALAPPDATA "AIDYCAI"
    New-Item -ItemType Directory -Path $dataRoot -Force | Out-Null
    $iconPath = Join-Path $dataRoot "aidycai.ico"
    Copy-Item -LiteralPath $iconSource -Destination $iconPath -Force

    $desktop = [Environment]::GetFolderPath("Desktop")
    $shortcutPath = Join-Path $desktop "AIDYCAI.lnk"
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = Join-Path $repoRoot "AIDYCAI.bat"
    $shortcut.WorkingDirectory = $repoRoot
    $shortcut.IconLocation = "$iconPath,0"
    $shortcut.Description = "Abrir AIDYCAI"
    $shortcut.Save()

    Write-Host ""
    Write-Host "Listo. AIDYCAI quedó instalado y el acceso directo está en el Escritorio." -ForegroundColor Green
}
catch {
    Write-Host "Error: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
