# Guia de Configuração Manual — DramaRecap Pipeline

Este guia contém as instruções passo a passo necessárias para configurar o novo pipeline de processamento de dramas no GitHub e na sua VPS.

---

## 1. Push Inicial para o GitHub

Como nosso token do MCP possui escopo restrito à conta de desenvolvimento temporária (`Blzofando`), o push direto para o seu GitHub pessoal (`custodiio`) falhou. O repositório Git local já está inicializado e com o commit feito. Siga estes passos para subir o código:

1. Acesse o seu GitHub e crie um repositório **privado** chamado exatamente **`drama-pipeline`** sob a sua conta `custodiio`.
2. Abra o terminal (PowerShell ou Bash) na pasta do projeto `D:\Applications\Drama-pipeline` e execute:
   ```bash
   git push -u origin main
   ```
   *(Como o remote do git local já foi configurado para `https://github.com/custodiio/drama-pipeline.git`, o comando acima fará o envio direto usando suas credenciais locais salvas no Git).*

---

## 2. Configuração do Telegram Bot para Drama

1. Abra o Telegram e inicie uma conversa com o **[@BotFather](https://t.me/BotFather)**.
2. Crie um novo bot com o comando `/newbot`, dê um nome (ex: `DramaRecap Pipeline Bot`) e um username (ex: `DramaRecapBot`).
3. Copie o **HTTP API Token** gerado.

---

## 3. Configuração do Arquivo `.env` na VPS

Na pasta onde rodará o `Drama-pipeline` na sua VPS, crie um arquivo `.env` com a seguinte estrutura. **Atenção:** você pode copiar a maioria dos valores (Google Drive, PostgreSQL, chaves de API, etc.) do arquivo `.env` existente do `AnimeRecap` para facilitar:

```env
# Token do novo Bot do Telegram criado para o Drama
TELEGRAM_BOT_TOKEN="SEU_NOVO_TELEGRAM_BOT_TOKEN"

# Chave secreta de sessão para o painel web (pode ser qualquer string longa aleatória)
SESSION_SECRET="UMA_CHAVE_ALEATORIA_E_SEGURA"

# Seu ID de Telegram (e de outros administradores permitidos) separados por vírgula
AUTHORIZED_TELEGRAM_USERS="7321866230,OUTROS_IDS_SE_HOUVER"

# Banco de Dados PostgreSQL compartilhado (mesmo do AnimeRecap)
DATABASE_URL="postgres://usuario:senha@host:porta/banco?sslmode=require"

# Credenciais do Google Drive (copie as do AnimeRecap)
DRIVE_REFRESH_TOKEN="SEU_DRIVE_REFRESH_TOKEN"
DRIVE_CLIENT_ID="SEU_DRIVE_CLIENT_ID"
DRIVE_CLIENT_SECRET="SEU_DRIVE_CLIENT_SECRET"

# Token do GitHub com permissão de workflow/dispatch para disparar o Kaggle Actions
GITHUB_TOKEN="SEU_GITHUB_PERSONAL_ACCESS_TOKEN"

# Repositório correto do Drama
GITHUB_REPO="custodiio/drama-pipeline"

# URL pública da sua VPS onde o webhook_server estará escutando (porta 8080)
PIPELINE_WEBHOOK_URL="https://animesrecaps.me/dramas/webhook"

# Servidor SEO integrado
SEO_SERVER_URL="http://localhost:3333"
```

---

## 4. Cadastro de Secrets no Repositório do GitHub

Para que o GitHub Actions consiga disparar e injetar as credenciais nos notebooks que rodam no Kaggle, acesse as configurações do seu repositório no GitHub (`Settings > Secrets and variables > Actions > Repository secrets`) e adicione as seguintes secrets (copie os valores das secrets do repositório `anime-pipeline` original):

* **`DATABASE_URL`**: Mesma URL do banco PostgreSQL compartilhado (para atualizar o status das células no painel).
* **`DRIVE_CLIENT_ID`**, **`DRIVE_CLIENT_SECRET`**, **`DRIVE_REFRESH_TOKEN`**: Credenciais de API do Google Drive.
* **`GEMINI_API_KEY`**: Chave de API do Gemini para os prompts e dublagens do notebook Omni.
* **`OPENAI_API_KEY`**: Chave de API da OpenAI.
* **`HF_TOKEN`**: Token do Hugging Face.
* **`PIPELINE_WEBHOOK_URL`**: URL pública do webhook do seu bot de drama na VPS (ex: `https://animesrecaps.me/dramas/webhook`).
* **`KAGGLE_USERNAME_1` a `6`** e **`KAGGLE_KEY_1` a `6`**: Credenciais das suas contas do Kaggle.

---

## 5. Como Iniciar e Colocar em Produção na VPS

Recomendamos usar o **PM2** para gerenciar o processo do bot e do webhook server simultaneamente na VPS:

1. Acesse a pasta do projeto na VPS:
   ```bash
   cd /caminho/do/projeto/Drama-pipeline
   ```
2. Instale as dependências Python:
   ```bash
   pip install -r requirements.txt
   ```
3. Inicie o projeto com PM2:
   ```bash
   pm2 start main.py --name "drama-pipeline" --interpreter python3
   ```
4. Salve a configuração do PM2:
   ```bash
   pm2 save
   ```

Pronto! Agora o pipeline de Drama está 100% isolado de Anime no Google Drive, compartilhando as tabelas e o banco de dados PostgreSQL sem risco de colisão.
