# DJE Finder TJRR

Aplicativo desktop para localizar e baixar edições em PDF do Diário da Justiça Eletrônico do Tribunal de Justiça de Roraima (TJRR), organizando os arquivos por ano e permitindo retomar sincronizações interrompidas.

> Este é um projeto independente, sem vínculo oficial com o TJRR. A disponibilidade, o formato e as regras de acesso aos documentos dependem do portal de origem.

## O que o projeto faz

- percorre as datas desde 3 de janeiro de 2003 até o dia atual;
- consulta o endereço público de cada possível edição;
- baixa PDFs encontrados para `Documentos/PDF-Dje/<ano>`;
- reconhece PDFs já existentes nessa pasta, mesmo quando `indice.json` não foi restaurado;
- mantém um índice local em `indice.json`;
- registra em `indice.json` as datas já verificadas sem PDF, evitando que elas voltem como pendência;
- salva o estado para continuar após interrupções;
- oferece modos de velocidade e downloads concorrentes;
- valida o conteúdo antes de substituir o arquivo definitivo;
- tenta novamente, na próxima execução, as datas que falharam por erro de rede.

## Requisitos

- Python 3.10 ou superior;
- Windows, Linux ou macOS com Tkinter disponível;
- acesso ao domínio `diario.tjrr.jus.br`.

No Linux, pode ser necessário instalar o pacote do Tkinter. Em distribuições baseadas em Debian:

```bash
sudo apt install python3-tk
```

## Instalação

```bash
git clone URL_DO_REPOSITORIO
cd NewDjeFinder
python -m venv .venv
```

Ative o ambiente virtual:

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

```bash
# Linux ou macOS
source .venv/bin/activate
```

Instale e execute:

```bash
python -m pip install -r requirements.txt
python app.py
```

## Como usar

1. Escolha o modo de velocidade.
2. Clique em **ATUALIZAR Base de PDFs**.
3. Use **Pausar** para impedir o agendamento de novos downloads. Downloads já iniciados podem terminar.
4. Enquanto estiver pausado, altere o modo de velocidade se quiser; ao clicar em **Retomar**, o novo limite será aplicado.
5. Feche a aplicação quando quiser; a fila e as tarefas em andamento serão salvas.

### Checagem Local vs Sincronização Online
* **Checagem Local (ao abrir o app)**: O aplicativo realiza de forma 100% offline a varredura e indexação dos arquivos locais. Ele valida os PDFs existentes, reconstrói o índice local (`indice.json`), detecta lacunas no acervo e atualiza as estatísticas sem necessitar de conexão com a rede.
* **Sincronização Online (ao atualizar)**: Ao iniciar a atualização online, o app executa primeiro uma checagem de conectividade do computador e de estabilidade do portal TJRR (`diario.tjrr.jus.br`).

### Comportamento em caso de portal offline ou sem internet
* **Sem conexão local**: Se o PC estiver desconectado da internet, a sincronização é pausada, exibindo uma mensagem de alerta em vermelho.
* **Portal instável / fora do ar (erro 502, timeouts, erros de certificado)**: O app não inicia consultas em massa nem faz downloads. Nenhuma data é gravada indevidamente no conjunto de `datas_sem_pdf` (evitando corromper o índice definitivo com falhas temporárias). Uma mensagem é exibida na interface indicando que o portal está indisponível e a sincronização foi pausada.
* **Instabilidade durante o progresso**: Caso ocorram 5 falhas de rede consecutivas durante o download/busca, o aplicativo entra em pausa automática de segurança para não gerar tráfego desnecessário e preservar a fila local.
* **Como tentar novamente**: O botão de ação é mantido ativo exibindo "Retomar" (ou "ATUALIZAR Base de PDFs"). O usuário pode clicar novamente no botão a qualquer momento para reavaliar a conexão e prosseguir com a sincronização online de onde parou.

Quando uma data é consultada e o portal informa que não há PDF disponível (resposta HTTP 404 válida e definitiva), ela é registrada como `datas_sem_pdf` no `indice.json`. Isso evita que a mesma lacuna volte a aparecer toda vez que o app abre.


Ao abrir o app depois de uma interrupção, a opção **Retomar Sessão** significa:

