"""Instalações sintéticas, sem contas, providers ou pastas reais do usuário."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0,str(RAIZ))
import atualizar_instalacao as a
import instalar


class Atualizacao(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='office upgrade ');self.addCleanup(self.temp.cleanup)
        self.raiz=Path(self.temp.name);self.origem=self.raiz/'pacote novo';self.origem.mkdir()
        for nome in instalar.PACOTE:
            p=self.origem/nome;p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(RAIZ/nome,p)
        self.app=self.raiz/'app com espaços';self.cfg={'porta':64531,'projetos':[],'titulo':'teste'}

    def instalar(self):return a.aplicar(a.preparar(self.app,self.origem,config=self.cfg))
    def upgrade(self):
        (self.origem/'VERSION').write_text('2.0.0-dev.7\n')
        return a.preparar(self.app,self.origem)

    def test_previa_limpa_instala_repete(self):
        plano=a.preparar(self.app,self.origem,config=self.cfg)
        self.assertFalse(self.app.exists());self.assertEqual(len(list(self.raiz.iterdir())),1)
        self.assertTrue(a.aplicar(plano)['alterado'])
        self.assertEqual(a.json_ler(self.app/'config.json')['porta'],self.cfg['porta'])
        antes=a.inventario(self.app)
        self.assertFalse(a.aplicar(a.preparar(self.app,self.origem))['alterado'])
        self.assertEqual(antes,a.inventario(self.app))

    def test_upgrade_preserva_tudo_e_reverte(self):
        self.instalar()
        for nome in ('dados/banco.db','dados/entregas/arte.png','.office/projeto.json','skills/minha.md','.claude/settings.json','NOTAS.md','privado.txt'):
            p=self.app/nome;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'privado\x00teste')
        cfg=self.app/'config.json';c=a.json_ler(cfg);c['personalizado']={'qualquer':True};cfg.write_text(json.dumps(c))
        (self.app/'.venv/bin').mkdir(parents=True);(self.app/'.venv/bin/python').symlink_to(sys.executable)
        (self.app/'privado.txt').chmod(0o600);self.app.chmod(0o700)
        antes=a.inventario(self.app);r=a.aplicar(self.upgrade())
        self.assertEqual(a.inventario(Path(r['backup'])),antes)
        depois=a.inventario(self.app)
        for n,v in antes.items():
            if n not in instalar.PACOTE and n!=a.MANIFESTO:self.assertEqual(depois[n],v)
        self.assertEqual(Path(r['recibo']).stat().st_mode & 0o777,0o600)
        a.reverter(r['recibo']);result=a.reverter(r['recibo'],True)
        self.assertEqual(a.inventario(self.app),antes);self.assertTrue(Path(result['preservado']).is_dir())

    def test_dev5_sem_manifesto_baseline_e_atalhos(self):
        self.instalar();(self.app/a.MANIFESTO).unlink()
        anterior=self.raiz/'dev5';shutil.copytree(self.origem,anterior)
        for p in (anterior,self.app):(p/'VERSION').write_text('2.0.0-dev.5\n')
        instalar.escrever_atalhos(self.app)
        with self.assertRaises(ValueError):a.preparar(self.app,self.origem)
        r=a.aplicar(a.preparar(self.app,self.origem,anterior))
        self.assertTrue(r['alterado']);self.assertEqual((self.app/'VERSION').read_bytes(),(self.origem/'VERSION').read_bytes())

    def test_personalizacao_pacote_incompleto_manifesto_privado(self):
        self.instalar();(self.app/'servidor.py').write_text('# meu servidor\n');antes=a.inventario(self.app)
        with self.assertRaises(ValueError):self.upgrade()
        self.assertEqual(a.inventario(self.app),antes)
        arq=self.origem/'instalar.py';arq.write_text(arq.read_text().replace('PACOTE = [','PACOTE = ["CONFIG.JSON",'))
        (self.origem/'CONFIG.JSON').write_text('{}')
        with self.assertRaises(ValueError):a.preparar(self.raiz/'novo',self.origem,config=self.cfg)
        (self.origem/'index.html').unlink()
        with self.assertRaises(ValueError):a.preparar(self.raiz/'novo',self.origem,config=self.cfg)

    def test_falhas_renomeacao_preservam_original(self):
        self.instalar()
        for falha in (1,2):
            plano=self.upgrade();antes=a.inventario(self.app);rename=os.rename;contador=[0]
            def falhar(x,y):
                contador[0]+=1
                if contador[0]==falha:raise OSError('falha sintética')
                return rename(x,y)
            with patch.object(a.os,'rename',side_effect=falhar):
                with self.assertRaises(OSError):a.aplicar(plano)
            self.assertEqual(a.inventario(self.app),antes)

    def test_recuperar_interrupcao_entre_renomeacoes(self):
        self.instalar();plano=self.upgrade();antes=a.inventario(self.app);rename=os.rename;contador=[0]
        def falhar(x,y):
            contador[0]+=1
            if contador[0]>=2:raise OSError('interrupção sintética')
            return rename(x,y)
        with patch.object(a.os,'rename',side_effect=falhar):
            with self.assertRaises(OSError):a.aplicar(plano)
        self.assertFalse(self.app.exists());recibo=next(p for p in self.raiz.glob('*.backup-*.json') if Path(a.json_ler(p)['backup']).is_dir())
        self.assertTrue(a.reverter(recibo)['recuperacao_interrompida'])
        a.reverter(recibo,True);self.assertEqual(a.inventario(self.app),antes)

    def test_interrupcao_real_mantem_backup_e_lock(self):
        self.instalar();self.upgrade();antes=a.inventario(self.app)
        codigo = """import os, sys
