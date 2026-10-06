# Skills de terceiros em quarentena

Skill tirada de um repositório público entra aqui **antes** de ir para o `.claude/skills/` do projeto. Uma pasta por skill
(`externo/<nome>/SKILL.md` + `references/`), com a licença do repositório ao lado.

## Checklist antes de copiar
1. **Licença** que permite o seu uso (MIT, Apache-2.0...). Sem licença, não use.
2. **Leia o SKILL.md e as `references/` inteiros.** Procure:
   - scripts (`.py`, `.sh`, `.js`, `.ps1`) e o que eles fazem;
   - chamadas de rede, downloads, `npx`/`pip install` no meio das instruções;
   - frases do tipo "ignore as instruções anteriores", pedidos de chaves, tokens ou senhas.
3. **Fixe o commit**: copie de `.../contents/<arquivo>?ref=<sha>` e anote o sha neste README. Nada de "instale a última
   versão" automático.
4. **Só o que serve**: de um pacote com 30 skills, traga as 3 ou 4 do seu assunto. Cada descrição entra em toda sessão.
5. **Hooks de terceiros** (código que roda a cada evento) só depois de ler linha a linha e testar num projeto descartável.

## Depois de copiar
Trate como candidata do `skills.py`: registre os usos (`skills.py usar <nome> --agente X --cartao N --resultado ok|falhou`),
compare o custo das tarefas com e sem a skill no `custo_time.py` e só então promova para o `.claude/skills/` do projeto.

## Registro
| Skill | Repositório | Commit | Licença | Lida em | Situação |
|---|---|---|---|---|---|
| | | | | | |
