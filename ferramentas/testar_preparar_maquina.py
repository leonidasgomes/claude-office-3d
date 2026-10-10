"""PowerShell real com instaladores simulados; não modifica software/PATH/contas."""
from pathlib import Path
import json,os,shutil,subprocess,sys,tempfile,unittest
R=Path(__file__).resolve().parent.parent
PS=shutil.which('powershell.exe') if os.name=='nt' else shutil.which('pwsh')
FIXTURE=r'''
param($Fonte,$Dados)
$ErrorActionPreference='Stop'
. $Fonte
$d=Get-Content -LiteralPath $Dados -Raw | ConvertFrom-Json
$s=@{};foreach($p in $d.estado.PSObject.Properties){$s[$p.Name]=$p.Value}
$raiz=Join-Path (Split-Path $Dados) 'tools'
$comandos=@();$registrados=0
function Get-OfficeMachineState($Raiz) { return $s }
function Invoke-OfficeMachineCommand($exe,$argumentos) {
    $script:comandos+=@{exe=$exe;args=$argumentos}
    if($d.falhar){throw 'falha simulada'}
    $pacote=$argumentos[-1]
    $nome=switch($pacote){'@openai/codex'{'codex'};'@google/gemini-cli'{'gemini'};'opencode-ai'{'opencode'};default{$null}}
    if(-not $nome){$nome=$argumentos[-1].Split([IO.Path]::DirectorySeparatorChar)[-1]}
    $s[$nome]=Join-Path $raiz ($nome+'/programa.exe')
    if($nome -eq 'python'){$s.pythonVersao='3.12.10'}
    if($nome -eq 'node'){$s.nodeVersao='24.14.1';$s.npmScript=Join-Path $raiz 'node/npm-cli.js'}
}
function Register-OfficeMachinePath($estado,$passos,$raiz){$script:registrados++}
try{
    if($d.ocupado){New-Item -ItemType Directory -Path $raiz|Out-Null;Set-Content -LiteralPath (Join-Path $raiz 'nao-tocar.txt') -Value 'original'}
    $selecionados=@($d.consoles)
    $p=Get-OfficeMachinePlan $selecionados $raiz $s
    $hash=$p.confirmacao
    if($d.ordem){$s2=@{};foreach($k in @($s.Keys|Sort-Object -Descending)){$s2[$k]=$s[$k]};if((Get-OfficeMachinePlan $selecionados $raiz $s2).confirmacao -ne $hash){throw 'hash instavel'}}
    if($d.mudar){$s.git='outro'}
    if($d.aplicar){Invoke-OfficeMachinePlan $p $hash}
    @{ok=$true;passos=@($p.passos);bloqueios=@($p.bloqueios);comandos=@($comandos);registrados=$registrados;criou=(Test-Path -LiteralPath $raiz)}|ConvertTo-Json -Depth 10 -Compress|Write-Output
}catch{
    @{ok=$false;erro=$_.Exception.Message;comandos=@($comandos);registrados=$registrados;criou=(Test-Path -LiteralPath $raiz)}|ConvertTo-Json -Depth 10 -Compress|Write-Output
}
'''

@unittest.skipUnless(os.name=='nt' and PS,'Teste de preparação requer PowerShell nativo do Windows')
class Preparar(unittest.TestCase):
    def rodar(self,**dados):
        with tempfile.TemporaryDirectory(dir=R/'ferramentas') as tmp:
            p=Path(tmp);f=p/'fixture.ps1';f.write_text(FIXTURE,encoding='utf-8-sig')
            d=p/'dados.json';d.write_text(json.dumps(dados),encoding='utf-8')
            res=subprocess.run([PS,'-NoProfile','-File',str(f),str(R/'preparar_maquina.ps1'),str(d)],capture_output=True,timeout=30)
            self.assertEqual(res.returncode,0,res.stderr.decode(errors='replace'))
            # Windows PowerShell escreve stdout com a página OEM deste PC; o JSON
            # de prova usa nomes/mensagens ASCII, sem dados de conta.
            return json.loads(res.stdout.decode(errors='replace').splitlines()[-1])
    def pronto(self):
        return dict(python='python',pythonVersao='3.12.10',node='node',nodeVersao='24.14.1',npmScript='npm-cli.js',git='git',gh='gh',winget='winget',claude='claude',codex='codex',gemini='gemini',opencode='opencode')
    def test_maquina_pronta_nao_instala_nao_cria_pasta_e_hash_independe_da_ordem(self):
        r=self.rodar(estado=self.pronto(),consoles=['claude','codex','gemini','opencode'],aplicar=True,ordem=True)
        self.assertTrue(r['ok']);self.assertFalse(r['criou']);self.assertEqual(r['comandos'],[]);self.assertEqual(r['registrados'],0)
    def test_previa_sem_python_planeja_dependencias_e_apenas_consoles_escolhidos(self):
        r=self.rodar(estado={'winget':'winget'},consoles=['codex','opencode'])
        self.assertTrue(r['ok']);self.assertFalse(r['criou']);self.assertEqual(r['comandos'],[])
        self.assertEqual([p['nome'] for p in r['passos']],['python','git','gh','node','codex','opencode'])
        self.assertEqual([p['pacote'] for p in r['passos']][-2:],['@openai/codex','opencode-ai'])
    def test_instalacao_simulada_ordena_dependencias_e_persiste_so_apos_sucesso(self):
        r=self.rodar(estado={'winget':'winget'},consoles=['gemini','codex'],aplicar=True)
        self.assertTrue(r['ok'],r);self.assertTrue(r['criou']);self.assertEqual(len(r['comandos']),6);self.assertEqual(r['registrados'],1)
        self.assertIn('--no-upgrade',r['comandos'][0]['args']);self.assertEqual(r['comandos'][-1]['args'][-1],'@google/gemini-cli')
        self.assertNotIn('login',json.dumps(r['comandos']));self.assertNotIn('--ignore-security-hash',json.dumps(r['comandos']))
    def test_falha_interrompe_sem_instalar_outros_e_sem_registrar_path(self):
        r=self.rodar(estado={'winget':'winget'},consoles=['claude'],aplicar=True,falhar=True)
        self.assertFalse(r['ok']);self.assertEqual(len(r['comandos']),1);self.assertEqual(r['registrados'],0)
    def test_estado_alterado_impede_qualquer_instalacao(self):
        r=self.rodar(estado={'winget':'winget'},consoles=['codex'],aplicar=True,mudar=True)
        self.assertFalse(r['ok']);self.assertEqual(r['comandos'],[]);self.assertFalse(r['criou'])
    def test_pasta_ocupada_preservada(self):
        r=self.rodar(estado={'winget':'winget'},consoles=['claude'],aplicar=True,ocupado=True)
        self.assertFalse(r['ok']);self.assertEqual(r['comandos'],[]);self.assertEqual(r['registrados'],0)
    def test_gerenciador_ausente_ou_versao_antiga_bloqueiam(self):
        for estado in ({},{**self.pronto(),'nodeVersao':'18.0.0','codex':None}):
            r=self.rodar(estado=estado,consoles=['codex'],aplicar=True)
            self.assertFalse(r['ok']);self.assertEqual(r['comandos'],[]);self.assertFalse(r['criou'])
    def test_selecao_invalida_nao_executa(self):
        r=self.rodar(estado=self.pronto(),consoles=['falso;comando'],aplicar=True)
        self.assertFalse(r['ok']);self.assertEqual(r['comandos'],[])

if __name__=='__main__':unittest.main()
