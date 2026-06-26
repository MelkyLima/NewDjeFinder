# Changelog

Todas as mudanças relevantes deste projeto serão documentadas neste arquivo.

## [1.0.0] - 2026-06-23

### Adicionado

- documentação completa para publicação;
- testes automatizados e workflows de CI/release;
- configuração por variáveis de ambiente;
- gravação atômica de JSON e PDFs;
- recuperação de tarefas em andamento e datas com falha;
- reconstrução do índice a partir de PDFs já existentes no disco, usando o PDF mais recente como marco inicial e preservando lacunas grandes para verificação;
- progresso visual durante a preparação da base local;
- varredura local paralela e cache de PDFs detectados para reduzir o tempo de preparação;
- indicador separado de bytes baixados e datas consultadas por segundo;
- reutilização de sessões HTTP por thread durante consultas ao portal.
- registro persistente de datas verificadas sem PDF para impedir que lacunas já concluídas retornem como pendência.
- verificação HTTPS e identificação do cliente.

### Alterado

- ponto de entrada renomeado de `app3.py` para `app.py`;
- seletor de velocidade liberado durante a pausa e reaplicado ao retomar;
- encerramento da janela agora persiste o trabalho pendente.