- **Sim**: mantém a fila salva em `estado.json`, incluindo falhas e downloads que estavam em andamento;
- **Não**: descarta a fila salva e recalcula a base usando os PDFs que já estão na pasta.

Se você já tem backup dos PDFs, copie as pastas anuais para o diretório de dados antes de iniciar a atualização. Arquivos no formato `PDF-Dje/<ano>/dpj-AAAAMMDD.pdf` serão detectados localmente e não serão baixados novamente.

Quando o backup contém apenas PDFs, sem `indice.json`, o app usa o PDF mais recente encontrado como ponto de partida e verifica somente datas posteriores. Isso evita consultar novamente todo o histórico. Se você quiser preservar também o registro exato de datas já verificadas sem edição, restaure o `indice.json` junto com as pastas.

Se você iniciou uma atualização, fechou o app e depois copiou um backup completo para a pasta, pode escolher **Sim** em **Retomar Sessão**. Durante a preparação inicial, o app reconcilia a fila antiga com os arquivos locais e descarta pendências já cobertas pelo backup.

Se houver um intervalo grande sem nenhum PDF entre arquivos importados, por exemplo anos anteriores presentes, 2006 ausente e anos posteriores presentes, esse intervalo volta para a fila de verificação. Assim o app não considera um backup incompleto como 100% concluído só porque encontrou PDFs mais recentes.

Se `indice.json` existir, qualquer PDF registrado no índice que tenha sido removido da pasta volta para a fila, inclusive quando uma pasta anual inteira for apagada. Sem `indice.json`, o app consegue detectar blocos grandes ausentes entre PDFs importados, mas não consegue saber com segurança que um único dia específico faltando era uma edição real; nesses casos, mantenha o `indice.json` junto ao backup para reparo preciso.

## Dados e configuração

Por padrão, os dados são gravados em:

```text
~/Documents/PDF-Dje/
├── estado.json
├── indice.json
├── 2025/
│   └── dpj-20250110.pdf
└── 2026/
    └── dpj-20260112.pdf
```

Variáveis de ambiente opcionais:

| Variável | Finalidade | Padrão |
| --- | --- | --- |
| `DJE_FINDER_DATA_DIR` | Diretório dos PDFs e metadados | `~/Documents/PDF-Dje` |
| `DJE_FINDER_START_DATE` | Primeira data da busca, em `AAAAMMDD` | `20030103` |
| `DJE_FINDER_BASE_URL` | Modelo da URL contendo `{}` para a data | Portal público do TJRR |

Exemplo:

```powershell
$env:DJE_FINDER_START_DATE = "20250101"
$env:DJE_FINDER_DATA_DIR = "D:\DiariosTJRR"
python app.py
```

## Testes

```bash
python -m unittest discover -s tests -v
python -m py_compile app.py
```

## Gerar executável Windows

```bash
python -m pip install -r requirements-dev.txt
pyinstaller dje-finder.spec
```

O executável será criado em `dist/DJEFinderTJRR.exe`. Releases marcadas com tags no formato `v*` também acionam o workflow que gera o artefato automaticamente.

## Arquitetura

O aplicativo separa suas responsabilidades em componentes internos:

- `IndexManager`: catálogo dos PDFs encontrados;
- `StateManager`: fila, tarefas em andamento e falhas recuperáveis;
- `PDFDiscovery`: consulta ao portal;
- `DownloadManager`: gravação temporária e validação do PDF;
- `WorkerController`: concorrência, limitação de velocidade e progresso;
- `TJRRSyncApp`: interface Tkinter.

Mais detalhes estão em [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

A avaliação técnica e o roadmap sugerido estão em [docs/ANALYSIS.md](docs/ANALYSIS.md).

## Limitações conhecidas

- o portal não oferece, neste projeto, uma API de catálogo; por isso a descoberta é feita por data;
- mudanças no endereço ou no padrão dos arquivos exigirão atualização da configuração;
- a pausa não interrompe imediatamente requisições já iniciadas;
- a aplicação baixa e organiza os PDFs, mas ainda não pesquisa texto dentro dos documentos.

## Contribuindo

Leia [CONTRIBUTING.md](CONTRIBUTING.md) antes de enviar uma alteração. Relatos de vulnerabilidade devem seguir [SECURITY.md](SECURITY.md).

## Licença

Distribuído sob a licença MIT. Consulte [LICENSE](LICENSE).
