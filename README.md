# Lumi Secrets

Loja online com painel do dono em `/admin`.

## Atualizar a loja

No painel, altere produtos, fotos principais e logos. Ao salvar, as mudancas ficam no banco compartilhado e aparecem na loja ao atualizar a pagina, sem precisar de um novo deploy.

Para alterar layout, cores, textos ou funcionalidades, edite os arquivos deste repositorio, confira as mudancas e envie um commit para `main`. Com a integracao Git da Vercel, cada push para `main` publica uma nova versao automaticamente apos o build terminar.

```powershell
git add index.html app.js baby-pink-theme.css
git commit -m "Atualiza a loja"
git push origin main
```

A pasta local esta ligada ao repositorio `matheusfcarvalho-cloud/lumi-secrets` e ao projeto Vercel `lumi-secrets`. Nao envie arquivos de ambiente, dados privados ou logs ao GitHub.

## Validacao

```powershell
python -m unittest discover -s tests
```

Consulte `ORDERS_DATABASE.md` para a configuracao do banco e dos pagamentos.
