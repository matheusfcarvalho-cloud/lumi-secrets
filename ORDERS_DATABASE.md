# Contas, pedidos e histórico Lumi

A aplicação usa SQLite em `.lumi-private/lumi_orders.sqlite3`. O backend registra perfis, sessões, pedidos, itens e eventos de histórico. O checkout exige que o cliente entre ou crie um perfil com nome, e-mail, senha, WhatsApp e endereço de entrega. O endereço é copiado para cada pedido para preservar o destino original.

## Executar localmente

Requer Python 3.10 ou mais recente; não há dependências externas.

```powershell
py -3 server.py
```

## Deploy na Vercel

A pasta `api/` encaminha as rotas `/api/*` para a aplicação WSGI de `server.py`; os arquivos do site são publicados como conteúdo estático. `vercel.json` habilita URLs sem `.html`, incluindo `/admin`. Em produção, use um banco Turso/libSQL remoto: o SQLite local da função não é persistente e a aplicação agora recusa iniciar na Vercel sem `TURSO_DATABASE_URL`.

1. Crie um banco no Turso e copie a URL `libsql://...` e um token de autenticação.
2. Importe este repositório na Vercel com a raiz do projeto apontando para a pasta que contém `vercel.json` e configure as variáveis `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`, `LUMI_ADMIN_EMAIL` e `LUMI_ADMIN_PASSWORD` para Production. Use uma senha forte com pelo menos 6 caracteres; ainda não defina `LUMI_DB_SCHEMA_READY`.
3. No ambiente seguro de onde executará a migração, use as credenciais do banco Production. Instale as dependências com `python -m pip install -r requirements.txt` e rode `python scripts/migrate_db.py` antes de liberar o deploy.
4. Depois que a migração terminar, defina `LUMI_DB_SCHEMA_READY=1` para Production e faça um novo deploy.
5. Para Preview, use de preferência outro banco Turso. Configure as credenciais desse banco, rode novamente `python scripts/migrate_db.py` com elas e só então defina `LUMI_DB_SCHEMA_READY=1` para Preview.
6. Acesse `https://seu-dominio/admin` e entre com o e-mail e a senha definidos nas variáveis.

O runtime da Vercel não cria nem altera o esquema: sem `LUMI_DB_SCHEMA_READY=1`, a API falha com uma mensagem de configuração. Execute o comando de migração novamente sempre que uma versão introduzir mudanças de esquema, antes de liberar essa versão. Cadastros, pedidos, sessões, configurações de pagamento e fotos enviadas pelo painel ficam no banco remoto. As fotos enviadas pelo painel têm limite de 3 MB.
O primeiro deploy começa com um banco vazio e não importa automaticamente o SQLite da pasta `.lumi-private`. O endereço público HTTPS da loja para retornos InfinitePay deve ser configurado na aba **Pagamentos** do painel.

Abra `http://localhost:8000`. O banco é criado/migrado automaticamente ao iniciar. O arquivo SQLite não é servido publicamente pelo servidor.

## Contas e privacidade

As senhas são armazenadas com hash scrypt e salt aleatório. A sessão é um cookie `HttpOnly` com expiração de 30 dias. Em produção, use HTTPS e defina `LUMI_HTTPS_ONLY=1`, hospede o backend junto ao site e mantenha `.lumi-private` em armazenamento persistente e não público. A hospedagem precisa preservar o arquivo SQLite entre reinicializações/deploys.

## Acesso do dono

No primeiro acesso, inicie o servidor local e abra `http://localhost:8000/admin`. Cadastre o e-mail e a senha do dono. Essa configuração inicial é aceita somente no próprio computador e apenas uma vez. O painel guarda a senha protegida por hash no SQLite; os cadastros de clientes não recebem acesso administrativo.

Para iniciar o servidor com o Python já instalado no perfil do Windows:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe" server.py
```

Também é possível definir `LUMI_ADMIN_EMAIL` e `LUMI_ADMIN_PASSWORD` no ambiente do servidor para controlar o acesso por configuração de implantação.


## Painel da loja

O painel privado `/admin` também gerencia o catálogo salvo em `products` (cadastro, edição de preço e retirada/reativação), consulta perfis de clientes e lista feedbacks. Os feedbacks são vinculados à conta do cliente e só podem ser enviados por perfis que já tenham ao menos um pedido. Os endpoints administrativos exigem a sessão autenticada do dono.


## InfinitePay

No painel do dono, a aba Pagamentos permite configurar a InfiniteTag e a URL pública HTTPS da loja. O checkout cria links para o fluxo hospedado da InfinitePay, onde o cliente escolhe Pix ou crédito. Cartões não passam nem são armazenados pelo backend Lumi. O retorno e o webhook confirmam cobranças consultando a API de verificação da InfinitePay; para confirmação automática, configure a URL pública HTTPS.
