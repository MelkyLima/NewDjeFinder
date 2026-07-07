# DJE Finder TJRR

Aplicativo desktop para localizar, baixar, organizar e indexar edicoes em PDF do Diario da Justica Eletronico do Tribunal de Justica de Roraima (TJRR). O app monta uma base local por ano, permite retomar sincronizacoes interrompidas e prepara os documentos para busca textual.

> Este e um projeto independente, sem vinculo oficial com o TJRR. A disponibilidade, o formato e as regras de acesso aos documentos dependem do portal de origem.

## O que o projeto faz

- percorre as datas desde 3 de janeiro de 2003 ate o dia atual;
- consulta o endereco publico de cada possivel edicao;
- baixa PDFs encontrados para `Documentos/PDF-Dje/<ano>`;
- reconhece PDFs ja existentes nessa pasta, mesmo quando metadados antigos nao foram restaurados;
- mantem um banco local SQLite (`dje_finder.db`) com PDFs, datas sem edicao, fila de sincronizacao e indice textual;
- migra automaticamente arquivos legados `indice.json` e `estado.json` para SQLite;
- registra datas ja verificadas sem PDF, evitando que voltem como pendencia;
- salva o estado para continuar apos interrupcoes;
- oferece modos de velocidade e downloads concorrentes;
- valida o conteudo antes de substituir o arquivo definitivo;
- tenta novamente, na proxima execucao, as datas que falharam por erro de rede;
- extrai texto dos PDFs com PyMuPDF e alimenta uma tabela FTS5 para busca textual na GUI.

## Requisitos

- Python 3.10 ou superior;
- Windows, Linux ou macOS com Tkinter disponivel;
- acesso ao dominio `diario.tjrr.jus.br`.

No Linux, pode ser necessario instalar o pacote do Tkinter. Em distribuicoes baseadas em Debian:

```bash
sudo apt install python3-tk
```

## Instalacao

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
3. Use **Pausar** para impedir o agendamento de novos downloads. Downloads ja iniciados podem terminar.
4. Enquanto estiver pausado, altere o modo de velocidade se quiser; ao clicar em **Retomar**, o novo limite sera aplicado.
5. Feche a aplicacao quando quiser; a fila e as tarefas em andamento serao salvas.

### Checagem local vs sincronizacao online

- **Checagem local, ao abrir o app**: o aplicativo varre os arquivos locais de forma offline, valida PDFs existentes, atualiza o banco SQLite, detecta lacunas no acervo e prepara a fila.
- **Indexacao textual em segundo plano**: depois da preparacao local, PDFs pendentes sao lidos com PyMuPDF e gravados no indice FTS5. A interface ja exibe o progresso dessa etapa.
- **Sincronizacao online, ao atualizar**: antes de consultar datas em massa, o app verifica a conectividade do computador e a estabilidade do portal TJRR.

### Busca textual

A aba **Busca textual** permite pesquisar termos no conteudo dos PDFs ja indexados. Os resultados sao exibidos em tabela com data, ano/mes, trecho encontrado e caminho do arquivo.

Recursos disponiveis:

- paginacao com carregamento inicial de ate 50 resultados;
- filtros por ano e mes;
- modo **Todos os termos**, que encontra PDFs contendo todos os termos digitados em qualquer ponto do texto;
- modo **Frase exata**, que encontra apenas a sequencia dos termos na ordem digitada;
- modo **Contexto proximo**, usando o campo **Perto de** para encontrar dois grupos de termos dentro de uma distancia aproximada em palavras;
- ordenacao por relevancia, mais recentes ou mais antigos;
- botoes para abrir o PDF ou a pasta do resultado selecionado;
- aviso quando ainda existem PDFs pendentes de indexacao.

O indice FTS5 usa tokenizacao Unicode com remocao de diacriticos, entao buscas ignoram diferencas de maiusculas/minusculas e acentos.

Para nomes completos, use **Frase exata** ou preencha **Perto de**. Quando **Perto de** esta preenchido, o termo principal e o termo relacionado sao tratados como grupos de frase, evitando que partes do nome sejam aceitas espalhadas pelo documento.

### Comportamento em caso de portal offline ou sem internet

- **Sem conexao local**: se o computador estiver desconectado, a sincronizacao e pausada e a interface exibe um alerta.
- **Portal instavel ou fora do ar**: o app nao inicia consultas em massa nem downloads. Falhas temporarias nao sao gravadas como datas definitivamente sem PDF.
- **Instabilidade durante o progresso**: caso ocorram 5 falhas de rede consecutivas, o aplicativo entra em pausa automatica de seguranca.
- **Como tentar novamente**: o botao de acao fica disponivel como **Retomar** ou **ATUALIZAR Base de PDFs** para reavaliar a conexao e prosseguir.

Quando uma data e consultada e o portal informa que nao ha PDF disponivel, por resposta HTTP 404 valida e definitiva, ela e registrada em `datas_sem_pdf` no SQLite.

Ao abrir o app depois de uma interrupcao, a opcao **Retomar Sessao** significa:

