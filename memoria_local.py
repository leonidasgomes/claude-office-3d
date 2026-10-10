"""Leituras de residentes Ollama e GPU NVIDIA; sem carregar ou descarregar modelos."""
import csv
import io
import http.client
import json
import shutil
import subprocess
import urllib.request

URL_OLLAMA = 'http://127.0.0.1:11434'
LIMITE_RESPOSTA = 256 * 1024


class SemRedirecionamento(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise OSError('Ollama local não pode redirecionar a consulta')


def residentes(dados):
    """Só totais: nomes, digests e detalhes dos modelos não saem deste parser."""
    if not isinstance(dados, dict) or not isinstance(dados.get('models'), list) or len(dados['models']) > 128:
        raise OSError('Lista de modelos residentes inválida')
    total = vram = 0
    for m in dados['models']:
        if not isinstance(m, dict):
            raise OSError('Modelo residente inválido')
        tamanho, video = m.get('size'), m.get('size_vram')
        if (type(tamanho) is not int or type(video) is not int
                or not 0 < tamanho <= 2**50 or not 0 <= video <= tamanho
                or m.get('remote_host') or m.get('remote_model')):
            raise OSError('Memória do modelo residente desconhecida ou inconsistente')
        total += tamanho
        vram += video
    return {'quantidade': len(dados['models']), 'memoria_bytes': total, 'vram_bytes': vram}


def medir_ollama():
    # Proxy ambiental e redirects não podem converter uma consulta loopback em cloud.
    cliente = urllib.request.build_opener(urllib.request.ProxyHandler({}), SemRedirecionamento())
    try:
        with cliente.open(URL_OLLAMA+'/api/ps', timeout=3) as resposta:
            bruto = resposta.read(LIMITE_RESPOSTA+1)
        if len(bruto) > LIMITE_RESPOSTA:
            raise OSError('Resposta Ollama grande demais')
        return residentes(json.loads(bruto))
    except (ValueError, OSError, http.client.HTTPException) as exc:
        raise OSError('Medição dos modelos residentes Ollama indisponível') from exc


def gpus_nvidia(texto):
    """CSV sem unidades: índice, total MiB, livre MiB, uso percentual."""
    if not isinstance(texto, str) or len(texto) > 65536:
        raise OSError('Resposta GPU inválida')
    linhas = list(csv.reader(io.StringIO(texto)))
    if not 1 <= len(linhas) <= 64:
        raise OSError('Lista GPU indisponível')
    vistos = set(); saida = []
    for linha in linhas:
        campos = [x.strip() for x in linha]
        if len(campos) != 4 or any(not x.isascii() or not x.isdecimal() for x in campos):
            raise OSError('Métrica GPU desconhecida')
        indice, total, livre, uso = map(int, campos)
        if indice in vistos or not 0 <= indice < 64 or not 0 < total <= 2**30 or not 0 <= livre <= total or not 0 <= uso <= 100:
            raise OSError('Métrica GPU inconsistente')
        vistos.add(indice)
        saida.append({'indice': indice, 'total_bytes': total*2**20, 'livre_bytes': livre*2**20, 'uso_pct': uso})
    return saida


def medir_gpu():
    exe = shutil.which('nvidia-smi')
    if not exe:
        return {'estado': 'indisponivel', 'gpus': []}
    try:
        r = subprocess.run([exe, '--query-gpu=index,memory.total,memory.free,utilization.gpu',
                            '--format=csv,noheader,nounits'], capture_output=True,
                           text=True, encoding='utf-8', errors='strict', timeout=3, check=True)
        return {'estado': 'medido', 'gpus': gpus_nvidia(r.stdout)}
    except (OSError, ValueError, subprocess.SubprocessError):
        return {'estado': 'erro', 'gpus': []}


def verificar_memoria(local, estado):
    resumo = estado.get('ollama')
    if (not isinstance(resumo, dict) or type(resumo.get('quantidade')) is not int
            or not 0 <= resumo['quantidade'] <= 128
            or type(resumo.get('memoria_bytes')) is not int or type(resumo.get('vram_bytes')) is not int
            or not 0 <= resumo['vram_bytes'] <= resumo['memoria_bytes'] <= 128*2**50
            or (resumo['quantidade'] == 0) != (resumo['memoria_bytes'] == 0)):
        raise ValueError('Memória dos modelos residentes desconhecida')
    if resumo['memoria_bytes'] > local['ollama_memoria_max_gb']*2**30:
        raise ValueError('Modelos residentes excedem o orçamento de memória local')
    gpu = estado.get('gpu')
    if not isinstance(gpu, dict):
        raise ValueError('Estado GPU desconhecido')
    if gpu.get('estado') == 'indisponivel' and gpu.get('gpus') == [] and resumo['vram_bytes'] == 0:
        return
    if gpu.get('estado') != 'medido' or not isinstance(gpu.get('gpus'), list) or not gpu['gpus']:
        raise ValueError('GPU/VRAM ocupada ou medição indisponível')
    for g in gpu['gpus']:
        if not isinstance(g, dict):
            raise ValueError('Medição GPU inválida')
        total, livre, uso = g.get('total_bytes'), g.get('livre_bytes'), g.get('uso_pct')
        if (any(type(x) is not int for x in (total, livre, uso))
                or not 0 <= livre <= total or total <= 0 or not 0 <= uso <= 100
                or livre < local['vram_livre_min_gb']*2**30 or uso > local['gpu_uso_max_pct']):
            raise ValueError('GPU/VRAM ocupada ou medição inválida para inferência local')