from pathlib import Path
import atualizar_instalacao as a
p=a.preparar(Path(sys.argv[1]),Path(sys.argv[2]))
rename=os.rename
def parar(x,y):
    rename(x,y)
    os._exit(97)
a.os.rename=parar
a.aplicar(p)
"""
        r=subprocess.run([sys.executable,'-c',codigo,str(self.app),str(self.origem)],cwd=RAIZ)
        self.assertEqual(r.returncode,97);self.assertFalse(self.app.exists())
        recibo=next(p for p in self.raiz.glob('*.backup-*.json') if Path(a.json_ler(p)['backup']).is_dir())
        with self.assertRaises(FileExistsError):a.reverter(recibo,True)
        # O processo sintético terminou; a recuperação exige essa conferência.
        (self.raiz/('.'+self.app.name+'.atualizacao.lock')).unlink()
        a.reverter(recibo,True);self.assertEqual(a.inventario(self.app),antes)

    def test_baseline_nao_pode_ser_instalacao(self):
        self.instalar();(self.app/a.MANIFESTO).unlink()
        with self.assertRaises(ValueError):a.preparar(self.app,self.origem,self.app)

    def test_reversao_recusa_trabalho_novo(self):
        self.instalar();r=a.aplicar(self.upgrade());(self.app/'novo-trabalho.txt').write_text('não perder');antes=a.inventario(self.app)
        with self.assertRaises(ValueError):a.reverter(r['recibo'],True)
        self.assertEqual(antes,a.inventario(self.app));self.assertTrue(Path(r['backup']).is_dir())

    def test_mudanca_apos_previa_e_copia_corrompida(self):
        self.instalar();plano=self.upgrade();(self.app/'dados/novo').write_text('alterado')
        with self.assertRaises(ValueError):a.aplicar(plano)
        plano=self.upgrade();original=a.shutil.copytree
        def corromper(src,dst,*args,**kw):
            r=original(src,dst,*args,**kw)
            if Path(src)==self.app:(Path(dst)/'dados/novo').write_text('corrompido')
            return r
        with patch.object(a.shutil,'copytree',side_effect=corromper):
            with self.assertRaises(ValueError):a.aplicar(plano)
        self.assertEqual((self.app/'dados/novo').read_text(),'alterado')

    def test_porta_ocupada_locks_links_hardlinks(self):
        self.instalar()
        with socket.socket() as s:
            s.bind(('127.0.0.1',self.cfg['porta']));s.listen()
            with self.assertRaises(ValueError):self.upgrade()
        lock=self.raiz/('.'+self.app.name+'.atualizacao.lock');lock.write_text('outro')
        with self.assertRaises(FileExistsError):a.aplicar(self.upgrade())
        self.assertEqual(lock.read_text(),'outro');lock.unlink()
        link=self.raiz/'link';link.symlink_to(self.app,target_is_directory=True)
        with self.assertRaises(ValueError):a.preparar(link,self.origem)
        os.link(self.app/'config.json',self.app/'hardlink')
        with self.assertRaises(ValueError):self.upgrade()

    def test_fonte_incompleta_bloqueada(self):
        arq=self.origem/'instalar.py'
        arq.write_text(arq.read_text().replace('"index.html", ', '', 1))
        with self.assertRaises(ValueError):a.preparar(self.app,self.origem,config=self.cfg)
        self.assertFalse(self.app.exists())

    def test_metadados_sem_permissao_e_plataforma_bloqueiam(self):
        self.instalar();plano=self.upgrade();antes=a.inventario(self.app)
        with patch.object(a.os,'listxattr',side_effect=PermissionError('não inspecionável')):
            with self.assertRaises(PermissionError):a.aplicar(plano)
        with patch.object(a.os,'listxattr',return_value=['system.posix_acl_access']):
            with self.assertRaises(ValueError):a.aplicar(plano)
        with patch.object(a.os,'geteuid',return_value=-1):
            with self.assertRaises(ValueError):a.aplicar(plano)
        with patch.object(a.os,'getegid',return_value=-1):
            with self.assertRaises(ValueError):a.aplicar(plano)
        with patch.object(a.sys,'platform','darwin'):
            with self.assertRaises(ValueError):a.aplicar(plano)
        self.assertEqual(a.inventario(self.app),antes)

    def test_copia_falha_espaco_e_mudanca_fonte(self):
        self.instalar();plano=self.upgrade();antes=a.inventario(self.app)
        with patch.object(a.shutil,'copytree',side_effect=OSError('disco')):
            with self.assertRaises(OSError):a.aplicar(plano)
        from types import SimpleNamespace
        with patch.object(a.shutil,'disk_usage',return_value=SimpleNamespace(free=0)):
            with self.assertRaises(ValueError):a.aplicar(plano)
        (self.origem/'servidor.py').write_text('# mudou após prévia\n')
        with self.assertRaises(ValueError):a.aplicar(plano)
        self.assertEqual(a.inventario(self.app),antes)

    def test_novo_caminho_colide_com_arquivo_pessoal(self):
        self.instalar();(self.app/a.MANIFESTO).unlink()
        anterior=self.raiz/'anterior';shutil.copytree(self.origem,anterior)
        for p in (anterior,self.app):
            arq=p/'instalar.py';arq.write_text(arq.read_text().replace('"docs/ATUALIZACAO.md", ', '', 1))
        (anterior/'docs/ATUALIZACAO.md').unlink()
        (self.app/'docs/ATUALIZACAO.md').write_text('manual pessoal')
        with self.assertRaises(ValueError):a.preparar(self.app,self.origem,anterior)
        self.assertEqual((self.app/'docs/ATUALIZACAO.md').read_text(),'manual pessoal')

    def test_cli_previa_omite_config_privado(self):
        self.instalar();cfg=self.app/'config.json';c=a.json_ler(cfg);c['sentinela']='PRIVADO-NAO-IMPRIMIR';cfg.write_text(json.dumps(c))
        antes=a.inventario(self.origem);destino_antes=a.inventario(self.app)
        r=subprocess.run([sys.executable,str(self.origem/'atualizar_instalacao.py'),'--destino',str(self.app)],capture_output=True,text=True)
        self.assertEqual(r.returncode,0,r.stderr);self.assertNotIn('PRIVADO-NAO-IMPRIMIR',r.stdout+r.stderr)
        self.assertEqual(a.inventario(self.origem),antes);self.assertEqual(a.inventario(self.app),destino_antes)


if __name__=='__main__':unittest.main()
