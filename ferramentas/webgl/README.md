# Validação real de WebGL no Linux

Teste isolado para PR, sem alterar o código de produção e sem merge/deploy.
Usa runner padrão `ubuntu-22.04` de repositório público, timeout de 10 minutos,
permissão `contents: read`, checkout sem credencial persistida e Chromium completo
compatível com Playwright fixado no lockfile. O sandbox é explicitamente ligado.
Nenhum flag de desativação do sandbox ou SwiftShader inseguro é permitido.
Defaults de teste que relaxam proteção (phishing, avisos self-XSS, IPC, popup,
repost, senha básica e features HTTPS/particionamento) são removidos por lista
explícita do Playwright fixado; os argumentos efetivos são conferidos.
Se o ambiente não oferecer contexto WebGL2 real, o teste **falha**; não troca
por DOM simulado, imagem pronta ou renderizador fictício.

O harness cria dois projetos sintéticos em diretório temporário, usa as rotas e
arquivos reais do Office, escuta apenas em 127.0.0.1 e serve Three.js 0.160.0 pelo
caminho vendor já suportado pelo aplicativo. Não executa os loops de integração
do main: GitHub, providers, notificações e sessões pessoais não são validados.
O servidor recebe HOME vazio, PATH sem CLIs e nenhum segredo. O harness bloqueia
subprocessos/conexões de saída do servidor, HTTP externo e todos os WebSockets
da página. A validação não atesta filtro de Host: usa o Handler original, que
confia no cliente loopback, nem modifica configurações de segurança do sistema.

O teste exige:
- WebGL2 com renderização de vermelho/verde e leitura exata dos pixels;
- cena real com mais de 100 cores quantizadas e amplitude > 80;
- movimento observável da câmera após a roda do mouse;
- mudança em > 5% dos pixels da cena, com duas capturas PNG;
- chamadas reais de desenho GL e mais de 100 triângulos;
- contexto da cena não perdido, nenhum erro GL, JavaScript ou console.

Commit testado, versão/argumentos do navegador, GPU declarada, métricas e erros
saem em `OFFICE_WEBGL_RESULT`. Dois PNGs de no máximo 400 KB cada saem em blocos
`OFFICE_PNG_BEGIN`, `OFFICE_PNG_DATA` e `OFFICE_PNG_END`, base64 em linhas curtas.
Para recuperar, retire o prefixo/timestamp do log, concatene os dados de cada
bloco e decodifique base64. Confira o tamanho e SHA-256 anunciados e abra a imagem.
Os arquivos também ficam em `ferramentas/webgl/results` durante o job efêmero.

Não usa Actions cache ou upload-artifact: o armazenamento de artifacts pode
ser cobrado separadamente; logs não contam para essa quota. Esta evidência
sintética depende da retenção de logs configurada no repositório, sem alterar
configurações da conta. Não é um teste de GPU física nem de todos os navegadores.

Execução local, em checkout descartável com git, Python 3 e Node 22:

```sh
cd ferramentas/webgl
npm ci --ignore-scripts --no-audit --no-fund
npx --no-install playwright install --with-deps --no-shell chromium
npm test
```

Referências:
- https://playwright.dev/docs/api/class-browsertype#browser-type-launch-option-chromium-sandbox
- https://playwright.dev/docs/browsers#chromium-new-headless-mode
- https://docs.github.com/en/billing/concepts/product-billing/github-actions
