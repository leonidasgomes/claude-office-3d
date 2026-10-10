"""Orçamento de modelos residentes, GPU e GET loopback; nenhuma inferência real."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import http.client
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import memoria_local as m
from gestao_projeto import validar
from recursos_local import verificar, reservar, vigiar, medir


def estado(memoria=0, video=0, gpu=None):
    return {'ram_livre_gb':16,'pesados':[],'cpu_uso_pct':10,
            'ollama':{'quantidade':1 if memoria else 0,'memoria_bytes':memoria,'vram_bytes':video},
            'gpu':gpu if gpu is not None else {'estado':'indisponivel','gpus':[]}}


def gpu(livre=3,uso=10):
    return {'estado':'medido','gpus':[{'indice':0,'total_bytes':8*2**30,
                                      'livre_bytes':livre*2**30,'uso_pct':uso}]}


class Memoria(unittest.TestCase):
    def setUp(self):self.cfg=validar({'local':{'ativo':True}})

    def test_politica_limites_e_local_desativado_por_padrao(self):
        self.assertFalse(validar({})['local']['ativo'])
        for chave,padrao in [('ollama_memoria_max_gb',4),('vram_livre_min_gb',2),('gpu_uso_max_pct',75)]:
            self.assertEqual(self.cfg['local'][chave],padrao)
            for valor in (None,True,0,-1,1.5,'4',1025):
                with self.subTest(chave=chave,valor=valor),self.assertRaises(ValueError):
                    validar({'local':{chave:valor}})

    def test_residentes_agregam_outros_clientes_sem_expor_identidades(self):
        dados={'models':[{'name':'privado','digest':'sigilo','size':2**30,'size_vram':2**29},
                         {'name':'outro cliente','size':2**30,'size_vram':0}]}
        self.assertEqual(m.residentes(dados),{'quantidade':2,'memoria_bytes':2**31,'vram_bytes':2**29})
        self.assertEqual(m.residentes({'models':[]}),{'quantidade':0,'memoria_bytes':0,'vram_bytes':0})
        for modelo in ({'size':True,'size_vram':0},{'size':1,'size_vram':2},{'size':0,'size_vram':0},
                       {'size':1},{'size':2,'size_vram':0,'remote_host':'cloud'},None):
            with self.subTest(modelo=modelo),self.assertRaises(OSError):m.residentes({'models':[modelo]})
        for invalido in ({}, {'models':[{}]*129}, {'models':None}):
            with self.assertRaises(OSError):m.residentes(invalido)

    def test_orcamento_residente_nao_desconta_ram_livre_duas_vezes(self):
        verificar(self.cfg,estado(4*2**30))
        with self.assertRaises(ValueError):verificar(self.cfg,estado(4*2**30+1))
        verificar(validar({'local':{'ativo':True,'ollama_memoria_max_gb':8}}),estado(7*2**30))
        for valor in (None,{}, {'quantidade':0,'memoria_bytes':1,'vram_bytes':0},
                      {'quantidade':1,'memoria_bytes':1,'vram_bytes':True}):
            d=estado();d['ollama']=valor
            with self.assertRaises(ValueError):verificar(self.cfg,d)

    def test_csv_gpu_nao_presume_na_ou_valores_inconsistentes(self):
        self.assertEqual(m.gpus_nvidia('0, 8192, 3072, 10\n')[0],gpu()['gpus'][0])
        for texto in ('','0,8192,N/A,0','0,8192,8193,0','0,8192,1000,101',
                      '0,8192,1000,-1','0,8192,1000,0\n0,8192,1000,0','0,8192,1000,0,extra'):
            with self.subTest(texto=texto),self.assertRaises(OSError):m.gpus_nvidia(texto)

    def test_comando_gpu_somente_leitura_timeout_e_erro_explicitado(self):
        with patch.object(m.shutil,'which',return_value='nvidia-smi'),patch.object(m.subprocess,'run',return_value=SimpleNamespace(stdout='0,8192,4096,0\n')) as run:
            self.assertEqual(m.medir_gpu()['estado'],'medido')
            self.assertEqual(run.call_args.args[0],['nvidia-smi','--query-gpu=index,memory.total,memory.free,utilization.gpu','--format=csv,noheader,nounits'])
            self.assertEqual(run.call_args.kwargs['timeout'],3)
        with patch.object(m.shutil,'which',return_value=None):self.assertEqual(m.medir_gpu()['estado'],'indisponivel')
        with patch.object(m.shutil,'which',return_value='nvidia-smi'),patch.object(m.subprocess,'run',side_effect=OSError):
            self.assertEqual(m.medir_gpu()['estado'],'erro')

    def test_gpu_ausente_so_admite_sem_vram_residente(self):
        verificar(self.cfg,estado())
        verificar(self.cfg,estado(2**30,0))
        for d in (estado(2**30,1),estado(gpu={'estado':'erro','gpus':[]}),estado(gpu={})):
            with self.assertRaises(ValueError):verificar(self.cfg,d)

    def test_gpu_limites_inclusivos_todas_as_placas_protegidas(self):
        verificar(self.cfg,estado(2**30,2**30,gpu(2,75)))
        for g in (gpu(1),gpu(3,76),gpu(3,True),gpu(9),{'estado':'medido','gpus':[]}):
            with self.assertRaises(ValueError):verificar(self.cfg,estado(gpu=g))
        g=gpu();g['gpus'].append(gpu(1)['gpus'][0])
        with self.assertRaises(ValueError):verificar(self.cfg,estado(gpu=g))

    def test_admissao_falha_antes_da_reserva_e_revalida_dentro_da_transacao(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'reserva.db'
            with self.assertRaises(ValueError):
                with reservar(db,self.cfg,medidor=lambda:estado(5*2**30)):self.fail('admitiu')
            self.assertFalse(db.exists())
            estados=iter([estado(),estado(5*2**30)])
            with self.assertRaises(ValueError):
                with reservar(db,self.cfg,medidor=lambda:next(estados)):self.fail('admitiu')
            with reservar(db,self.cfg,medidor=estado):pass

    def test_medicao_host_e_residentes_gpu_sao_conferidos_juntos(self):
        d=estado()
        with patch('recursos_local.medir_host',return_value={k:v for k,v in d.items() if k not in ('ollama','gpu')}), \
             patch('recursos_local.medir_ollama',return_value=d['ollama']),patch('recursos_local.medir_gpu',return_value=d['gpu']):
            self.assertEqual(medir(),d)

    def test_falha_de_protocolo_http_nao_escapa_do_watchdog(self):
        cliente=SimpleNamespace(open=lambda *a,**k: (_ for _ in ()).throw(http.client.BadStatusLine('invalido')))
        with patch.object(m.urllib.request,'build_opener',return_value=cliente):
            with self.assertRaises(OSError):m.medir_ollama()

    def test_watchdog_pressao_residente_interrompe_so_console(self):
        processo=SimpleNamespace(pid=98765,poll=lambda:None)
        for d in (estado(5*2**30),estado(gpu=gpu(1)),estado(2**30,1)):
            with patch('recursos_local.os.name','nt'),patch('recursos_local.subprocess.run',return_value=SimpleNamespace(returncode=0)) as parar:
                with self.assertRaises(ValueError):
                    with vigiar(processo,self.cfg,medidor=lambda:d,intervalo=0.005):
                        for _ in range(100):
                            if parar.called:break
                            time.sleep(0.005)
                parar.assert_called_once()
                self.assertEqual(parar.call_args.args[0],['taskkill','/PID','98765','/T','/F'])

    def test_http_get_bounded_sem_proxy_redirect_inferencia_ou_descarregamento(self):
        chamadas=[]
        class Handler(BaseHTTPRequestHandler):
            modo='normal'
            def log_message(self,*args):pass
            def do_GET(self):
                chamadas.append(self.path)
                if self.modo=='redirect':
                    self.send_response(302);self.send_header('Location','/fora');self.end_headers();return
                bruto=b'x'*(m.LIMITE_RESPOSTA+1) if self.modo=='grande' else json.dumps({'models':[]}).encode()
                self.send_response(200);self.send_header('Content-Length',str(len(bruto)));self.end_headers();self.wfile.write(bruto)
        srv=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=srv.serve_forever,daemon=True);thread.start()
        try:
            with patch.object(m,'URL_OLLAMA',f'http://127.0.0.1:{srv.server_port}'),patch.dict(os.environ,{'http_proxy':'http://127.0.0.1:1','HTTP_PROXY':'http://127.0.0.1:1','no_proxy':'','NO_PROXY':''}):
                self.assertEqual(m.medir_ollama()['quantidade'],0)
                for modo in ('redirect','grande'):
                    Handler.modo=modo
                    with self.assertRaises(OSError):m.medir_ollama()
            self.assertEqual(chamadas,['/api/ps']*3)
        finally:srv.shutdown();srv.server_close();thread.join(timeout=3)


if __name__=='__main__':unittest.main()
