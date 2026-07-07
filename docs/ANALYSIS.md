# Analise tecnica

## Resumo

O DJE Finder TJRR e um sincronizador desktop especializado. Ele explora um padrao previsivel de URL do portal do TJRR, testa uma data por vez, mantem localmente os PDFs encontrados e ja prepara uma base SQLite para pesquisa textual.

O desenho atual e adequado para uma aplicacao pessoal ou de pequeno porte: Tkinter mantem a distribuicao simples, `requests` resolve a comunicacao HTTP, SQLite evita infraestrutura externa e threads/processos mantem a interface responsiva durante downloads e indexacao.

## Pontos fortes

- objetivo claro e fluxo de uso direto;
- armazenamento local em SQLite, sem servico externo;
- organizacao dos documentos por ano;
- retomada apos interrupcoes;
- controle agregado de velocidade;
- concorrencia apropriada para operacoes de rede;
- migracao automatica de JSON legado;
- testes cobrindo persistencia, retomada, falhas de rede e indexacao textual;
- busca textual na GUI usando a base FTS5.

## Riscos encontrados e tratamento atual

| Area | Situacao | Tratamento atual |
| --- | --- | --- |
| HTTPS | Falhas temporarias do portal nao devem virar ausencia definitiva | Erros de rede sao salvos em `falhas`; apenas 404 vira `datas_sem_pdf` |
| Downloads incompletos | Arquivo final nao deve ser substituido por resposta invalida | Uso de `.part`, validacao `%PDF` e substituicao final |
| Interrupcao | Tarefas submetidas precisam voltar na proxima execucao | `em_andamento` e `fila_restante` sao persistidos no SQLite |
| Backups manuais | PDFs copiados sem metadados precisam ser reconhecidos | Varredura local valida PDFs e reconstrui o catalogo |
| Lacunas de acervo | Backup incompleto nao deve parecer completo | Intervalos grandes entre PDFs locais voltam para a fila |
| Busca textual | Extracao pode ser lenta em acervos grandes | Processo produtor-consumidor com escrita SQLite em lote |
| Dados legados | Usuarios podem ter `indice.json` e `estado.json` antigos | Migracao automatica para `dje_finder.db` |
| Distribuicao | Dependencias e build precisam acompanhar o codigo | `requirements.txt`, CI e spec do PyInstaller declaram a indexacao |

## Prioridades antes de novas funcionalidades

1. Manter `requirements.txt`, CI e PyInstaller alinhados com imports reais.
2. Preservar testes para persistencia, retomada, validacao de PDFs e indexacao.
3. Evitar que erros transitorios do portal contaminem `datas_sem_pdf`.
4. Nao versionar banco local, PDFs baixados, arquivos `.part` ou metadados pessoais.

## Estado da busca textual

A busca textual ja esta implementada na GUI com um modulo reutilizavel:

- campo para termo de busca;
- consulta FTS5 em `pdf_pages_fts`;
- listagem de resultados por data;
- trecho do texto encontrado;
- acao para abrir o PDF local correspondente;
- filtros por ano e mes;
- modo todos os termos e modo frase exata;
- modo contexto proximo com termo relacionado e distancia em palavras;
- ordenacao por relevancia, mais recentes e mais antigos;
- carregamento paginado;
- aviso quando ainda ha PDFs pendentes de indexacao.

## Proximo passo recomendado

A proxima evolucao mais natural e preparar a publicacao Web:

- decidir onde a base SQLite e os PDFs ficarao hospedados;
- adicionar exportacao CSV dos resultados;
- destacar melhor os termos encontrados;
- avaliar autenticacao ou acesso privado se a base contiver dados sensiveis.

Essa entrega aproveita a infraestrutura que ja existe e transforma a indexacao em valor visivel para o usuario.

## Evolucao posterior

1. OCR opcional para documentos sem camada de texto.
2. Exportacao de resultados e metadados em CSV.
3. Deteccao de alteracoes ou republicacoes por hash.
4. Tela de preferencias para pasta, periodo e concorrencia.
5. Interface de linha de comando para automacao.

## Cuidados juridicos e de privacidade

Diarios judiciais podem conter dados pessoais. O software apenas baixa documentos ja expostos pelo portal de origem, mas quem redistribui, indexa ou processa esse conteudo deve avaliar as regras aplicaveis, a finalidade do tratamento e eventuais obrigacoes relacionadas a LGPD.

O repositorio nao deve incluir PDFs baixados, indices pessoais, caminhos locais ou exemplos contendo dados reais de processos.
