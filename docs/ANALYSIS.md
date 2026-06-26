# Análise técnica

## Resumo

O DJE Finder TJRR é um sincronizador desktop especializado. Ele explora um padrão previsível de URL do portal do TJRR, testa uma data por vez e mantém localmente os PDFs encontrados. O projeto é útil para formar uma coleção histórica sem exigir que o usuário faça downloads manuais.

O desenho atual é adequado para uma aplicação pessoal ou de pequeno porte: Tkinter mantém a distribuição simples, `requests` resolve a comunicação HTTP e threads permitem que a interface continue responsiva.

## Pontos fortes

- objetivo claro e fluxo de uso direto;
- ausência de banco de dados ou infraestrutura externa;
- organização dos documentos por ano;
- retomada após interrupções;
- controle agregado de velocidade;
- concorrência apropriada para operações de rede;
- formato de dados legível e fácil de recuperar.

## Riscos encontrados e tratamento aplicado

| Área | Situação anterior | Tratamento atual |
| --- | --- | --- |
| HTTPS | certificado não era verificado e alertas eram ocultados | verificação padrão do `requests` restaurada |
| Downloads incompletos | o arquivo final era escrito diretamente | uso de `.part`, validação `%PDF` e substituição atômica |
| Interrupção | tarefas já submetidas podiam desaparecer da retomada | `em_andamento` agora é persistido |
| Falhas de rede | uma data com erro podia deixar de ser tentada | falhas são salvas e recuperadas na próxima execução |
| Backups manuais | PDFs copiados sem `indice.json` não eram reconhecidos na montagem da fila | a pasta é varrida, arquivos válidos entram no índice, lacunas grandes voltam para a fila e o PDF mais recente vira o marco inicial |
| Pausa | o seletor de velocidade continuava bloqueado após pausar | o modo pode ser alterado durante a pausa e aplicado ao retomar |
| JSON corrompido | uma interrupção durante a escrita podia truncar metadados | gravação temporária e substituição atômica |
| Diagnóstico | erros de leitura eram ignorados | avisos são registrados com `logging` |
| Distribuição | não havia instruções ou processo de build | README, dependências, PyInstaller e GitHub Actions adicionados |

## Prioridades recomendadas

### Alta

1. Confirmar periodicamente se o padrão de URL do TJRR continua válido.
2. Respeitar limites e termos de uso do portal, usando preferencialmente os modos lento ou rápido.
3. Manter testes para persistência, retomada e validação dos arquivos.
4. Assinar digitalmente o executável Windows quando o projeto tiver distribuição mais ampla.

### Média

1. Dividir `app.py` em módulos para interface, domínio, rede e persistência.
2. Adicionar uma tela de configuração de período e pasta de destino.
3. Exibir uma lista das falhas, com botão de nova tentativa.
4. Criar logs rotativos em arquivo para facilitar suporte.
5. Adicionar tentativas automáticas com espera progressiva para erros transitórios.

### Evolução do produto

1. Indexar o texto dos PDFs para pesquisa por nome, processo ou termo.
2. Adicionar OCR opcional para documentos sem camada de texto.
3. Permitir exportar resultados e metadados em CSV.
4. Detectar alterações ou republicações de uma mesma edição por hash.
5. Disponibilizar também uma interface de linha de comando para automação.

## Cuidados jurídicos e de privacidade

Diários judiciais podem conter dados pessoais. O software apenas baixa documentos já expostos pelo portal de origem, mas quem redistribui, indexa ou processa esse conteúdo deve avaliar as regras aplicáveis, a finalidade do tratamento e eventuais obrigações relacionadas à LGPD.

O repositório não deve incluir PDFs baixados, índices pessoais, caminhos locais ou exemplos contendo dados reais de processos.
