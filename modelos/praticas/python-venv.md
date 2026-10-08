# Python do projeto: sempre o .venv

- Rode testes, scripts e o grafo com o Python do `.venv` do projeto, nunca com o `python` do sistema:
  - Windows: `.venv/Scripts/python -m pytest`, `.venv/Scripts/python grafo.py ...`
  - Linux/macOS: `.venv/bin/python -m pytest`, `.venv/bin/python grafo.py ...`
- Onde outra regra, skill ou definição de agente diz `python ...`, leia como o Python do `.venv` acima.
- A evidência de teste de uma revisão ou de um PR vale só se rodou no `.venv` (é o ambiente que o CI e os colegas usam).
- Falta um pacote? Instale no `.venv` (`.venv/Scripts/python -m pip install <pacote>` ou `.venv/bin/python -m pip install
  <pacote>`) e registre no `requirements.txt` (ou no `pyproject.toml`) no mesmo commit. Nunca instale no Python do sistema.
- Sem `.venv` ainda: `python -m venv .venv` e depois `-m pip install -r requirements.txt` com o Python dele. A pasta `.venv/`
  fica fora do git (`.gitignore`).