- **Sim**: mantem a fila salva, incluindo falhas e downloads que estavam em andamento;
- **Nao**: descarta a fila salva e recalcula a base usando os PDFs que ja estao na pasta.

Se voce ja tem backup dos PDFs, copie as pastas anuais para o diretorio de dados antes de iniciar a atualizacao. Arquivos no formato `PDF-Dje/<ano>/dpj-AAAAMMDD.pdf` serao detectados localmente e nao serao baixados novamente.

Se houver um intervalo grande sem nenhum PDF entre arquivos importados, por exemplo anos anteriores presentes, 2006 ausente e anos posteriores presentes, esse intervalo volta para a fila de verificacao. Assim o app nao considera um backup incompleto como 100% concluido so porque encontrou PDFs mais recentes.

Se arquivos legados `indice.json` ou `estado.json` existirem, eles sao migrados para `dje_finder.db` e renomeados para `.bak`. Depois da migracao, o SQLite passa a ser a fonte principal dos metadados.

## Dados e configuracao

Por padrao, os dados sao gravados em:

```text
~/Documents/PDF-Dje/
|-- dje_finder.db
|-- dje_finder.db-shm
|-- dje_finder.db-wal
|-- 2025/
|   `-- dpj-20250110.pdf
`-- 2026/
    `-- dpj-20260112.pdf
```

Variaveis de ambiente opcionais:

| Variavel | Finalidade | Padrao |
| --- | --- | --- |
| `DJE_FINDER_DATA_DIR` | Diretorio dos PDFs e metadados | `~/Documents/PDF-Dje` |
| `DJE_FINDER_START_DATE` | Primeira data da busca, em `AAAAMMDD` | `20030103` |
| `DJE_FINDER_BASE_URL` | Modelo da URL contendo `{}` para a data | Portal publico do TJRR |

Exemplo:

```powershell
$env:DJE_FINDER_START_DATE = "20250101"
$env:DJE_FINDER_DATA_DIR = "D:\DiariosTJRR"
python app.py
```

## Testes

```bash
python -m unittest discover -s tests -v
python -m compileall app.py dje_finder tests
```

## Gerar executavel Windows

```bash
python -m pip install -r requirements-dev.txt
pyinstaller dje-finder.spec
```

O executavel sera criado em `dist/DJEFinderTJRR.exe`. Releases marcadas com tags no formato `v*` tambem acionam o workflow que gera o artefato automaticamente.

## Interface Web local

O projeto tambem possui uma interface Web em Streamlit para consulta textual, reaproveitando o mesmo `PDFSearchEngine` usado pela GUI.

Execute localmente:

```bash
python -m pip install -r requirements.txt
python -m streamlit run streamlit_app.py
```

Na barra lateral, confirme o diretorio que contem `dje_finder.db` e as pastas anuais com PDFs. A pagina permite:

- buscar por todos os termos, frase exata ou contexto proximo;
- informar um termo relacionado em **Perto de**;
- ajustar distancia do contexto;
- filtrar por ano e mes;
- ordenar por relevancia, mais recentes ou mais antigos;
- baixar o PDF encontrado quando o arquivo existe localmente.

Para acessar em outro computador da mesma rede, mantenha o servidor rodando e abra o endereco de rede exibido pelo Streamlit, por exemplo `http://192.168.100.9:8501`.

## Arquitetura

O aplicativo separa suas responsabilidades em componentes internos:

- `IndexManager`: catalogo dos PDFs encontrados e datas sem edicao;
- `StateManager`: fila, tarefas em andamento, falhas recuperaveis e contadores da interface;
- `PDFDiscovery`: consulta ao portal;
- `DownloadManager`: gravacao temporaria e validacao do PDF;
- `PDFIndexer`: extracao de texto e indexacao SQLite FTS5;
- `PDFSearchEngine`: consulta reutilizavel ao indice textual;
- `WorkerController`: concorrencia, limitacao de velocidade e progresso;
- `TJRRSyncApp`: interface Tkinter.
- `streamlit_app.py`: interface Web local para busca textual.

Mais detalhes estao em [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

A avaliacao tecnica e o roadmap sugerido estao em [docs/ANALYSIS.md](docs/ANALYSIS.md).

## Limitacoes conhecidas

- o portal nao oferece, neste projeto, uma API de catalogo; por isso a descoberta e feita por data;
- mudancas no endereco ou no padrao dos arquivos exigirao atualizacao da configuracao;
- a pausa nao interrompe imediatamente requisicoes ja iniciadas;
- a busca textual cobre apenas PDFs que ja foram indexados localmente;
- PDFs sem camada de texto exigirao OCR em uma evolucao futura.

## Contribuindo

Leia [CONTRIBUTING.md](CONTRIBUTING.md) antes de enviar uma alteracao. Relatos de vulnerabilidade devem seguir [SECURITY.md](SECURITY.md).

## Licenca

Distribuido sob a licenca MIT. Consulte [LICENSE](LICENSE).
