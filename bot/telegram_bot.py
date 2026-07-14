"""
Bot Telegram — Agente de Postagem
Controle completo do pipeline via Telegram.
Protegido por lista de IDs autorizados.
"""

import os
import sys
import asyncio
import tempfile
import logging
import uuid
import hashlib
import time
from functools import wraps

# Força UTF-8 no console do Windows (evita charmap error com emojis)
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from dotenv import load_dotenv

from bot.database import (
    init_db, get_active_project, get_project, get_running_projects,
    format_status, format_cell_status, update_step, set_project_opts,
    get_latest_project
)
from bot.pipeline_controller import PipelineController
from bot.scrapper_downloader import run_scrapper_download

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
SESSION_SECRET = os.getenv("SESSION_SECRET")
if not SESSION_SECRET:
    raise ValueError("❌ ERRO CRÍTICO: SESSION_SECRET não foi configurado no .env!")

# IDs autorizados (separados por vírgula no .env)
_raw_users = os.getenv("AUTHORIZED_TELEGRAM_USERS", "")
AUTHORIZED_USERS = set(
    int(uid.strip()) for uid in _raw_users.split(",")
    if uid.strip().isdigit()
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

controller = PipelineController()

# Estado temporário
user_uploads = {}  # chat_id -> {"video": path, "audio": path, "mask": path}
active_sessions = {}  # session_token -> {"project_id": ..., "chat_id": ..., "created_at": ...}

# Mapeamento de step -> nome amigável
STEP_LABELS = {
    "step_watermark_pt1": "🧹 WM PT1",
    "step_watermark_pt2": "🧹 WM PT2",
    "step_enhancer_pt1": "⚡ Enhancer PT1",
    "step_enhancer_pt2": "⚡ Enhancer PT2",
    "step_omni": "🧠 Omni",
    "step_render_pt1": "🎬 Render PT1",
    "step_render_pt2": "🎬 Render PT2",
    "step_merge": "📦 Merge Final",
}

STATUS_ICONS = {
    "pending": "⏳",
    "running": "🔄",
    "done": "✅",
    "error": "❌",
    "waiting_config": "⚙️",
}


# ═══════════════════════════════════════════════════════════════════
# 🔒 AUTENTICAÇÃO
# ═══════════════════════════════════════════════════════════════════

def authorized(func):
    """Decorator que bloqueia usuários não autorizados."""
    @wraps(func)
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id if update.effective_user else None
        chat_id = update.effective_chat.id if update.effective_chat else None
        text = update.message.text if update.message else "No text"
        logger.info(f"[DEBUG] Recebido comando/evento: func={func.__name__}, user_id={user_id}, chat_id={chat_id}, text={text}")
        if AUTHORIZED_USERS and user_id not in AUTHORIZED_USERS:
            logger.warning(f"Acesso negado para user_id={user_id}")
            if update.message:
                await update.message.reply_text(
                    "🔒 Acesso negado.\n"
                    f"Seu ID: `{user_id}`\n"
                    "Peça ao administrador para adicionar seu ID.",
                    parse_mode="Markdown"
                )
            return
        return await func(update, ctx, *args, **kwargs)
    return wrapper


def gerar_session_token(project_id: str) -> str:
    """Gera token de sessão seguro para o VideoRender."""
    raw = f"{project_id}:{SESSION_SECRET}:{uuid.uuid4().hex}"
    token = hashlib.sha256(raw.encode()).hexdigest()[:24]
    return token

def get_session_link(token: str) -> str:
    # Frontend é servido pelo webhook_server na mesma porta (8080)
    base_url = os.getenv("PIPELINE_WEBHOOK_URL", "http://localhost:8080")
    return f"{base_url}/?session={token}"


# ═══════════════════════════════════════════════════════════════════
# 📋 COMANDOS
# ═══════════════════════════════════════════════════════════════════

@authorized
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Mensagem de boas-vindas com menu visual."""
    buttons = [
        [InlineKeyboardButton("🚀 Novo Projeto Automático", callback_data="new_auto")],
        [InlineKeyboardButton("🛠️ Novo Projeto Manual", callback_data="new_manual")],
        [InlineKeyboardButton("☁️ Iniciar via GDrive (Scrapper)", callback_data="start_usar_drive")],
        [InlineKeyboardButton("📂 Iniciar via Upload Local", callback_data="start_usar_local")]
    ]
    await update.message.reply_text(
        "🎬 *Agente de Postagem — DramaRecap*\n\n"
        "Bem-vindo! Escolha uma opção abaixo após enviar os arquivos, ou use os comandos normais.\n\n"
        "📦 *Envio de arquivos:*\n"
        "  1. Envie o *vídeo* (com marca d'água)\n"
        "  2. Envie o *áudio* (original do vídeo)\n"
        "  3. Clique em um dos botões ou use `/novo Nome`",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


@authorized
async def cmd_myid(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Mostra o User ID do Telegram."""
    uid = update.effective_user.id
    await update.message.reply_text(f"🆔 Seu User ID: `{uid}`", parse_mode="Markdown")


@authorized
async def cmd_upload(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Gera link para upload local de arquivos grandes."""
    base_url = os.getenv("PIPELINE_WEBHOOK_URL", "http://localhost:8080")
    upload_url = f"{base_url}/upload"
    await update.message.reply_text(
        f"📂 *Upload Local*\n\n"
        f"Use o link abaixo no seu navegador para enviar vídeos maiores que 20MB:\n"
        f"👉 [Acessar Painel de Upload]({upload_url})\n\n"
        f"Após o upload, inicie o projeto com:\n"
        f"`/usar_local Nome do Drama`",
        parse_mode="Markdown"
    )



@authorized
async def cmd_teste_enhancer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Comando de teste isolado para o Video Enhancer."""
    chat_id = str(update.effective_chat.id)
    uploads = user_uploads.get(chat_id, {})
    video_path = uploads.get("video")
    
    if not video_path:
        await update.message.reply_text("❌ Envie um vídeo primeiro e depois chame /teste_enhancer.")
        return

    await update.message.reply_text("🚀 Iniciando Teste do Enhancer (só PT1)...")
    
    import uuid, asyncio
    from bot.drive_manager import DriveManager
    from bot.github_actions import dispatch_parallel
    
    pid = str(uuid.uuid4())
    
    async def run_test():
        try:
            drive = DriveManager()
            await update.message.reply_text("⏳ Fazendo upload do video pro Drive (pt1_limpo.mp4)...")
            await asyncio.to_thread(drive.salvar, video_path, "DRAMA/PIPELINE/WATERMARK/pt1_limpo.mp4")
            
            await update.message.reply_text("🚀 Disparando workflow do Enhancer no Kaggle...")
            await asyncio.to_thread(dispatch_parallel, ["enhancer-pt1"], pid)
            
            await update.message.reply_text("✅ Workflow disparado! Acompanhe os logs pelo Kaggle.\nO arquivo gerado será DRAMA/PIPELINE/ENHANCER/pt1_enhanced.mp4")
            
            # Limpa cache do user para não interferir em outros comandos
            user_uploads.pop(chat_id, None)
        except Exception as e:
            await update.message.reply_text(f"❌ Erro no teste: {e}")

    asyncio.create_task(run_test())

@authorized
async def cmd_novo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Inicia um novo projeto."""
    chat_id = str(update.effective_chat.id)

    active = get_active_project(chat_id)
    if active:
        await update.message.reply_text(
            f"⚠️ Já existe um projeto ativo: *{active['project_name']}*\n"
            f"Use /cancel para cancelar ou /status para ver o progresso.",
            parse_mode="Markdown"
        )
        return

    uploads = user_uploads.get(chat_id, {})
    if not uploads.get("video") or not uploads.get("audio"):
        await update.message.reply_text(
            "❌ Envie o *vídeo* e o *áudio* antes de usar /novo!\n\n"
            "1️⃣ Envie o vídeo (com marca d'água)\n"
            "2️⃣ Envie o áudio (original do vídeo)\n"
            "3️⃣ Use: `/novo Nome do Drama`",
            parse_mode="Markdown"
        )
        return

    project_name = " ".join(ctx.args) if ctx.args else f"Projeto_{chat_id[:6]}"
    
    # Prepara o estado temporário
    user_uploads[chat_id]["name"] = project_name
    user_uploads[chat_id]["local"] = False
    user_uploads[chat_id]["watermark"] = True
    user_uploads[chat_id]["enhancer"] = False
    user_uploads[chat_id]["thumbnail"] = True
    user_uploads[chat_id]["manual_mode"] = False
    
    await send_config_menu(update, chat_id)

async def _handle_local_upload_check(update: Update, chat_id: str, project_name: str = None, query=None):
    active = get_active_project(chat_id)
    if active:
        msg = "⚠️ Já existe um projeto ativo. Use /cancel primeiro."
        if query:
            await query.message.reply_text(msg)
        else:
            await update.message.reply_text(msg)
        return

    uploads_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")
    os.makedirs(uploads_dir, exist_ok=True)
    
    files = os.listdir(uploads_dir)
    videos = [f for f in files if any(f.lower().endswith(ext) for ext in [".mp4", ".mkv", ".avi", ".mov"])]
    audios = [f for f in files if any(f.lower().endswith(ext) for ext in [".mp3", ".wav", ".m4a", ".aac"])]
    
    if not videos or not audios:
        msg = (
            f"❌ Arquivos não encontrados!\n"
            f"Coloque 1 vídeo e 1 áudio na pasta:\n`{uploads_dir}`\n"
            f"E tente novamente."
        )
        if query:
            await query.message.reply_text(msg)
        else:
            await update.message.reply_text(msg)
        return

    video_path = os.path.join(uploads_dir, videos[0])
    audio_path = os.path.join(uploads_dir, audios[0])
    
    # Se não foi fornecido um nome, tenta pegar do chat_id
    if not project_name:
        project_name = f"Projeto_{chat_id[:6]}"

    # Verificar timestamp do video local vs ultimo projeto concluido
    mtime = os.path.getmtime(video_path)
    latest_proj = get_latest_project(chat_id)
    
    # Se tiveros um projeto anterior, e a data de conclusao (ou atualizacao) dele for maior que a do mtime do video local
    # Significa que o arquivo de video em uploads/ provavelmente é o MESMO que ja foi processado nesse projeto
    if latest_proj and latest_proj.get("updated_at"):
        try:
            dt = latest_proj["updated_at"]
            if dt.timestamp() > mtime:
                # O vídeo é antigo e já foi processado!
                buttons = [
                    [InlineKeyboardButton("🔄 Retomar Projeto Antigo", callback_data=f"local_resume_old:{latest_proj['id']}")],
                    [InlineKeyboardButton("▶️ Ignorar e Criar Novo (Do Zero)", callback_data="local_force_new")],
                    [InlineKeyboardButton("❌ Cancelar", callback_data="cancel")]
                ]
                text = (
                    f"⚠️ *Aviso de Vídeo Recorrente*\n\n"
                    f"O vídeo atual em `uploads/` parece ser o mesmo que já foi processado no projeto:\n"
                    f"📁 *{latest_proj['project_name']}*\n\n"
                    f"📊 *Status Atual:* {latest_proj['status'].upper()}\n"
                    f"📍 *Última Etapa:* {latest_proj.get('current_step', 'N/A')}\n\n"
                    f"Como cada projeto cria uma pasta única no Google Drive, se você quiser apenas rodar uma etapa específica (ex: Enhancer ou Render) para este vídeo já processado pelo Omni, você deve *retomar o projeto antigo*.\n\n"
                    f"O que deseja fazer?"
                )
                
                # Guardamos as variaveis provisórias pra caso ele clique em "Force New"
                if chat_id not in user_uploads:
                    user_uploads[chat_id] = {}
                user_uploads[chat_id]["video"] = video_path
                user_uploads[chat_id]["audio"] = audio_path
                user_uploads[chat_id]["name"] = project_name
                user_uploads[chat_id]["local"] = True
                user_uploads[chat_id]["watermark"] = True
                user_uploads[chat_id]["enhancer"] = False
                user_uploads[chat_id]["thumbnail"] = True
                user_uploads[chat_id]["manual_mode"] = False
                
                if query:
                    await query.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))
                else:
                    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))
                return
        except Exception as e:
            logger.error(f"Erro ao parsear data {latest_proj['updated_at']}: {e}")
            pass

    # Se o vídeo é novo (ou falhou parse), segue fluxo normal
    if chat_id not in user_uploads:
        user_uploads[chat_id] = {}
        
    user_uploads[chat_id]["video"] = video_path
    user_uploads[chat_id]["audio"] = audio_path
    user_uploads[chat_id]["name"] = project_name
    user_uploads[chat_id]["local"] = True
    user_uploads[chat_id]["watermark"] = True
    user_uploads[chat_id]["enhancer"] = False
    user_uploads[chat_id]["thumbnail"] = True
    user_uploads[chat_id]["manual_mode"] = False

    if query:
        await send_config_menu(update, chat_id, query)
    else:
        await send_config_menu(update, chat_id)


@authorized
async def cmd_usar_local(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Inicia o projeto pegando os arquivos direto da pasta uploads local."""
    chat_id = str(update.effective_chat.id)
    project_name = " ".join(ctx.args) if ctx.args else None
    await _handle_local_upload_check(update, chat_id, project_name)


async def _handle_drive_upload_check(update: Update, chat_id: str, project_name: str = None, query=None):
    active = get_active_project(chat_id)
    if active:
        msg = "⚠️ Já existe um projeto ativo. Use /cancel primeiro."
        if query:
            await query.message.reply_text(msg)
        else:
            await update.message.reply_text(msg)
        return

    uploads_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")
    os.makedirs(uploads_dir, exist_ok=True)
    
    video_path = os.path.join(uploads_dir, "video_original.mp4")
    audio_path = os.path.join(uploads_dir, "drama_audio.mp3")

    msg_loading = "⏳ Conectando ao Google Drive e baixando arquivos de referência enviados pelo Scrapper..."
    if query:
        status_msg = await query.message.reply_text(msg_loading)
    else:
        status_msg = await update.message.reply_text(msg_loading)

    # 1. Apaga arquivos locais antigos na GCP se existirem, para forçar o download limpo
    for p in [video_path, audio_path]:
        if os.path.exists(p):
            try: os.remove(p)
            except Exception as e: logger.warning(f"Erro ao remover arquivo antigo {p}: {e}")

    try:
        # 2. Executa download do Drive em thread (sincrono por debaixo dos panos)
        drive = controller.drive
        audio_success = await asyncio.to_thread(drive.baixar, "DRAMA/AUDIO_DUB/INPUT/drama_audio.mp3", audio_path)
        video_success = await asyncio.to_thread(drive.baixar, "DRAMA/PIPELINE/ATIVO/video_original.mp4", video_path)

        if not audio_success or not video_success:
            await status_msg.edit_text(
                "❌ **Arquivos não encontrados no Google Drive!**\n"
                "Certifique-se de que o Scrapper local já concluiu o download e o envio para o Drive:\n"
                "├ 🎥 `video_original.mp4` em `DRAMA/PIPELINE/ATIVO/`\n"
                "└ 🎵 `drama_audio.mp3` em `DRAMA/AUDIO_DUB/INPUT/`"
            )
            return

        await status_msg.edit_text("✅ Arquivos baixados do Google Drive com sucesso!")

    except Exception as e:
        await status_msg.edit_text(f"❌ Erro ao baixar arquivos do Google Drive:\n`{e}`")
        return

    # Se não foi fornecido um nome, tenta pegar do chat_id
    if not project_name:
        project_name = f"Projeto_{chat_id[:6]}"

    if chat_id not in user_uploads:
        user_uploads[chat_id] = {}
        
    user_uploads[chat_id]["video"] = video_path
    user_uploads[chat_id]["audio"] = audio_path
    user_uploads[chat_id]["name"] = project_name
    user_uploads[chat_id]["local"] = True  # Tratado como local, pois acabamos de baixar do Drive para a VPS
    user_uploads[chat_id]["watermark"] = True
    user_uploads[chat_id]["enhancer"] = False
    user_uploads[chat_id]["thumbnail"] = True
    user_uploads[chat_id]["manual_mode"] = False
    user_uploads[chat_id]["bg_audio"] = False
    user_uploads[chat_id]["srt_type"] = "normal"

    if query:
        await send_config_menu(update, chat_id, query)
    else:
        await send_config_menu(update, chat_id)


@authorized
async def cmd_usar_drive(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Inicia o projeto pegando os arquivos direto do Google Drive (enviados pelo Scrapper)."""
    chat_id = str(update.effective_chat.id)
    project_name = " ".join(ctx.args) if ctx.args else None
    await _handle_drive_upload_check(update, chat_id, project_name)


async def send_config_menu(update, chat_id, query=None):
    """Envia ou atualiza o menu completo de configurações do projeto."""
    opts = user_uploads.get(chat_id)
    if not opts:
        return

    wm_text      = "✅ Remover Marca d'água" if opts.get("watermark", True)   else "❌ Remover Marca d'água"
    enhancer_text = "✅ Aumentar Qualidade"   if opts.get("enhancer", False)  else "❌ Aumentar Qualidade"
    thumb_text   = "✅ Gerar Thumbnail"       if opts.get("thumbnail", True)  else "❌ Gerar Thumbnail"
    bg_text      = "🎵 Áudio: Fundo + Dub"    if opts.get("bg_audio", False)  else "🔇 Áudio: Apenas Dub"
    srt_text     = "📝 SRT: Palavra/Palavra" if opts.get("srt_type", "normal") == "word_by_word" else "📝 SRT: Normal (Fluxo)"
    is_manual    = opts.get("manual_mode", False)
    mode_text    = "🛠️ Modo: Manual"         if is_manual else "🤖 Modo: Automático"

    buttons = [
        [InlineKeyboardButton(wm_text,        callback_data="toggle_wm")],
        [InlineKeyboardButton(enhancer_text,  callback_data="toggle_enhancer")],
        [InlineKeyboardButton(thumb_text,     callback_data="toggle_thumbnail")],
        [InlineKeyboardButton(bg_text,        callback_data="toggle_bgaudio")],
        [InlineKeyboardButton(srt_text,       callback_data="toggle_srt")],
        [InlineKeyboardButton(mode_text,      callback_data="toggle_mode")],
        [InlineKeyboardButton("▶️ Iniciar Projeto", callback_data="start_project")]
    ]
    markup = InlineKeyboardMarkup(buttons)

    mode_desc = "Manual — você dispara cada etapa" if is_manual else "Automático — Omni inicia imediatamente"
    text = (
        f"⚙️ *Configurações do Projeto*\n"
        f"📽️ `{opts['name']}`\n\n"
        f"Modo: *{mode_desc}*\n\n"
        f"Selecione as opções:"
    )

    if query:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)
    else:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=markup)


@authorized
async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Mostra o status visual do projeto ativo."""
    chat_id = str(update.effective_chat.id)
    project = get_active_project(chat_id)

    if not project:
        await update.message.reply_text("❌ Nenhum projeto ativo. Use /novo para iniciar.")
        return

    status_text = format_status(project)

    # Botões inline
    buttons = []
    if project.get("status") == "waiting_config":
        buttons.append([InlineKeyboardButton("⚙️ Abrir VideoRender", callback_data="open_session")])
        buttons.append([InlineKeyboardButton("✅ Config Pronta", callback_data="confirm_config")])
    buttons.append([InlineKeyboardButton("🎯 Disparar Função", callback_data="trigger_menu")])
    buttons.append([InlineKeyboardButton("🔄 Atualizar", callback_data="refresh_status")])

    reply_markup = InlineKeyboardMarkup(buttons) if buttons else None
    await update.message.reply_text(status_text, parse_mode="Markdown", reply_markup=reply_markup)


@authorized
async def cmd_cells(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Mostra o tracking detalhado por célula dos notebooks."""
    chat_id = str(update.effective_chat.id)
    project = get_active_project(chat_id)
    if not project:
        await update.message.reply_text("❌ Nenhum projeto ativo.")
        return
    pid = str(project["id"])
    notebook_filter = " ".join(ctx.args) if ctx.args else None
    cells_text = format_cell_status(pid, notebook_filter)
    await update.message.reply_text(cells_text, parse_mode="Markdown")


@authorized
async def cmd_sessao(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Gera um link de sessão para o VideoRender."""
    chat_id = str(update.effective_chat.id)
    project = get_active_project(chat_id)

    if not project:
        await update.message.reply_text("❌ Nenhum projeto ativo.")
        return

    pid = str(project["id"])
    token = gerar_session_token(pid)
    active_sessions[token] = {
        "project_id": pid,
        "chat_id": chat_id,
        "created_at": time.time()
    }

    session_link = get_session_link(token)

    await update.message.reply_text(
        f"🎬 Sessão VideoRender\n\n"
        f"Projeto: {project['project_name']}\n"
        f"⏰ Válida por 2 horas\n\n"
        f"🔗 {session_link}"
    )


@authorized
async def cmd_config(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Marca a configuração como pronta e dispara render."""
    chat_id = str(update.effective_chat.id)
    project = get_active_project(chat_id)

    if not project:
        await update.message.reply_text("❌ Nenhum projeto ativo.")
        return

    pid = str(project["id"])

    if project.get("step_enhancer_pt1") != "done" or project.get("step_enhancer_pt2") != "done":
        update_step(pid, "step_config_ready", "done", "Config pronta, aguardando enhancer")
        await update.message.reply_text(
            "✅ Config marcada como pronta!\n"
            "⏳ Aguardando Video Enhancer finalizar...",
            parse_mode="Markdown"
        )
    else:
        controller.disparar_render(pid)
        await update.message.reply_text(
            "✅ Config pronta! 🎬 Renderização disparada (PT1 + PT2)!\n"
            "📊 Use /status para acompanhar.",
            parse_mode="Markdown"
        )


@authorized
async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Cancela o projeto ativo."""
    chat_id = str(update.effective_chat.id)
    project = get_active_project(chat_id)
    if not project:
        await update.message.reply_text("❌ Nenhum projeto ativo para cancelar.")
        return

    pid = str(project["id"])
    update_step(pid, "step_upload", "error", "Cancelado pelo usuário")
    await update.message.reply_text(
        f"🛑 Projeto *{project['project_name']}* cancelado.",
        parse_mode="Markdown"
    )


# ═══════════════════════════════════════════════════════════════════
# 🔘 CALLBACKS (botões inline)
# ═══════════════════════════════════════════════════════════════════

@authorized
async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Trata cliques nos botões inline."""
    query = update.callback_query
    await query.answer()

    chat_id = str(query.message.chat.id)
    data = query.data

    if data == "start_usar_local":
        await _handle_local_upload_check(update, chat_id, query=query)
        return

    elif data == "start_usar_drive":
        await _handle_drive_upload_check(update, chat_id, query=query)
        return

    elif data == "local_force_new":
        await send_config_menu(update, chat_id, query)
        return

    elif data.startswith("local_resume_old:"):
        pid = data.split(":")[1]
        from bot.database import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("UPDATE pipeline_projects SET status = 'paused' WHERE id = %s::uuid", (pid,))
        conn.commit()
        cur.close()
        conn.close()
        
        await query.edit_message_text(f"✅ Projeto {pid[:8]} retomado!")
        # Exibir painel de status automaticamente
        project = get_project(pid)
        status_text = format_status(project)
        buttons = []
        if project.get("status") == "waiting_config":
            buttons.append([InlineKeyboardButton("⚙️ Abrir VideoRender", callback_data="open_session")])
            buttons.append([InlineKeyboardButton("✅ Config Pronta", callback_data="confirm_config")])
        buttons.append([InlineKeyboardButton("🎯 Disparar Função", callback_data="trigger_menu")])
        buttons.append([InlineKeyboardButton("🔄 Atualizar", callback_data="refresh_status")])
        reply_markup = InlineKeyboardMarkup(buttons) if buttons else None
        
        # Envia como nova mensagem para nao misturar parse mode
        await query.message.reply_text(status_text, parse_mode="Markdown", reply_markup=reply_markup)
        return

    if data == "new_auto" or data == "new_manual":
        if chat_id not in user_uploads or not user_uploads[chat_id].get("video") or not user_uploads[chat_id].get("audio"):
            await query.edit_message_text("❌ Envie vídeo e áudio primeiro!")
            return
        
        active = get_active_project(chat_id)
        if active:
            await query.edit_message_text("⚠️ Já existe um projeto ativo. Use /cancel primeiro.")
            return
            
        user_uploads[chat_id]["name"] = f"Projeto_{chat_id[:6]}"
        user_uploads[chat_id]["local"] = False
        user_uploads[chat_id]["watermark"] = True
        user_uploads[chat_id]["enhancer"] = False
        user_uploads[chat_id]["thumbnail"] = True
        user_uploads[chat_id]["manual_mode"] = (data == "new_manual")
        await send_config_menu(None, chat_id, query)
        
    elif data == "toggle_wm":
        if chat_id in user_uploads:
            user_uploads[chat_id]["watermark"] = not user_uploads[chat_id].get("watermark", True)
            await send_config_menu(None, chat_id, query)
            
    elif data == "toggle_enhancer":
        if chat_id in user_uploads:
            user_uploads[chat_id]["enhancer"] = not user_uploads[chat_id].get("enhancer", False)
            await send_config_menu(None, chat_id, query)

    elif data == "toggle_thumbnail":
        if chat_id in user_uploads:
            user_uploads[chat_id]["thumbnail"] = not user_uploads[chat_id].get("thumbnail", True)
            await send_config_menu(None, chat_id, query)

    elif data == "toggle_mode":
        if chat_id in user_uploads:
            user_uploads[chat_id]["manual_mode"] = not user_uploads[chat_id].get("manual_mode", False)
            await send_config_menu(None, chat_id, query)
            
    elif data == "toggle_bgaudio":
        if chat_id in user_uploads:
            user_uploads[chat_id]["bg_audio"] = not user_uploads[chat_id].get("bg_audio", False)
            await send_config_menu(None, chat_id, query)

    elif data == "toggle_srt":
        if chat_id in user_uploads:
            current_srt = user_uploads[chat_id].get("srt_type", "normal")
            user_uploads[chat_id]["srt_type"] = "word_by_word" if current_srt == "normal" else "normal"
            await send_config_menu(None, chat_id, query)
            
    elif data == "start_project":
        if chat_id not in user_uploads:
            await query.edit_message_text("❌ Sessão expirada. Envie os arquivos novamente.")
            return
            
        opts = user_uploads[chat_id]
        
        await query.edit_message_text(
            f"🚀 Iniciando projeto: *{opts['name']}*\n"
            f"📤 Fazendo upload e dividindo vídeo...",
            parse_mode="Markdown"
        )

        try:
            manual_mode       = opts.get("manual_mode", False)
            thumbnail_enabled = opts.get("thumbnail", True)
            bg_audio          = opts.get("bg_audio", False)
            srt_type          = opts.get("srt_type", "normal")

            if manual_mode:
                project = await asyncio.to_thread(
                    controller.iniciar_projeto_manual,
                    project_name=opts["name"],
                    chat_id=chat_id,
                    video_path=opts["video"],
                    audio_path=opts["audio"],
                    mask_path=opts.get("mask"),
                    opts=opts
                )
            else:
                project = await asyncio.to_thread(
                    controller.iniciar_projeto,
                    project_name=opts["name"],
                    chat_id=chat_id,
                    video_path=opts["video"],
                    audio_path=opts["audio"],
                    mask_path=opts.get("mask"),
                    opts=opts
                )
            pid = str(project["id"])

            # Salvar opções no banco para o notifier consultar depois
            set_project_opts(pid, manual_mode, thumbnail_enabled, bg_audio, srt_type)

            token = gerar_session_token(pid)
            active_sessions[token] = {"project_id": pid, "chat_id": chat_id, "created_at": time.time()}
            session_link = get_session_link(token)

            if not manual_mode:
                controller.disparar_omni_imediatamente(pid)
                thumb_info = "\n🖼️ Thumbnail será gerada automaticamente após a tradução." if thumbnail_enabled else ""
                msg_text = (
                    f"✅ Upload e Divisão Concluídos!\n\n"
                    f"🔄 Disparando a Dublagem (Omni)...{thumb_info}\n\n"
                    f"⚙\ufe0f Sessão de Configuração de Legenda:\n"
                    f"🎬 Abrir VideoRender:\n{session_link}\n\n"
                    f"📊 Use /status para acompanhar."
                )
            else:
                msg_text = (
                    f"🛠\ufe0f Projeto Manual Inicializado!\n\n"
                    f"✅ Upload e Divisão Concluídos.\n"
                    f"Nenhuma função foi disparada automaticamente.\n"
                    f"🎬 Sessão VideoRender:\n{session_link}\n\n"
                    f"Use /status e clique em '🎯 Disparar Função' para rodar os blocos."
                )

            await query.message.reply_text(msg_text)
            user_uploads.pop(chat_id, None)

        except Exception as e:
            await query.message.reply_text(f"❌ Erro ao iniciar projeto:\n`{e}`", parse_mode="Markdown")

    elif data == "refresh_status":
        project = get_active_project(chat_id)
        if project:
            status_text = format_status(project)
            buttons = []
            if project.get("status") == "waiting_config":
                buttons.append([InlineKeyboardButton("⚙️ Abrir VideoRender", callback_data="open_session")])
                buttons.append([InlineKeyboardButton("✅ Config Pronta", callback_data="confirm_config")])
            buttons.append([InlineKeyboardButton("🎯 Disparar Função", callback_data="trigger_menu")])
            buttons.append([InlineKeyboardButton("🔄 Atualizar", callback_data="refresh_status")])
            try:
                await query.edit_message_text(status_text, parse_mode="Markdown",
                                              reply_markup=InlineKeyboardMarkup(buttons))
            except Exception as e:
                if "Message is not modified" in str(e):
                    await query.answer("Status já está atualizado!", show_alert=False)
                else:
                    pass

    elif data == "open_session":
        project = get_active_project(chat_id)
        if project:
            pid = str(project["id"])
            token = gerar_session_token(pid)
            active_sessions[token] = {"project_id": pid, "chat_id": chat_id, "created_at": time.time()}
            session_link = get_session_link(token)
            await query.message.reply_text(
                f"🎬 Abrir VideoRender:\n{session_link}"
            )

    elif data == "confirm_config":
        project = get_active_project(chat_id)
        if project:
            pid = str(project["id"])
            if project.get("step_enhancer_pt1") != "done" or project.get("step_enhancer_pt2") != "done":
                await query.message.reply_text("⏳ Aguardando Enhancer finalizar...")
            else:
                controller.disparar_render(pid)
                await query.message.reply_text("🎬 Renderização disparada!")

    # -------- DISPARO MANUAL --------
    elif data == "trigger_menu":
        project = get_active_project(chat_id)
        if not project:
            await query.edit_message_text("❌ Sem projeto ativo.")
            return
        buttons = [
            [InlineKeyboardButton("🧠 Omni", callback_data="trigger_omni"),
             InlineKeyboardButton("🧹 Watermark", callback_data="trigger_wm_menu")],
            [InlineKeyboardButton("⚡ Enhancer", callback_data="trigger_enhancer_menu"),
             InlineKeyboardButton("🎬 Render", callback_data="trigger_render_menu")],
            [InlineKeyboardButton("📦 Merge", callback_data="trigger_merge"),
             InlineKeyboardButton("🌐 SEO & Thumb", callback_data="trigger_seo")],
            [InlineKeyboardButton("🔙 Voltar", callback_data="refresh_status")]
        ]
        try:
            await query.edit_message_text("🎯 *Menu de Disparo*\nQual função deseja iniciar?", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))
        except Exception:
            pass

    elif data == "trigger_seo":
        project = get_active_project(chat_id)
        if project:
            pid = str(project["id"])
            _chat_id = str(chat_id)
            import threading

            def _disparar_seo_manual():
                """Dispara SEO e Thumbnail diretamente, ignorando manual_mode."""
                import requests as req
                SEO_SERVER_URL_LOCAL = os.getenv("SEO_SERVER_URL", "http://localhost:3333")

                def _send(text, md="Markdown", message_id=None):
                    if message_id:
                        return req.post(
                            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/editMessageText",
                            json={"chat_id": _chat_id, "message_id": message_id, "text": text, "parse_mode": md},
                            timeout=10
                        ).json()
                    else:
                        return req.post(
                            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                            json={"chat_id": _chat_id, "text": text, "parse_mode": md},
                            timeout=10
                        ).json()

                try:
                    res_msg = _send("⏳ *gerando seo decrição*")
                    msg_id = res_msg.get("result", {}).get("message_id")
                    
                    guia, roteiro, identificacao = controller.gerar_seo_automatico(pid)
                    if not guia:
                        _send("❌ Erro ao gerar descrição SEO.", message_id=msg_id)
                        return

                    _send("⏳ *gerando thumbnails*", message_id=msg_id)
                    
                    # Passamos telegram info para que o server continue atualizando o message_id!
                    token = controller.preparar_sessao_seo(pid, _chat_id, telegram_info={
                        "token": TELEGRAM_BOT_TOKEN,
                        "message_id": msg_id,
                        "guia": guia
                    })
                    
                    if not token:
                        _send("❌ Erro ao iniciar sessão SEO.", message_id=msg_id)
                        
                except Exception as e:
                    logger.error(f"[SEO Manual] Erro: {e}")
                    try:
                        req.post(
                            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                            json={"chat_id": _chat_id, "text": f"❌ Erro ao gerar SEO: {e}"},
                            timeout=10
                        )
                    except Exception:
                        pass

            threading.Thread(target=_disparar_seo_manual, daemon=True).start()
            try:
                await query.edit_message_text("🚀 *SEO & Thumb disparado!* Aguarde a mensagem com o guia...")
            except Exception:
                pass

    elif data == "trigger_omni":
        project = get_active_project(chat_id)
        if project:
            pid = str(project["id"])
            ok, err = controller.check_omni_ready()
            if not ok:
                await query.answer(err, show_alert=True)
                return
            controller.disparar_omni_imediatamente(pid)
            await query.edit_message_text("🚀 Omni disparado!")

    elif data == "trigger_merge":
        project = get_active_project(chat_id)
        if project:
            pid = str(project["id"])
            ok, err = controller.check_merge_ready()
            if not ok:
                await query.answer(err, show_alert=True)
                return
            controller.disparar_merge(pid)
            await query.edit_message_text("🚀 Merge disparado!")

    elif data in ["trigger_wm_menu", "trigger_enhancer_menu", "trigger_render_menu"]:
        prefix = data.replace("_menu", "")
        buttons = []
        for i in range(1, 6):
            buttons.append([InlineKeyboardButton(f"Parte {i}", callback_data=f"{prefix}_{i}")])
        buttons.append([InlineKeyboardButton("Todas as Partes", callback_data=f"{prefix}_all")])
        buttons.append([InlineKeyboardButton("🔙 Voltar", callback_data="trigger_menu")])
        names = {"trigger_wm": "Watermark", "trigger_enhancer": "Enhancer", "trigger_render": "Render"}
        await query.edit_message_text(f"🎯 *{names[prefix]}*\nEscolha a parte:", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))

    elif data.startswith("trigger_wm_"):
        project = get_active_project(chat_id)
        if not project: return
        pid = str(project["id"])
        ok, err = controller.check_watermark_ready()
        if not ok:
            await query.answer(err, show_alert=True)
            return
        from bot.github_actions import dispatch_parallel
        part = data.split("_")[-1]
        if part == "all":
            controller.disparar_watermark(pid)
            await query.edit_message_text("🚀 Watermark disparado para todas as partes!")
        else:
            from bot.database import update_step
            update_step(pid, f"step_watermark_pt{part}", "running")
            dispatch_parallel([f"wm-pt{part}"], pid)
            await query.edit_message_text(f"🚀 Watermark PT {part} disparado!")

    elif data.startswith("trigger_enhancer_"):
        project = get_active_project(chat_id)
        if not project: return
        pid = str(project["id"])
        part = data.split("_")[-1]
        p_val = int(part) if part != "all" else None
        ok, err = controller.check_enhancer_ready(p_val)
        if not ok:
            await query.answer(err, show_alert=True)
            return
        from bot.github_actions import dispatch_parallel
        if part == "all":
            controller.disparar_enhancer(pid)
            await query.edit_message_text("🚀 Enhancer disparado para todas as partes!")
        else:
            from bot.database import update_step
            update_step(pid, f"step_enhancer_pt{part}", "running")
            dispatch_parallel([f"enhancer-pt{part}"], pid)
            await query.edit_message_text(f"🚀 Enhancer PT {part} disparado!")

    elif data.startswith("trigger_render_"):
        project = get_active_project(chat_id)
        if not project: return
        pid = str(project["id"])
        part = data.split("_")[-1]
        p_val = int(part) if part != "all" else None
        ok, err = controller.check_render_ready(p_val)
        if not ok:
            await query.answer(err, show_alert=True)
            return
        from bot.github_actions import dispatch_parallel
        if part == "all":
            controller.disparar_render(pid)
            await query.edit_message_text("🚀 Render disparado para todas as partes!")
        else:
            from bot.database import update_step
            update_step(pid, f"step_render_pt{part}", "running")
            dispatch_parallel([f"render-pt{part}"], pid)
            await query.edit_message_text(f"🚀 Render PT {part} disparado!")



# ═══════════════════════════════════════════════════════════════════
# 📁 HANDLERS DE ARQUIVO (com auth)
# ═══════════════════════════════════════════════════════════════════

@authorized
async def handle_video(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Recebe vídeo do usuário."""
    chat_id = str(update.effective_chat.id)
    message = update.message

    file_obj = message.video or message.document
    if not file_obj:
        return

    file_name = getattr(file_obj, "file_name", "video.mp4") or "video.mp4"
    if not any(file_name.lower().endswith(ext) for ext in [".mp4", ".mkv", ".avi", ".mov", ".webm"]):
        return

    msg = await message.reply_text(f"⬇️ Baixando vídeo: `{file_name}`...", parse_mode="Markdown")

    temp_dir = tempfile.mkdtemp(prefix="drama_pipeline_")
    local_path = os.path.join(temp_dir, file_name)

    try:
        if file_obj.file_size and file_obj.file_size > 20 * 1024 * 1024:
            await msg.edit_text("❌ *Erro*: O Telegram limita o download de bots a 20MB. Por favor, envie um vídeo menor ou compactado.", parse_mode="Markdown")
            return

        tg_file = await ctx.bot.get_file(file_obj.file_id)
        
        import httpx
        import time
        async with httpx.AsyncClient() as client:
            async with client.stream("GET", tg_file.file_path) as response:
                response.raise_for_status()
                total_size = int(response.headers.get("Content-Length", file_obj.file_size or 0))
                downloaded = 0
                last_update = time.time()
                
                with open(local_path, "wb") as f:
                    async for chunk in response.aiter_bytes(chunk_size=8192 * 4):
                        f.write(chunk)
                        downloaded += len(chunk)
                        now = time.time()
                        if total_size and (now - last_update > 2.0):
                            percent = (downloaded / total_size) * 100
                            try:
                                await msg.edit_text(f"⬇️ Baixando vídeo: `{file_name}`\n⏳ *{percent:.1f}%* ({downloaded//1024//1024}MB / {total_size//1024//1024}MB)", parse_mode="Markdown")
                            except Exception:
                                pass
                            last_update = now
    except Exception as e:
        await msg.edit_text(f"❌ Erro ao baixar vídeo: `{e}`", parse_mode="Markdown")
        return

    if chat_id not in user_uploads:
        user_uploads[chat_id] = {}
    user_uploads[chat_id]["video"] = local_path

    has_audio = user_uploads[chat_id].get("audio")
    await msg.edit_text(
        f"✅ Vídeo recebido: `{file_name}`\n"
        f"{'📦 Pronto! Use /novo <nome> para iniciar.' if has_audio else '📎 Agora envie o *áudio* original.'}",
        parse_mode="Markdown"
    )


@authorized
async def handle_audio(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Recebe áudio do usuário."""
    chat_id = str(update.effective_chat.id)
    message = update.message

    file_obj = message.audio or message.voice or message.document
    if not file_obj:
        return

    file_name = getattr(file_obj, "file_name", "audio.mp3") or "audio.mp3"
    if not any(file_name.lower().endswith(ext) for ext in [".mp3", ".wav", ".m4a", ".ogg", ".aac"]):
        mime = getattr(file_obj, "mime_type", "") or ""
        if "audio" not in mime:
            return

    msg = await message.reply_text(f"⬇️ Baixando áudio: `{file_name}`...", parse_mode="Markdown")

    temp_dir = tempfile.mkdtemp(prefix="drama_pipeline_")
    local_path = os.path.join(temp_dir, file_name)

    try:
        if file_obj.file_size and file_obj.file_size > 20 * 1024 * 1024:
            await msg.edit_text("❌ *Erro*: O Telegram limita o download de bots a 20MB. Por favor, envie um áudio menor ou compactado.", parse_mode="Markdown")
            return

        tg_file = await ctx.bot.get_file(file_obj.file_id)
        
        import httpx
        import time
        async with httpx.AsyncClient() as client:
            async with client.stream("GET", tg_file.file_path) as response:
                response.raise_for_status()
                total_size = int(response.headers.get("Content-Length", file_obj.file_size or 0))
                downloaded = 0
                last_update = time.time()
                
                with open(local_path, "wb") as f:
                    async for chunk in response.aiter_bytes(chunk_size=8192 * 4):
                        f.write(chunk)
                        downloaded += len(chunk)
                        now = time.time()
                        if total_size and (now - last_update > 2.0):
                            percent = (downloaded / total_size) * 100
                            try:
                                await msg.edit_text(f"⬇️ Baixando áudio: `{file_name}`\n⏳ *{percent:.1f}%* ({downloaded//1024//1024}MB / {total_size//1024//1024}MB)", parse_mode="Markdown")
                            except Exception:
                                pass
                            last_update = now
    except Exception as e:
        await msg.edit_text(f"❌ Erro ao baixar áudio: `{e}`", parse_mode="Markdown")
        return

    if chat_id not in user_uploads:
        user_uploads[chat_id] = {}
    user_uploads[chat_id]["audio"] = local_path

    has_video = user_uploads[chat_id].get("video")
    msg_ready = "📦 Pronto! Use /novo <nome> para iniciar."
    msg_wait = "📎 Agora envie o *vídeo* com marca d'água."
    await msg.edit_text(
        f"✅ Áudio recebido: `{file_name}`\n"
        f"{msg_ready if has_video else msg_wait}",
        parse_mode="Markdown"
    )


@authorized
async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Recebe máscara (imagem) do usuário."""
    chat_id = str(update.effective_chat.id)
    message = update.message

    photo = message.photo[-1] if message.photo else None
    if not photo:
        return

    temp_dir = tempfile.mkdtemp(prefix="drama_pipeline_")
    local_path = os.path.join(temp_dir, "mask.png")

    tg_file = await ctx.bot.get_file(photo.file_id)
    await tg_file.download_to_drive(local_path)

    if chat_id not in user_uploads:
        user_uploads[chat_id] = {}
    user_uploads[chat_id]["mask"] = local_path

    await message.reply_text("✅ Máscara de watermark recebida!")


@authorized
async def handle_text_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Trata mensagens de texto enviadas (links de Douyin/Bilibili)."""
    chat_id = str(update.effective_chat.id)
    text = update.message.text.strip()
    
    import re
    douyin_match = re.search(r"(https?://\S*douyin\.com\S*)", text)
    bilibili_match = re.search(r"(https?://\S*(bilibili\.com|b23\.tv)\S*)", text)
    
    if douyin_match or bilibili_match:
        url = (douyin_match or bilibili_match).group(1)
        asyncio.create_task(
            run_scrapper_download(
                chat_id=chat_id,
                context=ctx,
                url=url,
                user_uploads=user_uploads
            )
        )
        return
        
    await update.message.reply_text(
        "❓ Comando ou link não reconhecido. Envie um link válido do Douyin ou Bilibili para baixar automaticamente o drama!"
    )


# ═══════════════════════════════════════════════════════════════════
# 🌐 API SESSÃO (para o VideoRender chamar)
# ═══════════════════════════════════════════════════════════════════

def validar_sessao(token: str):
    """Valida e retorna dados da sessão (usado pelo webhook_server)."""
    session = active_sessions.get(token)
    if not session:
        return None
    # Expirar após 2 horas
    if time.time() - session["created_at"] > 7200:
        active_sessions.pop(token, None)
        return None
    return session


import requests

# ═══════════════════════════════════════════════════════════════════
# 🚀 INICIALIZAÇÃO
# ═══════════════════════════════════════════════════════════════════

def notificar_omni_concluido(project_id, chat_id, project_name):
    """Callback chamado pelo PipelineController quando o Omni termina."""
    token = gerar_session_token(project_id)
    active_sessions[token] = {
        "project_id": project_id,
        "chat_id": chat_id,
        "created_at": time.time()
    }
    session_link = get_session_link(token)
    
    msg = (
        f"✅ Omni-Drama-Ver Concluído!\n\n"
        f"O projeto {project_name} teve suas legendas e marcações extraídas com sucesso.\n\n"
        f"🎨 Próximo passo:\n"
        f"Configure o visual da renderização.\n"
        f"Ao terminar, clique em 'Salvar no Pipeline'.\n\n"
        f"🔗 {session_link}"
    )
    
    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(api_url, json={
        "chat_id": chat_id,
        "text": msg
    })

def main():
    """Inicia o bot."""
    if not TELEGRAM_BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN não configurado no .env!")
        return

    if not AUTHORIZED_USERS:
        print("AVISO: AUTHORIZED_TELEGRAM_USERS nao configurado! Bot aberto a todos.")
    else:
        print(f"Usuarios autorizados: {AUTHORIZED_USERS}")

    init_db()

    from bot.webhook_server import start_webhook_server, set_session_validator, set_seo_notifier
    set_session_validator(validar_sessao)
    start_webhook_server()

    SEO_SERVER_URL = os.getenv("SEO_SERVER_URL", "http://localhost:3333")
    FRONTEND_URL   = os.getenv("FRONTEND_URL", "http://localhost:8080")

    def _seo_notifier_callback(project_id):
        """
        Chamado quando cel5 finaliza.
        - Se projeto foi modo MANUAL → ignora (usuário disparou tudo manualmente)
        - Se modo AUTOMÁTICO → gera SEO e, se thumbnail_enabled, envia link de sessão
        """
        import requests as req
        proj = get_project(project_id)
        if not proj:
            return

        # Verificar modo: se manual, não fazer nada
        if proj.get("manual_mode", False):
            logger.info(f"[SEO] Projeto {project_id} é manual — cel5 ignorado pelo notifier.")
            return

        chat_id = proj.get("telegram_chat_id")
        thumbnail_enabled = proj.get("thumbnail_enabled", True)

        def _send_telegram(text, parse_mode="Markdown", message_id=None):
            if message_id:
                return req.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/editMessageText",
                    json={"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": parse_mode},
                    timeout=10
                ).json()
            else:
                return req.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                    json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode},
                    timeout=10
                ).json()

        try:
            res_msg = _send_telegram("⏳ *gerando seo decrição*")
            msg_id = res_msg.get("result", {}).get("message_id")
            
            guia, roteiro, identificacao = controller.gerar_seo_automatico(project_id)

            if not guia:
                _send_telegram("⚠️ Não foi possível gerar o guia SEO automaticamente.", message_id=msg_id)
                return

            # Sessão Thumbnail — só envia se thumbnail_enabled
            if thumbnail_enabled:
                try:
                    _send_telegram("⏳ *gerando thumbnails*", message_id=msg_id)
                    token = controller.preparar_sessao_seo(project_id, chat_id, telegram_info={
                        "token": TELEGRAM_BOT_TOKEN,
                        "message_id": msg_id,
                        "guia": guia
                    })
                    if not token:
                        _send_telegram("❌ Erro ao iniciar sessão SEO.", message_id=msg_id)
                except Exception as e:
                    logger.error(f"[SEO] Erro ao criar sessão thumbnail: {e}")
                    _send_telegram(f"❌ Erro na thumbnail: {e}", message_id=msg_id)
            else:
                logger.info(f"[SEO] Thumbnail desabilitado para projeto {project_id} — link não enviado.")

        except Exception as e:
            logger.error(f"[SEO] Erro no notifier: {e}")
            try:
                _send_telegram(f"❌ Erro ao gerar SEO: {e}")
            except Exception:
                pass

    set_seo_notifier(_seo_notifier_callback)

    controller.on_omni_done = notificar_omni_concluido

    # Polling periódico via thread (não depende de job_queue extra)
    import threading

    def _pipeline_poll_loop():
        """Thread que verifica o banco a cada 30s e avança o pipeline."""
        while True:
            try:
                projects = get_running_projects()
                for proj in projects:
                    pid = str(proj["id"])
                    # Se antes era running e agora o controller.verificar_e_avancar marcar como completed, podemos checar
                    status_antes = proj.get("status")
                    controller.verificar_e_avancar(pid)
                    
                    from bot.database import get_project
                    proj_depois = get_project(pid)
                    if status_antes != "completed" and proj_depois and proj_depois.get("status") == "completed":
                        # Projeto acabou de finalizar!
                        chat_id = proj_depois["chat_id"]
                        link = controller.drive.get_file_link("DRAMA/PIPELINE/FINAL/drama_final.mp4")
                        if link:
                            msg = f"✅ *Processo Finalizado!*\nO vídeo final está pronto:\n🔗 [Acessar no Drive]({link})"
                        else:
                            msg = f"✅ *Processo Finalizado!*\nO vídeo final está na pasta DRAMA/PIPELINE/FINAL no Drive."
                        
                        import requests
                        api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                        requests.post(api_url, json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"})
            except Exception as e:
                logger.error(f"Erro no polling do pipeline: {e}")
            time.sleep(30)

    poll_thread = threading.Thread(target=_pipeline_poll_loop, daemon=True)
    poll_thread.start()
    print("Pipeline polling ativo (30s via thread).")

    async def post_init(application: Application):
        await application.bot.set_my_commands([
            BotCommand("start", "Mensagem de boas-vindas"),
            BotCommand("novo", "Inicia novo projeto"),
            BotCommand("status", "Status do projeto ativo"),
            BotCommand("cells", "Tracking por célula"),
            BotCommand("sessao", "Gera link do VideoRender"),
            BotCommand("config", "Confirma config (dispara render)"),
            BotCommand("upload", "Obter link para upload local"),
            BotCommand("cancel", "Cancela projeto ativo"),
            BotCommand("usar_local", "Iniciar projeto com arquivos do PC"),
            BotCommand("usar_drive", "Iniciar projeto com arquivos do Google Drive"),
        ])
        print("Comandos do Telegram registrados no menu azul!")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    # Comandos
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("novo", cmd_novo))
    app.add_handler(CommandHandler("teste_enhancer", cmd_teste_enhancer))
    app.add_handler(CommandHandler("usar_local", cmd_usar_local))
    app.add_handler(CommandHandler("usar_drive", cmd_usar_drive))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("cells", cmd_cells))
    app.add_handler(CommandHandler("sessao", cmd_sessao))
    app.add_handler(CommandHandler("config", cmd_config))
    app.add_handler(CommandHandler("upload", cmd_upload))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("myid", cmd_myid))

    # Callbacks (botões inline)
    app.add_handler(CallbackQueryHandler(handle_callback))

    # Handlers de arquivo
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_video))
    app.add_handler(MessageHandler(
        filters.AUDIO | filters.VOICE | filters.Document.AUDIO, handle_audio
    ))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

    print("Bot Telegram iniciado! Ctrl+C para parar.")
    import asyncio
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
