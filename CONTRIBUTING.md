# Como contribuir

## Preparação

1. Crie um fork e uma branch descritiva.
2. Configure um ambiente virtual.
3. Instale `requirements-dev.txt`.
4. Faça mudanças pequenas e focadas.

## Validação

Antes de abrir um pull request:

```bash
python -m unittest discover -s tests -v
python -m py_compile app.py
```

## Pull requests

Descreva:

- o problema resolvido;
- a abordagem adotada;
- como a alteração foi testada;
- impactos sobre rede, armazenamento ou compatibilidade.

Não inclua PDFs baixados, arquivos de estado, credenciais ou dados pessoais no repositório.
