param(
    [string[]]$Consoles = @('claude'),
    [string]$PastaFerramentas = '',
    [switch]$Aplicar,
    [string]$Confirmacao = '',
    [switch]$Interativo
)

function Get-OfficeTool($Nome, $Raiz) {
    $relativos = @{python='python/python.exe';node='node/node.exe';git='git/cmd/git.exe';gh='gh/gh.exe';claude='claude/claude.exe';codex='npm/codex.cmd';gemini='npm/gemini.cmd';opencode='npm/opencode.cmd'}
    if ($Raiz -and $relativos.ContainsKey($Nome)) {
        $p = Join-Path $Raiz $relativos[$Nome]
        if (Test-Path -LiteralPath $p -PathType Leaf) {
            $verificar=$p
            while ($verificar -and $verificar -ne $Raiz) {
                if ((Get-Item -LiteralPath $verificar -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Ferramenta por link/juncao recusada.' }
                $verificar=Split-Path $verificar -Parent
            }
            return $p
        }
    }
    $cmd = Get-Command $Nome -CommandType Application,ExternalScript -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($cmd -and -not ($Nome -eq 'python' -and $cmd.Source -match '\\WindowsApps\\')) { return $cmd.Source }
    return $null
}

function Get-OfficeMachineState($Raiz) {
    $null = Get-OfficeMachinePlan @('claude') $Raiz @{}
    $s = @{}
    foreach ($n in @('python','node','git','gh','claude','codex','gemini','opencode','winget')) { $s[$n] = Get-OfficeTool $n $Raiz }
    foreach ($n in @('python','node')) {
        $s[$n+'Versao'] = $null
        if ($s[$n]) {
            $texto = & $s[$n] --version 2>$null
            if ($LASTEXITCODE -eq 0 -and "$texto" -match '(\d+\.\d+\.\d+)') { $s[$n+'Versao'] = $Matches[1] }
        }
    }
    $s['npmScript'] = $null
    if ($s.node) {
        $p = Join-Path (Split-Path $s.node) 'node_modules/npm/bin/npm-cli.js'
        if (Test-Path -LiteralPath $p -PathType Leaf) { $s.npmScript = $p }
    }
    return $s
}

function Get-OfficeMachinePlan($Selecionados, $Raiz, $Estado) {
    $nomes = @($Selecionados | Sort-Object -Unique)
    if ($nomes.Count -lt 1 -or $nomes.Count -gt 4 -or @($nomes | Where-Object { $_ -notin @('claude','codex','opencode','gemini') }).Count) { throw 'Selecione claude, codex, opencode ou gemini.' }
    if ($Raiz -notmatch '^[A-Za-z]:[\\/]' -or $Raiz -match '[\x00-\x1f";&|<>%]' ) { throw 'Escolha uma pasta absoluta em disco local, sem caracteres de comando.' }
    $raizCompleta = [IO.Path]::GetFullPath($Raiz)
    if ($raizCompleta.TrimEnd('\') -eq [IO.Path]::GetPathRoot($raizCompleta).TrimEnd('\')) { throw 'Nao use a raiz do disco.' }
    $p = $raizCompleta
    while ($p) {
        if (Test-Path -LiteralPath $p) {
            $item = Get-Item -LiteralPath $p -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or -not $item.PSIsContainer) { throw 'Pasta por link/juncao ou arquivo recusada.' }
        }
        $pai = Split-Path $p -Parent
        if ($pai -eq $p) { break }; $p = $pai
    }
    $passos = @(); $bloqueios = @()
    $ids = @{python='Python.Python.3.12';git='Git.Git';gh='GitHub.cli';node='OpenJS.NodeJS.LTS';claude='Anthropic.ClaudeCode'}
    $npm = @{codex='@openai/codex';gemini='@google/gemini-cli';opencode='opencode-ai'}
    $precisaNode = @($nomes | Where-Object { $_ -ne 'claude' }).Count -gt 0
    $necessarios = @('python','git','gh') + $(if ($precisaNode) { @('node') } else { @() }) + $nomes
    foreach ($n in $necessarios) {
        if ($Estado[$n]) {
            if ($n -in @('python','node')) {
                $minimo = $(if ($n -eq 'python') { [version]'3.9' } else { [version]'22.0' })
                if (-not $Estado[$n+'Versao'] -or [version]$Estado[$n+'Versao'] -lt $minimo) { $bloqueios += "$n existente sem versao minima comprovada; atualize pelos meios oficiais." }
            }
            continue
        }
        if ($ids.ContainsKey($n)) {
            $args = @('install','--exact','--id',$ids[$n],'--source','winget','--no-upgrade','--location',(Join-Path $raizCompleta $n))
            $passos += [pscustomobject]@{nome=$n;tipo='winget';pacote=$ids[$n];argumentos=$args}
        } else {
            $passos += [pscustomobject]@{nome=$n;tipo='npm';pacote=$npm[$n];argumentos=@('install','--global','--prefix',(Join-Path $raizCompleta 'npm'),$npm[$n])}
        }
    }
    if (@($passos | Where-Object tipo -eq 'winget').Count -and -not $Estado.winget) { $bloqueios += 'WinGet ausente. Instale o App Installer oficial da Microsoft.' }
    if (@($passos | Where-Object tipo -eq 'npm').Count -and $Estado.node -and -not $Estado.npmScript) { $bloqueios += 'npm da instalacao Node nao encontrado; confira Node.js oficial.' }
    $marker = Join-Path $raizCompleta 'office-maquina.json'
    if ($passos.Count -and (Test-Path -LiteralPath $raizCompleta)) {
        if (Test-Path -LiteralPath $marker -PathType Leaf) {
            if ((Get-Item -LiteralPath $marker -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Identidade por link recusada.' }
            if ((Get-Item -LiteralPath $marker).Length -gt 1024) { throw 'Identidade de ferramentas invalida.' }
            $edicao = Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json
            if ($edicao.edicao -ne 'office-maquina' -or $edicao.formato -ne 1 -or -not ($edicao.formato -is [int] -or $edicao.formato -is [long])) { throw 'Pasta pertence a outra instalacao.' }
        } elseif (@(Get-ChildItem -LiteralPath $raizCompleta -Force | Select-Object -First 1).Count) { throw 'Use uma pasta vazia ou ja preparada por este assistente.' }
    }
    $estadoOrdenado = [ordered]@{}
    foreach ($k in @($Estado.Keys | Sort-Object)) { $estadoOrdenado[$k]=$Estado[$k] }
    $material = [ordered]@{raiz=$raizCompleta;consoles=$nomes;passos=$passos;bloqueios=$bloqueios;estado=$estadoOrdenado} | ConvertTo-Json -Depth 8 -Compress
    $hash = [Security.Cryptography.SHA256]::Create()
    try { $id = ([BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($material)))).Replace('-','').ToLowerInvariant() } finally { $hash.Dispose() }
    return [pscustomobject]@{raiz=$raizCompleta;consoles=$nomes;passos=$passos;bloqueios=$bloqueios;confirmacao=$id}
}

function Invoke-OfficeMachineCommand($Executavel, $Argumentos) {
    & $Executavel @Argumentos
    if ($LASTEXITCODE -ne 0) { throw 'Instalador retornou falha. Preserve o que foi instalado e refaca a previa; nao houve rollback de software.' }
}

function Register-OfficeMachinePath($Estado, $Passos, $Raiz) {
    $dirs = @($Passos | ForEach-Object { Split-Path $Estado[$_.nome] } | Sort-Object -Unique)
    $antes = [Environment]::GetEnvironmentVariable('Path','User'); $novo=$antes
    foreach ($dir in $dirs) { if ($dir -and $dir -notin @($novo -split ';')) { $novo = $(if ($novo) { $novo+';' } else { '' })+$dir } }
    if ($novo -eq $antes) { return }
    if ($novo.Length -gt 30000) { throw 'PATH excede o limite do assistente; configure pelo Windows.' }
    $backup = Join-Path $Raiz ('path-anterior-'+[guid]::NewGuid().ToString('N')+'.json')
    @{anterior=$antes;novo=$novo} | ConvertTo-Json | Set-Content -LiteralPath $backup -Encoding UTF8
    if ([Environment]::GetEnvironmentVariable('Path','User') -ne $antes) { throw 'PATH foi alterado por outro processo; preserve a alteracao e refaca a previa.' }
    [Environment]::SetEnvironmentVariable('Path',$novo,'User')
}

function Invoke-OfficeMachinePlan($Plano, $Id) {
    $estado = Get-OfficeMachineState $Plano.raiz
    $atual = Get-OfficeMachinePlan $Plano.consoles $Plano.raiz $estado
    if ($Id -ne $atual.confirmacao) { throw 'Estado mudou; refaca a previa.' }
    if ($atual.bloqueios.Count) { throw ($atual.bloqueios -join ' ') }
    if (-not $atual.passos.Count) { return }
    New-Item -ItemType Directory -Path $atual.raiz -Force | Out-Null
    $marker = Join-Path $atual.raiz 'office-maquina.json'
    if (-not (Test-Path -LiteralPath $marker)) { @{edicao='office-maquina';formato=1} | ConvertTo-Json | Set-Content -LiteralPath $marker -Encoding UTF8 }
    $cache = Join-Path $atual.raiz 'cache/npm'; $temporario = Join-Path $atual.raiz 'tmp'
    New-Item -ItemType Directory -Path $cache,$temporario -Force | Out-Null
    $anterior = @{TMP=$env:TMP;TEMP=$env:TEMP;npm_config_cache=$env:npm_config_cache}
    try {
        $env:TMP=$temporario; $env:TEMP=$temporario; $env:npm_config_cache=$cache
        foreach ($passo in $atual.passos) {
            Write-Host ('Instalando: '+$passo.nome)
            if ($passo.tipo -eq 'winget') { Invoke-OfficeMachineCommand $estado.winget $passo.argumentos }
            else {
                $estado = Get-OfficeMachineState $atual.raiz
                if (-not $estado.node -or -not $estado.npmScript) { throw 'Node/npm ainda indisponiveis. Confira a instalacao e refaca a previa.' }
                Invoke-OfficeMachineCommand $estado.node (@($estado.npmScript)+$passo.argumentos)
            }
            # Rele o PATH que instaladores nativos podem ter registrado.
            $env:Path = [Environment]::GetEnvironmentVariable('Path','Machine')+';'+[Environment]::GetEnvironmentVariable('Path','User')
            $estado = Get-OfficeMachineState $atual.raiz
            if (-not $estado[$passo.nome]) { throw ('Componente nao encontrado apos instalar: '+$passo.nome+'. --location depende do pacote; confira a pasta e reabra o terminal.') }
            if ($passo.nome -in @('python','node')) {
                $minimo = $(if ($passo.nome -eq 'python') { [version]'3.9' } else { [version]'22.0' })
                if (-not $estado[$passo.nome+'Versao'] -or [version]$estado[$passo.nome+'Versao'] -lt $minimo) { throw 'Componente instalado sem versao minima comprovada; instalacao interrompida.' }
            }
        }
        Register-OfficeMachinePath $estado $atual.passos $atual.raiz
        Write-Host 'Ferramentas instaladas. Reabra o terminal antes de configurar o projeto.'
    } finally { $env:TMP=$anterior.TMP; $env:TEMP=$anterior.TEMP; $env:npm_config_cache=$anterior.npm_config_cache }
}

if ($MyInvocation.InvocationName -ne '.') {
    try {
        if ($env:OS -ne 'Windows_NT') { throw 'Preparacao automatica de maquina disponivel para Windows.' }
        $edicao = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'EDICAO.json') -Raw | ConvertFrom-Json
        if ($edicao.edicao -ne 'office-multi-provider' -or $edicao.formato -ne 1 -or -not ($edicao.formato -is [int] -or $edicao.formato -is [long])) { throw 'Use a nova edicao separada do escritorio.' }
        if ((Get-Content -LiteralPath (Join-Path $PSScriptRoot 'VERSION') -Raw).Trim() -notmatch '^2\.') { throw 'Versao do escritorio incompativel.' }
        if ($Interativo) {
            $entrada = Read-Host 'Consoles separados por virgula (claude,codex,opencode,gemini; vazio = claude)'
            if ($entrada) { $Consoles = @($entrada.Split(',') | ForEach-Object { $_.Trim().ToLowerInvariant() }) }
            if (-not $PastaFerramentas) { $PastaFerramentas = Read-Host 'Pasta vazia de ferramentas (exemplo D:\OfficeTools)' }
        }
        $estado = Get-OfficeMachineState $PastaFerramentas
        $plano = Get-OfficeMachinePlan $Consoles $PastaFerramentas $estado
        Write-Host ('Pasta de ferramentas: '+$plano.raiz)
        foreach ($p in $plano.passos) { Write-Host ($p.nome+' via '+$p.tipo+': '+$p.pacote) }
        foreach ($p in $plano.bloqueios) { Write-Host ('Pendente: '+$p) }
        Write-Host 'Apenas ferramentas ausentes; nao atualiza consoles existentes, autentica contas, baixa modelos ou inicia agentes.'
        Write-Host 'Aplicar permite instalacao dos pacotes acima, cache/tmp nesta pasta e registro dos novos caminhos no PATH do usuario (backup local).'
        Write-Host 'WinGet pode pedir aceite/elevacao; local de instalacao depende do pacote. Nao altera politicas de seguranca do Windows.'
        if ($Interativo -and -not $plano.bloqueios.Count -and $plano.passos.Count) {
            if ((Read-Host 'Instalar estes componentes? Digite SIM') -eq 'SIM') { $Aplicar=$true; $Confirmacao=$plano.confirmacao }
        }
        if ($Aplicar) { Invoke-OfficeMachinePlan $plano $Confirmacao }
        else { Write-Host ('Previa apenas. Para aplicar pelo terminal, use -Aplicar -Confirmacao '+$plano.confirmacao) }
        Write-Host 'Depois: python iniciar_projeto.py --projeto CAMINHO --destino PASTA_DO_ESCRITORIO; confira a previa e aplique.'
        Write-Host 'Login e modelos sao configurados no console escolhido. Instalacao nao comprova autenticacao, modelo free, cotas ou paridade Team.'
    } catch { Write-Error $_; exit 2 }
}
