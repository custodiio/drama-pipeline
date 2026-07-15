"""
Bot Telegram — Agente de Postagem
Controle completo do pipeline via Telegram.
Protegido por lista de IDs autorizados.
"""

import os
import sys
import html
import asyncio
import tempfile
import logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)
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
    CallbackQueryHandler, ContextTypes, filters,
    ConversationHandler
)
from dotenv import load_dotenv

from bot.database import (
    init_db, get_active_project, get_project, get_running_projects,
    format_status, format_cell_status, update_step, set_project_opts,
    get_latest_project
)
from bot.pipeline_controller import PipelineController
from bot.scrapper_downloader import run_scrapper_download, finalize_scrapper_download

load_dotenv()

# Estados da conversação de postagem
(SELECT_PLATFORMS, SELECT_YOUTUBE_TITLE, INPUT_YOUTUBE_TITLE_MANUAL, 
 SELECT_SHORTS_TITLE, INPUT_SHORTS_TITLE_MANUAL, SELECT_YOUTUBE_PRIVACY, 
 SELECT_INSTAGRAM_SCHEDULING, INPUT_INSTAGRAM_TIME, SELECT_TIKTOK_PRIVACY, 
 SELECT_TIKTOK_SCHEDULING, INPUT_TIKTOK_TIME, CONFIRM_POST, 
 INPUT_UNIFIED_SCHEDULE_TIME) = range(13)

import json
import shutil

# Injeta PostRecap no path para uploader de redes sociais
POSTRECAP_PATH = "/home/ubuntu/apps/Post_recap"
if os.path.exists(POSTRECAP_PATH) and POSTRECAP_PATH not in sys.path:
    sys.path.insert(0, POSTRECAP_PATH)

try:
    import tiktok_service
    import youtube_uploader
    has_postrecap = True
except ImportError:
    has_postrecap = False
    logger = logging.getLogger(__name__)
    logger.warning("Aviso: Post_recap nao encontrado no path!")

def get_user_connections(email: str):
    """Retorna as conexões ativas de redes sociais de um e-mail do banco de dados users.db."""
    db_path = "/home/ubuntu/apps/database/users.db"
    if not os.path.exists(db_path):
        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "users.db")
        if not os.path.exists(db_path):
            return {"youtube": None, "tiktok": None}

    import sqlite3
    connections = {"youtube": None, "tiktok": None}
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # YouTube
        try:
            cursor.execute("SELECT channel_name FROM youtube_connections WHERE email = ?", (email,))
            row = cursor.fetchone()
            if row:
                connections["youtube"] = row[0]
        except Exception as e:
            pass
            
        # TikTok
        try:
            cursor.execute("SELECT username FROM tiktok_connections WHERE email = ?", (email,))
            row = cursor.fetchone()
            if row:
                connections["tiktok"] = row[0]
        except Exception as e:
            pass
            
        conn.close()
    except Exception as e:
        logger.error(f"Erro ao ler conexoes do banco users.db: {e}")
    return connections

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


from bot.db_postagem import init_db as init_db_postagem
init_db_postagem()

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
        [InlineKeyboardButton("📂 Iniciar via Upload Local", callback_data="start_usar_local")],
        [InlineKeyboardButton("📢 Menu de Postagem 🚀", callback_data="menu_postagem")]
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

    elif data.startswith("scrapper_speed:"):
        adjust_speed = (data.split(":")[-1] == "yes")
        pending = ctx.user_data.pop("pending_scrapper_download", None)
        if not pending:
            await query.answer("Sessão de download expirada ou não encontrada.", show_alert=True)
            return
            
        asyncio.create_task(
            finalize_scrapper_download(
                chat_id=chat_id,
                context=ctx,
                status_msg=query.message,
                temp_video_path=pending["temp_video_path"],
                temp_audio_path=pending["temp_audio_path"],
                uploads_dir=pending["uploads_dir"],
                duration=pending["duration"],
                adjust_speed=adjust_speed,
                user_uploads=user_uploads
            )
        )

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

    # -------- POSTAGEM --------
    elif data == "menu_postagem":
        ctx.user_data["temp_post"] = None  # Reseta cache
        await show_posting_menu(update, ctx, edit=True)

    elif data == "post_now_select":
        await show_post_select_platforms(update, ctx)

    elif data == "edit_yt_title":
        ctx.user_data["waiting_edit"] = "yt_title"
        await query.edit_message_text(
            "📝 *EDITAR TÍTULO DO YOUTUBE*\n\n"
            "Por favor, envie o novo título do YouTube por mensagem de texto:\n"
            "_(Máximo de 100 caracteres, inclua o #shorts se desejar)_",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancelar", callback_data="post_now_select")]])
        )

    elif data == "edit_tt_caption":
        ctx.user_data["waiting_edit"] = "tt_caption"
        await query.edit_message_text(
            "📝 *EDITAR LEGENDA DO TIKTOK*\n\n"
            "Por favor, envie a nova legenda do TikTok por mensagem de texto:\n"
            "_(Máximo de 150 caracteres, inclua as 5 hashtags virais)_",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancelar", callback_data="post_now_select")]])
        )

    elif data == "confirm_post_now":
        asyncio.create_task(run_immediate_post(update, ctx))

    elif data == "schedule_post_menu":
        await show_schedule_menu(update, ctx)

    elif data.startswith("sched_quick_"):
        from datetime import datetime, timedelta
        unit = data.split("_")[-1]
        now = datetime.now()
        if unit == "15m": sched_time = now + timedelta(minutes=15)
        elif unit == "30m": sched_time = now + timedelta(minutes=30)
        elif unit == "1h": sched_time = now + timedelta(hours=1)
        elif unit == "2h": sched_time = now + timedelta(hours=2)
        elif unit == "6h": sched_time = now + timedelta(hours=6)
        elif unit == "12h": sched_time = now + timedelta(hours=12)
        
        sqlite_time_str = sched_time.strftime("%Y-%m-%d %H:%M:%S")
        asyncio.create_task(run_schedule_action(update, ctx, sqlite_time_str))

    elif data == "sched_custom_prompt":
        ctx.user_data["waiting_edit"] = "sched_custom"
        await query.edit_message_text(
            "📅 *DIGITAR HORÁRIO PERSONALIZADO*\n\n"
            "Por favor, envie o horário de agendamento por mensagem de texto exatamente no formato:\n"
            "`DD/MM/AAAA HH:MM` (ex: `15/07/2026 14:30`)",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancelar", callback_data="schedule_post_menu")]])
        )

    elif data == "back_to_lobby":
        ctx.user_data["temp_post"] = None
        ctx.user_data["waiting_edit"] = None
        buttons = [
            [InlineKeyboardButton("🚀 Novo Projeto Automático", callback_data="new_auto")],
            [InlineKeyboardButton("🛠️ Novo Projeto Manual", callback_data="new_manual")],
            [InlineKeyboardButton("☁️ Iniciar via GDrive (Scrapper)", callback_data="start_usar_drive")],
            [InlineKeyboardButton("📂 Iniciar via Upload Local", callback_data="start_usar_local")],
            [InlineKeyboardButton("📢 Menu de Postagem 🚀", callback_data="menu_postagem")]
        ]
        await query.edit_message_text(
            "🎬 *Agente de Postagem — DramaRecap*\n\n"
            "Bem-vindo! Escolha uma opção abaixo após enviar os arquivos, ou use os comandos normais.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(buttons)
        )


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
    
    # Processa edições de campos de postagem se estiver aguardando
    waiting_edit = ctx.user_data.get("waiting_edit")
    if waiting_edit:
        from datetime import datetime
        if "temp_post" not in ctx.user_data:
            ctx.user_data["temp_post"] = {}
            
        if waiting_edit == "yt_title":
            ctx.user_data["temp_post"]["youtube_title"] = text
            ctx.user_data["waiting_edit"] = None
            await update.message.reply_text("✅ Título do YouTube atualizado!")
            await show_post_select_platforms(update, ctx)
            return
            
        elif waiting_edit == "tt_caption":
            ctx.user_data["temp_post"]["tiktok_desc"] = text
            ctx.user_data["waiting_edit"] = None
            await update.message.reply_text("✅ Legenda do TikTok atualizada!")
            await show_post_select_platforms(update, ctx)
            return
            
        elif waiting_edit == "sched_custom":
            try:
                # Tenta parsear no formato DD/MM/AAAA HH:MM
                sched_time = datetime.strptime(text, "%d/%m/%Y %H:%M")
                sqlite_time_str = sched_time.strftime("%Y-%m-%d %H:%M:%S")
                ctx.user_data["temp_post"]["scheduled_time"] = sqlite_time_str
                ctx.user_data["waiting_edit"] = None
                asyncio.create_task(run_schedule_action(update, ctx, sqlite_time_str))
                return
            except Exception as ex:
                await update.message.reply_text(
                    "❌ Formato inválido! Envie a data/hora exatamente no formato:\n"
                    "`DD/MM/AAAA HH:MM` (ex: `15/07/2026 14:30`)",
                    parse_mode="Markdown"
                )
                return
    
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
            BotCommand("postar", "Menu de postagem nas redes sociais"),
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
    app.add_handler(CommandHandler("postar", cmd_postar))

    # Conversation Handler de Postagem (igual ao do PostRecap)
    from telegram.ext import ConversationHandler
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("postar", cmd_postar),
            CallbackQueryHandler(menu_postar, pattern="^menu_postar$"),
            CallbackQueryHandler(menu_postar, pattern="^menu_programar$"),
            CallbackQueryHandler(menu_programados, pattern="^menu_programados$"),
            CallbackQueryHandler(delete_programado, pattern="^delete_prog_\\d+$"),
            CallbackQueryHandler(show_posting_menu_lobby, pattern="^menu_postagem$"),
        ],
        states={
            SELECT_PLATFORMS: [
                CallbackQueryHandler(menu_postar, pattern="^menu_postar$"),
                CallbackQueryHandler(menu_postar, pattern="^menu_programar$"),
                CallbackQueryHandler(menu_programados, pattern="^menu_programados$"),
                CallbackQueryHandler(delete_programado, pattern="^delete_prog_\\d+$"),
                CallbackQueryHandler(toggle_platform, pattern="^toggle_"),
                CallbackQueryHandler(confirm_platforms, pattern="^confirm_platforms$"),
                CallbackQueryHandler(back_to_lobby_end, pattern="^back_to_lobby_end$"),
            ],
            SELECT_YOUTUBE_TITLE: [
                CallbackQueryHandler(handle_youtube_title_selection, pattern="^yt_title_"),
                CallbackQueryHandler(menu_postar, pattern="^menu_postar$"),
            ],
            INPUT_YOUTUBE_TITLE_MANUAL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_youtube_title_manual)
            ],
            SELECT_SHORTS_TITLE: [
                CallbackQueryHandler(handle_shorts_title_selection, pattern="^shorts_title_"),
                CallbackQueryHandler(menu_postar, pattern="^menu_postar$"),
            ],
            INPUT_SHORTS_TITLE_MANUAL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_shorts_title_manual)
            ],
            SELECT_YOUTUBE_PRIVACY: [
                CallbackQueryHandler(handle_youtube_privacy, pattern="^yt_priv_")
            ],
            SELECT_INSTAGRAM_SCHEDULING: [
                CallbackQueryHandler(handle_instagram_scheduling, pattern="^ig_")
            ],
            INPUT_INSTAGRAM_TIME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_instagram_time)
            ],
            SELECT_TIKTOK_PRIVACY: [
                CallbackQueryHandler(handle_tiktok_privacy, pattern="^tt_")
            ],
            SELECT_TIKTOK_SCHEDULING: [
                CallbackQueryHandler(handle_tiktok_scheduling, pattern="^tt_")
            ],
            INPUT_TIKTOK_TIME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_tiktok_time)
            ],
            INPUT_UNIFIED_SCHEDULE_TIME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_unified_schedule_time)
            ],
            CONFIRM_POST: [
                CallbackQueryHandler(execute_upload, pattern="^execute_upload$"),
                CallbackQueryHandler(back_to_lobby_end, pattern="^back_to_lobby_end$")
            ]
        },
        fallbacks=[
            CommandHandler("cancel", cancel_posting),
            CallbackQueryHandler(cancel_posting, pattern="^cancel_posting$")
        ]
    )
    app.add_handler(conv_handler)

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

    # Inicializa thread do Scheduler Worker de Postagens
    import threading
    sched_thread = threading.Thread(target=run_post_scheduler_worker, args=(app.bot,), daemon=True)
    sched_thread.start()
    print("Scheduler de publicações agendadas ativo (30s via thread).")

    app.run_polling(drop_pending_updates=True)


# ═══════════════════════════════════════════════════════════════════
# 📢 NOVAS FUNÇÕES DE POSTAGEM
# ═══════════════════════════════════════════════════════════════════

@authorized
async def cmd_postar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Comando /postar - Apresenta o menu de postagem."""
    return await show_posting_menu_lobby(update, context)

async def show_posting_menu_lobby(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Exibe o menu de postagem principal (igual ao do PostRecap)."""
    query = update.callback_query
    if query:
        await query.answer()
        
    email = os.getenv("TIKTOK_USER_EMAIL", "mariadelurdesalvesdoprado@gmail.com")
    conn_info = get_user_connections(email)
    
    status_yt = f"🟢 {conn_info['youtube']}" if conn_info["youtube"] else "🔴 Desconectado"
    status_tt = f"🟢 {conn_info['tiktok']}" if conn_info["tiktok"] else "🔴 Desconectado"
    
    text = (
        "📢 *MENU DE POSTAGEM SOCIAL — DRAMARECAP*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📧 *Conta Ativa:* `{email}`\n\n"
        f"🎬 *YouTube Shorts:* {status_yt}\n"
        f"📱 *TikTok:* {status_tt}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Selecione uma opção no menu abaixo:"
    )
    
    keyboard = [
        [InlineKeyboardButton("Postar Novo Vídeo 🚀", callback_data="menu_postar")],
        [InlineKeyboardButton("Programar Publicação 📅", callback_data="menu_programar")],
        [InlineKeyboardButton("Ver Publicações Programadas 📋", callback_data="menu_programados")],
        [InlineKeyboardButton("🔙 Voltar ao Início", callback_data="back_to_lobby_end")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if query:
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    return SELECT_PLATFORMS

async def back_to_lobby_end(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Retorna ao lobby principal do bot de dramas terminando o ConversationHandler."""
    query = update.callback_query
    if query:
        await query.answer()
        
    buttons = [
        [InlineKeyboardButton("🚀 Novo Projeto Automático", callback_data="new_auto")],
        [InlineKeyboardButton("🛠️ Novo Projeto Manual", callback_data="new_manual")],
        [InlineKeyboardButton("☁️ Iniciar via GDrive (Scrapper)", callback_data="start_usar_drive")],
        [InlineKeyboardButton("📂 Iniciar via Upload Local", callback_data="start_usar_local")],
        [InlineKeyboardButton("📢 Menu de Postagem 🚀", callback_data="menu_postagem")]
    ]
    
    text = (
        "🎬 *Agente de Postagem — DramaRecap*\n\n"
        "Bem-vindo! Escolha uma opção abaixo após enviar os arquivos, ou use os comandos normais."
    )
    
    if query:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))
    else:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))
    return ConversationHandler.END

async def cancel_posting(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancela o fluxo de postagem e retorna ao lobby principal."""
    query = update.callback_query
    if query:
        await query.answer("Fluxo cancelado.")
    return await back_to_lobby_end(update, context)

async def menu_postar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Conecta ao Drive, lê o guia de postagem e exibe seleção de plataformas."""
    query = update.callback_query
    if query:
        await query.answer()
        
    is_scheduled = (query.data == "menu_programar") if query else False
    
    # Inicializa o dicionário de contexto da postagem
    context.user_data["post_data"] = {
        "platforms": {"youtube": False, "youtube_shorts": False, "tiktok": False, "instagram": False},
        "youtube_title": "",
        "shorts_title": "",
        "instagram_scheduled_time": None,
        "tiktok_scheduled_time": None,
        "unified_scheduled_time": None,
        "is_scheduled_run": is_scheduled,
        "guia": None,
        "folder_id": None
    }
    
    status_msg = None
    if query:
        status_msg = await query.edit_message_text("🔍 Conectando ao Google Drive e buscando informações do post...")
    else:
        status_msg = await update.message.reply_text("🔍 Conectando ao Google Drive e buscando informações do post...")
        
    chat_id = str(update.effective_chat.id)
    
    # Baixar guia do Drive
    temp_dir = tempfile.mkdtemp(prefix="drama_guia_")
    local_guia_path = os.path.join(temp_dir, "guia.json")
    
    def _download_guia():
        success = controller.drive.baixar("DRAMA/PIPELINE/FINAL/guia_postagem.json", local_guia_path)
        if not success:
            project = get_latest_project(chat_id)
            if project:
                pid = str(project["id"])
                controller.drive.baixar(f"DRAMA/PIPELINE/PROJECTS/{pid}/guia_postagem.json", local_guia_path)
                
    await asyncio.to_thread(_download_guia)
    
    guia_data = {}
    if os.path.exists(local_guia_path):
        try:
            with open(local_guia_path, "r", encoding="utf-8") as f:
                guia_data = json.load(f)
        except Exception as e:
            logger.error(f"Erro ao ler guia: {e}")
            
    try: shutil.rmtree(temp_dir, ignore_errors=True)
    except: pass
    
    # Se não temos dados, gera genéricos
    if not guia_data:
        guia_data = {
            "titulo_principal": f"Drama_Recap_{datetime.now().strftime('%Y-%m-%d_%H%M')}",
            "titulos_alternativos": [],
            "descricao": "Recap de drama enviado via Bot.",
            "tags_youtube": "drama, dorama, recap, series",
            "tiktok_titulo": "Drama Recap!",
            "tiktok_descricao": "Resumo do drama de hoje! 😱🍿",
            "youtube_title": f"Drama Recap {datetime.now().strftime('%Y-%m-%d')}"
        }
        
    context.user_data["post_data"]["guia"] = guia_data
    
    title = guia_data.get("title") or guia_data.get("youtube_title") or guia_data.get("titulo_principal") or "Drama Recap"
    desc = guia_data.get("tiktok_desc") or guia_data.get("tiktok_guia") or guia_data.get("synopsis") or "Recap de drama!"
    
    escaped_title = html.escape(title[:60])
    escaped_desc = html.escape(desc[:120])
    
    msg_text = (
        f"🎬 *Drama Detectado!*\n"
        f"*Título:* {escaped_title}\n"
        f"*Guia/Sinopse:* {escaped_desc}...\n\n"
        f"Selecione as redes sociais para envio:"
    )
    
    # Limita apenas às redes configuradas do usuário
    email = os.getenv("TIKTOK_USER_EMAIL", "mariadelurdesalvesdoprado@gmail.com")
    conn_info = get_user_connections(email)
    
    # Configura plataformas com base nas conexões reais
    platforms = context.user_data["post_data"]["platforms"]
    
    reply_markup = get_platforms_keyboard(platforms, conn_info)
    
    if query:
        await query.edit_message_text(msg_text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await status_msg.edit_text(msg_text, reply_markup=reply_markup, parse_mode="Markdown")
    return SELECT_PLATFORMS

def get_platforms_keyboard(platforms, conn_info):
    """Gera o teclado de seleção de plataformas do PostRecap."""
    yt_check = "✅" if platforms["youtube_shorts"] else "⬜"
    tt_check = "✅" if platforms["tiktok"] else "⬜"
    
    keyboard = []
    if conn_info["youtube"]:
        keyboard.append([InlineKeyboardButton(f"{yt_check} YouTube Shorts", callback_data="toggle_youtube_shorts")])
    if conn_info["tiktok"]:
        keyboard.append([InlineKeyboardButton(f"{tt_check} TikTok", callback_data="toggle_tiktok")])
        
    keyboard.append([
        InlineKeyboardButton("Cancelar", callback_data="cancel_posting"),
        InlineKeyboardButton("Confirmar Redes", callback_data="confirm_platforms")
    ])
    return InlineKeyboardMarkup(keyboard)

async def toggle_platform(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Alterna a seleção de uma rede social."""
    query = update.callback_query
    await query.answer()
    
    platform_key = query.data.replace("toggle_", "", 1)
    platforms = context.user_data["post_data"]["platforms"]
    
    if platform_key in platforms:
        platforms[platform_key] = not platforms[platform_key]
        
    email = os.getenv("TIKTOK_USER_EMAIL", "mariadelurdesalvesdoprado@gmail.com")
    conn_info = get_user_connections(email)
    
    reply_markup = get_platforms_keyboard(platforms, conn_info)
    await query.edit_message_reply_markup(reply_markup=reply_markup)
    return SELECT_PLATFORMS

async def confirm_platforms(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Confirma a seleção e define o próximo passo do fluxo."""
    query = update.callback_query
    await query.answer()
    
    post_data = context.user_data["post_data"]
    platforms = post_data["platforms"]
    
    if not any(platforms.values()):
        await query.answer("Por favor, selecione pelo menos uma rede social!", show_alert=True)
        return SELECT_PLATFORMS
        
    # Se YouTube Shorts foi selecionado, pergunta o título do Shorts
    if platforms["youtube_shorts"]:
        return await ask_shorts_title(query, context)
        
    # Se não tem YouTube Shorts, mas tem TikTok
    elif platforms["tiktok"]:
        return await check_tiktok_workflow(update, context)
        
    else:
        if post_data.get("is_scheduled_run"):
            return await ask_unified_schedule_time(query, context)
        else:
            return await show_final_confirmation(query, context)

async def handle_tiktok_scheduling(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    data = query.data
    if data == "tt_now":
        context.user_data["post_data"]["tiktok_scheduled_time"] = None
        if context.user_data["post_data"].get("is_scheduled_run"):
            return await ask_unified_schedule_time(query, context)
        else:
            return await show_final_confirmation(query, context)
    elif data == "tt_schedule":
        await query.edit_message_text(
            "Por favor, digite a data e hora do agendamento para o TikTok.\n"
            "Use o formato: `AAAA-MM-DD HH:MM`\n"
            "Exemplo: `2026-07-24 18:00`",
            parse_mode="Markdown"
        )
        return INPUT_TIKTOK_TIME

async def handle_tiktok_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_user.id not in AUTHORIZED_USERS:
        return ConversationHandler.END
        
    raw_time = update.message.text.strip()
    try:
        dt = datetime.strptime(raw_time, "%Y-%m-%d %H:%M")
        context.user_data["post_data"]["tiktok_scheduled_time"] = dt.strftime("%Y-%m-%d %H:%M:00")
        
        if context.user_data["post_data"].get("is_scheduled_run"):
            return await ask_unified_schedule_time(update.message, context)
            
        await show_final_confirmation_message(update.message, context)
        return CONFIRM_POST
    except ValueError:
        await update.message.reply_text(
            "❌ Formato inválido! Por favor, utilize o formato correto:\n"
            "`AAAA-MM-DD HH:MM` (ex: `2026-07-24 18:00`)",
            parse_mode="Markdown"
        )
        return INPUT_TIKTOK_TIME

async def handle_youtube_title_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    data = query.data
    guia = context.user_data["post_data"]["guia"]
    
    if data == "yt_title_principal":
        context.user_data["post_data"]["youtube_title"] = guia.get("titulo_principal")
    elif data.startswith("yt_title_alt_"):
        idx = int(data.split("_")[-1])
        context.user_data["post_data"]["youtube_title"] = guia.get("titulos_alternativos", [])[idx]
    elif data == "yt_title_manual":
        await query.edit_message_text("Por favor, digite o título desejado para o YouTube:")
        return INPUT_YOUTUBE_TITLE_MANUAL
        
    if context.user_data["post_data"]["platforms"]["youtube_shorts"]:
        return await ask_shorts_title(query, context)
    else:
        return await ask_youtube_privacy(query, context)

async def handle_youtube_title_manual(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_user.id not in AUTHORIZED_USERS:
        return ConversationHandler.END
        
    title = update.message.text.strip()
    if not title:
        await update.message.reply_text("Título inválido. Por favor, envie um texto válido:")
        return INPUT_YOUTUBE_TITLE_MANUAL
        
    context.user_data["post_data"]["youtube_title"] = title
    
    if context.user_data["post_data"]["platforms"]["youtube_shorts"]:
        # Precisa definir título do Shorts
        guia = context.user_data["post_data"]["guia"]
        titulo_p = guia.get("titulo_principal", "Sem Título")
        keyboard = [
            [InlineKeyboardButton(f"Usar: {titulo_p[:40]}... #shorts", callback_data="shorts_title_principal")],
            [InlineKeyboardButton("✍️ Digitar Título Manualmente", callback_data="shorts_title_manual")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "🎬 *Título para o YouTube Shorts:*\n\n"
            f"*Sugestão:* {titulo_p} #shorts\n\n"
            "Selecione ou digite um título:",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        return SELECT_SHORTS_TITLE
    else:
        return await ask_youtube_privacy(update, context)

async def handle_instagram_scheduling(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    data = query.data
    if data == "ig_now":
        context.user_data["post_data"]["instagram_scheduled_time"] = None
        if context.user_data["post_data"]["platforms"]["tiktok"]:
            return await check_tiktok_workflow(update, context)
        return await show_final_confirmation(query, context)
    elif data == "ig_schedule":
        await query.edit_message_text(
            "Por favor, digite a data e hora do agendamento para o Instagram.\n"
            "Use o formato: `AAAA-MM-DD HH:MM`\n"
            "Exemplo: `2026-07-24 18:00`",
            parse_mode="Markdown"
        )
        return INPUT_INSTAGRAM_TIME

async def handle_instagram_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_user.id not in AUTHORIZED_USERS:
        return ConversationHandler.END
        
    raw_time = update.message.text.strip()
    try:
        dt = datetime.strptime(raw_time, "%Y-%m-%d %H:%M")
        context.user_data["post_data"]["instagram_scheduled_time"] = dt.strftime("%Y-%m-%d %H:%M:00")
        
        if context.user_data["post_data"]["platforms"]["tiktok"]:
            return await check_tiktok_workflow(update, context)
            
        await show_final_confirmation_message(update.message, context)
        return CONFIRM_POST
    except ValueError:
        await update.message.reply_text(
            "❌ Formato inválido! Por favor, utilize o formato correto:\n"
            "`AAAA-MM-DD HH:MM` (ex: `2026-07-24 18:00`)",
            parse_mode="Markdown"
        )
        return INPUT_INSTAGRAM_TIME

async def ask_shorts_title(query, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Pergunta o título para o YouTube Shorts."""
    guia = context.user_data["post_data"]["guia"]
    
    titulo_p = guia.get("youtube_title") or guia.get("title") or guia.get("titulo_principal") or "Drama Recap"
    if "#shorts" not in titulo_p.lower() and len(titulo_p) <= 90:
        titulo_p = f"{titulo_p} #shorts"
        
    escaped_titulo_p = html.escape(titulo_p)
    text = (
        f"🎬 *Título para o YouTube Shorts:*\n\n"
        f"*Sugestão:* {escaped_titulo_p}\n\n"
        f"Selecione ou digite um título:"
    )
    
    keyboard = [
        [InlineKeyboardButton(f"Usar Sugerido: {titulo_p[:40]}...", callback_data="shorts_title_principal")],
        [InlineKeyboardButton("✍️ Digitar Título Manualmente", callback_data="shorts_title_manual")],
        [InlineKeyboardButton("Voltar", callback_data="menu_postar")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    return SELECT_SHORTS_TITLE

async def handle_shorts_title_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Processa a escolha do título do YouTube Shorts."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    guia = context.user_data["post_data"]["guia"]
    
    if data == "shorts_title_principal":
        title = guia.get("youtube_title") or guia.get("title") or guia.get("titulo_principal") or "Drama Recap"
        if "#shorts" not in title.lower():
            title = f"{title} #shorts"
        context.user_data["post_data"]["shorts_title"] = title
    elif data == "shorts_title_manual":
        await query.edit_message_text(
            "Por favor, digite o título desejado para o YouTube Shorts:\n\n"
            "💡 _Dica: inclua #shorts no título para melhor SEO._",
            parse_mode="Markdown"
        )
        return INPUT_SHORTS_TITLE_MANUAL
        
    return await ask_youtube_privacy(query, context)

async def handle_shorts_title_manual(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Recebe o título do Shorts digitado manualmente."""
    if update.effective_user.id not in AUTHORIZED_USERS:
        return ConversationHandler.END
        
    title = update.message.text.strip()
    if not title:
        await update.message.reply_text("Título inválido. Por favor, envie um texto válido:")
        return INPUT_SHORTS_TITLE_MANUAL
        
    if "#shorts" not in title.lower():
        title = f"{title} #shorts"
    context.user_data["post_data"]["shorts_title"] = title
    
    return await ask_youtube_privacy(update, context)

async def ask_youtube_privacy(query_or_update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Pergunta a visibilidade do vídeo no YouTube."""
    query = getattr(query_or_update, 'callback_query', None) or query_or_update
    message = getattr(query_or_update, 'message', None)
    
    text = (
        "🔒 *Visibilidade no YouTube*\n"
        "Como deseja publicar o vídeo?"
    )
    keyboard = [
        [
            InlineKeyboardButton("📝 Rascunho", callback_data="yt_priv_draft"),
            InlineKeyboardButton("🌎 Público", callback_data="yt_priv_public")
        ],
        [
            InlineKeyboardButton("🔒 Privado", callback_data="yt_priv_private"),
            InlineKeyboardButton("🔗 Não Listado", callback_data="yt_priv_unlisted")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if hasattr(query, 'edit_message_text'):
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    elif message:
        await message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        
    return SELECT_YOUTUBE_PRIVACY

async def handle_youtube_privacy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Processa a escolha de visibilidade do YouTube."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    privacy_map = {
        "yt_priv_draft": "draft",
        "yt_priv_public": "public",
        "yt_priv_private": "private",
        "yt_priv_unlisted": "unlisted"
    }
    context.user_data["post_data"]["youtube_privacy"] = privacy_map.get(data, "draft")
    
    return await route_after_titles(update, context)

async def route_after_titles(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Função auxiliar para direcionar para o fluxo do TikTok ou confirmação."""
    post_data = context.user_data["post_data"]
    platforms = post_data["platforms"]
    query = getattr(update, "callback_query", None)
    message = getattr(update, "message", None)
    
    if platforms["tiktok"]:
        return await check_tiktok_workflow(update, context)
    else:
        if post_data.get("is_scheduled_run"):
            return await ask_unified_schedule_time(query or message, context)
        else:
            if query:
                return await show_final_confirmation(query, context)
            else:
                await show_final_confirmation_message(message, context)
                return CONFIRM_POST

async def check_tiktok_workflow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Configurações de privacidade e agendamento do TikTok."""
    query = getattr(update, "callback_query", None)
    message = getattr(update, "message", None)
    
    text = "🎬 *Configuração do TikTok*\nQual a privacidade desejada para o vídeo?"
    keyboard = [
        [
            InlineKeyboardButton("🌍 Público", callback_data="tt_public"),
            InlineKeyboardButton("🔒 Privado", callback_data="tt_private")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if query:
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    elif message:
        await message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    return SELECT_TIKTOK_PRIVACY

async def handle_tiktok_privacy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    data = query.data
    if data == "tt_public":
        context.user_data["post_data"]["tiktok_privacy"] = "PUBLIC_TO_EVERYONE"
    elif data == "tt_private":
        context.user_data["post_data"]["tiktok_privacy"] = "SELF_ONLY"
        
    if context.user_data["post_data"].get("is_scheduled_run"):
        return await ask_unified_schedule_time(query, context)
        
    # Se postagem imediata (não agendamento local), vai direto para a confirmação
    context.user_data["post_data"]["tiktok_scheduled_time"] = None
    return await show_final_confirmation(query, context)

async def ask_unified_schedule_time(query, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Solicita a data/hora unificada para o agendamento local."""
    text = (
        "📅 *Programação Unificada (Salvar na VM)*\n\n"
        "Digite a data e hora que deseja realizar o disparo nas redes sociais selecionadas.\n"
        "Use o formato: `AAAA-MM-DD HH:MM`\n"
        "Exemplo: `2026-07-16 14:30`"
    )
    if hasattr(query, 'edit_message_text'):
        await query.edit_message_text(text, parse_mode="Markdown")
    else:
        await query.reply_text(text, parse_mode="Markdown")
    return INPUT_UNIFIED_SCHEDULE_TIME

async def handle_unified_schedule_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Recebe a data/hora do agendamento unificado."""
    if update.effective_user.id not in AUTHORIZED_USERS:
        return ConversationHandler.END
        
    raw_time = update.message.text.strip()
    try:
        dt = datetime.strptime(raw_time, "%Y-%m-%d %H:%M")
        context.user_data["post_data"]["unified_scheduled_time"] = dt.strftime("%Y-%m-%d %H:%M:00")
        
        await show_final_confirmation_message(update.message, context)
        return CONFIRM_POST
    except ValueError:
        await update.message.reply_text(
            "❌ Formato inválido! Utilize o formato correto:\n"
            "`AAAA-MM-DD HH:MM` (ex: `2026-07-16 14:30`)",
            parse_mode="Markdown"
        )
        return INPUT_UNIFIED_SCHEDULE_TIME

async def show_final_confirmation(query, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Gera a mensagem de confirmação final de postagem."""
    post_data = context.user_data["post_data"]
    platforms = post_data["platforms"]
    
    redes = []
    if platforms["youtube_shorts"]:
        title = html.escape(post_data['shorts_title'])
        redes.append(f"• YouTube Shorts (Título: {title})")
    if platforms["tiktok"]:
        priv = "Público" if post_data.get("tiktok_privacy") == "PUBLIC_TO_EVERYONE" else "Privado"
        redes.append(f"• TikTok (Privacidade: {priv})")
        
    redes_str = "\n".join(redes)
    
    if post_data.get("is_scheduled_run"):
        sched = post_data.get("unified_scheduled_time")
        text = (
            "<b>📝 Resumo da Programação Unificada:</b>\n\n"
            f"O vídeo final será baixado e armazenado localmente na VM para disparo em:\n"
            f"📅 <b>{sched}</b>\n\n"
            f"<b>Redes sociais ativas:</b>\n{redes_str}\n\n"
            "Confirma a programação?"
        )
    else:
        text = (
            "<b>📝 Resumo da Postagem Imediata:</b>\n\n"
            f"O vídeo final será enviado para:\n"
            f"{redes_str}\n\n"
            "Confirma o envio agora?"
        )
        
    keyboard = [
        [
            InlineKeyboardButton("Cancelar", callback_data="cancel_posting"),
            InlineKeyboardButton("Confirmar e Enviar", callback_data="execute_upload")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")
    return CONFIRM_POST

async def show_final_confirmation_message(msg_object, context: ContextTypes.DEFAULT_TYPE):
    post_data = context.user_data["post_data"]
    platforms = post_data["platforms"]
    
    redes = []
    if platforms["youtube_shorts"]:
        title = html.escape(post_data['shorts_title'])
        redes.append(f"• YouTube Shorts (Título: {title})")
    if platforms["tiktok"]:
        priv = "Público" if post_data.get("tiktok_privacy") == "PUBLIC_TO_EVERYONE" else "Privado"
        redes.append(f"• TikTok (Privacidade: {priv})")
        
    redes_str = "\n".join(redes)
    
    if post_data.get("is_scheduled_run"):
        sched = post_data.get("unified_scheduled_time")
        text = (
            "<b>📝 Resumo da Programação Unificada:</b>\n\n"
            f"O vídeo final será baixado e armazenado localmente na VM para disparo em:\n"
            f"📅 <b>{sched}</b>\n\n"
            f"<b>Redes sociais ativas:</b>\n{redes_str}\n\n"
            "Confirma a programação?"
        )
    else:
        text = (
            "<b>📝 Resumo da Postagem Imediata:</b>\n\n"
            f"O vídeo final será enviado para:\n"
            f"{redes_str}\n\n"
            "Confirma o envio agora?"
        )
        
    keyboard = [
        [
            InlineKeyboardButton("Cancelar", callback_data="cancel_posting"),
            InlineKeyboardButton("Confirmar e Enviar", callback_data="execute_upload")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await msg_object.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")

async def execute_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Dispara a postagem imediata ou cria o agendamento local."""
    query = update.callback_query
    await query.answer()
    
    post_data = context.user_data["post_data"]
    platforms = post_data["platforms"]
    guia = post_data["guia"]
    
    if post_data.get("is_scheduled_run"):
        status_msg = await query.edit_message_text("⏳ Criando agendamento no banco de dados local da VM...")
        asyncio.create_task(run_local_schedule_pipeline(status_msg, platforms, post_data, guia))
    else:
        status_msg = await query.edit_message_text("📥 Iniciando download do vídeo final do Google Drive...")
        asyncio.create_task(run_upload_pipeline(status_msg, platforms, post_data, guia))
        
    return ConversationHandler.END

async def run_local_schedule_pipeline(status_msg, platforms, post_data, guia):
    """Pipeline para baixar o vídeo e criar o registro programado pendente."""
    loop = asyncio.get_running_loop()
    
    async def safe_edit_status(text, parse_mode=None):
        try: await status_msg.edit_text(text, parse_mode=parse_mode)
        except Exception as e: logger.error(f"Erro ao editar status: {e}")
        
    post_id = None
    try:
        email = os.getenv("TIKTOK_USER_EMAIL", "mariadelurdesalvesdoprado@gmail.com")
        
        # Constrói legendas
        def get_formatted_caption(g):
            if g.get("tiktok_desc"):
                return g["tiktok_desc"]
            if g.get("tiktok_guia"):
                return g["tiktok_guia"]
            hook = g.get("tiktok_titulo") or g.get("titulo_principal") or "Você teria coragem de assistir até o final? 😳"
            titulo_dorama = g.get("tiktok_titulo_anime") or g.get("titulo_anime") or g.get("title") or "Drama"
            sinopse = g.get("tiktok_sinopse") or g.get("sinopse") or "Resumo incrível!"
            tags_list = g.get("instagram_hashtags") or g.get("tiktok_hashtags") or ["#dramas", "#doramas", "#recap", "#series"]
            tags_str = " ".join(tags_list[:5]) if isinstance(tags_list, list) else tags_list
            return f"{hook}\n\nTitulo: {titulo_dorama}\n\nSinopse: {sinopse}\n\n{tags_str}"
            
        caption_texto = get_formatted_caption(guia)
        sched_time = post_data.get("unified_scheduled_time")
        
        yt_desc = guia.get("youtube_desc") or guia.get("descricao") or f"Assista ao drama recap.\n\n#dramas #shorts #doramas"
        
        # Adiciona post_id no banco
        post_id = add_scheduled_post(
            video_path="",
            title_shorts=post_data.get("shorts_title", "Drama Recap #shorts"),
            shorts_description=yt_desc,
            tiktok_caption=caption_texto,
            post_shorts=platforms["youtube_shorts"],
            post_tiktok=platforms["tiktok"],
            scheduled_time=sched_time,
            chat_id=status_msg.chat_id,
            email=email
        )
        
        update_scheduled_post_status(post_id, "downloading")
        
        base_dir = "/home/ubuntu/apps/drama-pipeline/scheduled_posts"
        os.makedirs(base_dir, exist_ok=True)
        post_dir = os.path.join(base_dir, f"post_{post_id}")
        os.makedirs(post_dir, exist_ok=True)
        local_video_path = os.path.join(post_dir, "video.mp4")
        
        # Baixa do Drive de forma assíncrona
        await safe_edit_status("📥 *Baixando o vídeo final do Drive para agendamento local na VM...*", parse_mode="Markdown")
        
        def _download():
            success = controller.drive.baixar("DRAMA/PIPELINE/FINAL/video_final.mp4", local_video_path)
            if not success:
                project = get_latest_project(str(status_msg.chat_id))
                if project:
                    pid = str(project["id"])
                    controller.drive.baixar(f"DRAMA/PIPELINE/PROJECTS/{pid}/video_final.mp4", local_video_path)
            return success
            
        success_dl = await asyncio.to_thread(_download)
        
        if not success_dl or not os.path.exists(local_video_path):
            raise Exception("Vídeo final (video_final.mp4) não foi localizado ou baixado do Drive.")
            
        # Atualiza path do vídeo no SQLite e ativa pendente
        import sqlite3
        db_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "posts.db")
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        cursor.execute("UPDATE scheduled_posts SET video_path = ?, status = 'pending' WHERE id = ?", (local_video_path, post_id))
        conn.commit()
        conn.close()
        
        success_text = (
            "✅ *Publicação Programada com Sucesso!*\n\n"
            f"📅 *Data de Disparo:* `{sched_time}`\n"
            "📂 O vídeo foi baixado e armazenado localmente na VM para segurança.\n\n"
            "Você pode gerenciar ou excluir esta publicação no menu *Ver Publicações Programadas*."
        )
        await safe_edit_status(success_text, parse_mode="Markdown")
        
    except Exception as e:
        error_msg = f"❌ *Falha ao criar agendamento local:* `{e}`"
        logger.error(f"Erro no pipeline de agendamento: {e}")
        await safe_edit_status(error_msg, parse_mode="Markdown")
        if post_id:
            try: update_scheduled_post_status(post_id, "failed", error_msg[:250])
            except: pass

async def run_upload_pipeline(status_msg, platforms, post_data, guia):
    """Pipeline de download e upload imediato."""
    async def safe_edit_status(text, parse_mode=None):
        try: await status_msg.edit_text(text, parse_mode=parse_mode)
        except Exception as e: logger.error(f"Erro ao editar status: {e}")
        
    temp_dir = tempfile.mkdtemp(prefix="drama_post_")
    local_video_path = os.path.join(temp_dir, "video.mp4")
    
    try:
        email = os.getenv("TIKTOK_USER_EMAIL", "mariadelurdesalvesdoprado@gmail.com")
        conn_info = get_user_connections(email)
        
        await safe_edit_status("📥 *Baixando o vídeo final do Drive para postagem imediata...*", parse_mode="Markdown")
        
        def _download():
            success = controller.drive.baixar("DRAMA/PIPELINE/FINAL/video_final.mp4", local_video_path)
            if not success:
                project = get_latest_project(str(status_msg.chat_id))
                if project:
                    pid = str(project["id"])
                    controller.drive.baixar(f"DRAMA/PIPELINE/PROJECTS/{pid}/video_final.mp4", local_video_path)
            return success
            
        success_dl = await asyncio.to_thread(_download)
        
        if not success_dl or not os.path.exists(local_video_path):
            raise Exception("Vídeo final (video_final.mp4) não foi localizado ou baixado do Drive.")
            
        # Títulos e legendas
        youtube_title = post_data.get("shorts_title", "Drama Recap #shorts")
        youtube_desc = guia.get("youtube_desc") or guia.get("descricao") or f"Assista ao drama recap.\n\n#dramas #shorts #doramas"
        youtube_tags = guia.get("youtube_tags") or guia.get("tags_youtube") or "dramas, shorts"
        if isinstance(youtube_tags, str):
            youtube_tags = [t.strip() for t in youtube_tags.split(",") if t.strip()]
            
        def get_formatted_caption(g):
            if g.get("tiktok_desc"):
                return g["tiktok_desc"]
            if g.get("tiktok_guia"):
                return g["tiktok_guia"]
            hook = g.get("tiktok_titulo") or g.get("titulo_principal") or "Você teria coragem de assistir até o final? 😳"
            titulo_dorama = g.get("tiktok_titulo_anime") or g.get("titulo_anime") or g.get("title") or "Drama"
            sinopse = g.get("tiktok_sinopse") or g.get("sinopse") or "Resumo incrível!"
            tags_list = g.get("instagram_hashtags") or g.get("tiktok_hashtags") or ["#dramas", "#doramas", "#recap", "#series"]
            tags_str = " ".join(tags_list[:5]) if isinstance(tags_list, list) else tags_list
            return f"{hook}\n\nTitulo: {titulo_dorama}\n\nSinopse: {sinopse}\n\n{tags_str}"
            
        tiktok_caption = get_formatted_caption(guia)
        
        results = []
        
        # Configurar ambiente
        os.environ["TIKTOK_USER_EMAIL"] = email
        os.environ["YOUTUBE_USER_EMAIL"] = email
        
        # 1. YouTube Shorts
        if platforms["youtube_shorts"] and conn_info["youtube"]:
            await safe_edit_status(f"📤 *Enviando para o YouTube Shorts...*\nCanal: `{conn_info['youtube']}`", parse_mode="Markdown")
            try:
                def _upload_yt():
                    import youtube_uploader
                    video_id_res, video_url_res = youtube_uploader.upload_video_to_youtube(
                        video_path=local_video_path,
                        title=youtube_title[:100],
                        description=youtube_desc,
                        tags=youtube_tags,
                        category_id="24",
                        privacy_status=post_data.get("youtube_privacy", "draft"),
                        thumbnail_path=None
                    )
                    return video_url_res
                yt_url = await asyncio.to_thread(_upload_yt)
                results.append(f"🎥 *YouTube Shorts:* ✅ Postado!\n🔗 {yt_url}")
            except Exception as ex:
                results.append(f"🎥 *YouTube Shorts:* ❌ Falhou!\n`Erro: {ex}`")
                
        # 2. TikTok
        if platforms["tiktok"] and conn_info["tiktok"]:
            await safe_edit_status(f"📤 *Enviando para o TikTok...*\nConta: `@ {conn_info['tiktok']}`", parse_mode="Markdown")
            try:
                def _upload_tt():
                    import tiktok_service
                    publish_id = tiktok_service.upload_video_to_tiktok(
                        video_path=local_video_path,
                        title=tiktok_caption[:150],
                        privacy_level=post_data.get("tiktok_privacy", "PUBLIC_TO_EVERYONE")
                    )
                    return publish_id
                pub_id = await asyncio.to_thread(_upload_tt)
                results.append(f"🎵 *TikTok:* ✅ Postado! (ID: `{pub_id}`)")
            except Exception as ex:
                results.append(f"🎵 *TikTok:* ❌ Falhou!\n`Erro: {ex}`")
                
        results_str = "\n\n".join(results)
        await safe_edit_status(
            "📢 *RELATÓRIO DE POSTAGEM*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{results_str}\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            parse_mode="Markdown"
        )
        
    except Exception as e:
        logger.error(f"Erro no pipeline imediato: {e}")
        await safe_edit_status(f"❌ *Erro ao processar postagem:* `{e}`", parse_mode="Markdown")
        
    finally:
        try: shutil.rmtree(temp_dir, ignore_errors=True)
        except: pass

async def menu_programados(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Lista todos os agendamentos programados pendentes na VM."""
    query = update.callback_query
    await query.answer()
    
    from bot.db_postagem import get_all_pending_scheduled
    rows = get_all_pending_scheduled()
    
    if not rows:
        text = "📭 Nenhuma publicação programada localmente na VM no momento."
        keyboard = [[InlineKeyboardButton("Voltar", callback_data="back_to_menu")]]
    else:
        text = "📋 *Publicações Programadas na VM (Aguardando Disparo):*\n\n"
        keyboard = []
        for r in rows:
            post_id, sched_time, title_shorts, tiktok_caption, post_shorts, post_tiktok, status = r
            
            redes = []
            if post_shorts: redes.append("Shorts")
            if post_tiktok: redes.append("TT")
            redes_str = "/".join(redes)
            
            display_title = title_shorts or (tiktok_caption[:30] + "..." if tiktok_caption else "Sem Título")
            status_emoji = "⏳" if status == "pending" else "❌"
            
            text += f"{status_emoji} *ID: {post_id}* | `{sched_time}`\n"
            text += f"   Redes: {redes_str}\n"
            text += f"   Título/Legenda: {display_title}\n\n"
            
            keyboard.append([
                InlineKeyboardButton(f"🗑️ Excluir #{post_id}", callback_data=f"delete_prog_{post_id}")
            ])
            
        keyboard.append([InlineKeyboardButton("Voltar ao Início", callback_data="back_to_menu")])
        
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    return SELECT_PLATFORMS

async def delete_programado(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Exclui um agendamento e seus arquivos físicos correspondentes."""
    query = update.callback_query
    data = query.data
    post_id = int(data.split("_")[-1])
    
    import sqlite3
    db_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "posts.db")
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    cursor.execute("SELECT video_path FROM scheduled_posts WHERE id = ?", (post_id,))
    row = cursor.fetchone()
    
    if row and row[0]:
        video_path = row[0]
        if os.path.exists(video_path):
            try:
                os.remove(video_path)
                post_dir = os.path.dirname(video_path)
                os.rmdir(post_dir)
            except Exception as ex:
                logger.error(f"Erro ao deletar arquivos: {ex}")
                
    cursor.execute("DELETE FROM scheduled_posts WHERE id = ?", (post_id,))
    conn.commit()
    conn.close()
    
    await query.answer(f"Publicação #{post_id} excluída com sucesso!", show_alert=True)
    return await menu_programados(update, context)

def run_post_scheduler_worker(bot):
    """Worker de Fila que processa posts programados que venceram na tabela scheduled_posts."""
    logger.info("Iniciando Worker de Fila de Agendamento de Dramas em background...")
    while True:
        try:
            from bot.db_postagem import get_pending_scheduled_posts, update_scheduled_post_status
            jobs = get_pending_scheduled_posts()
            
            if jobs:
                logger.info(f"[SCHEDULER] Encontrados {len(jobs)} agendamentos pendentes para processar.")
                
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    
                for job in jobs:
                    post_id, video_path, title_shorts, shorts_description, tiktok_caption, post_shorts, post_tiktok, sched_time, chat_id, email = job
                    
                    logger.info(f"[SCHEDULER] Processando post #{post_id} programado para {sched_time}...")
                    update_scheduled_post_status(post_id, "processing")
                    
                    results = []
                    errors = []
                    
                    conn_info = get_user_connections(email)
                    
                    # Configura conexões no ambiente do processo
                    os.environ["TIKTOK_USER_EMAIL"] = email
                    os.environ["YOUTUBE_USER_EMAIL"] = email
                    
                    # 1. YouTube Shorts
                    if post_shorts and conn_info["youtube"]:
                        try:
                            logger.info(f"[SCHEDULER] Enviando Shorts para o canal {conn_info['youtube']}")
                            import youtube_uploader
                            video_id_res, video_url_res = youtube_uploader.upload_video_to_youtube(
                                video_path=video_path,
                                title=title_shorts[:100],
                                description=shorts_description,
                                tags=["dramas", "shorts", "recap"],
                                category_id="24",
                                privacy_status="public",
                                thumbnail_path=None
                            )
                            results.append(f"🎥 YouTube Shorts: ✅ Postado!\n🔗 {video_url_res}")
                        except Exception as ex:
                            errors.append(f"YouTube: {ex}")
                            logger.error(f"[SCHEDULER] Erro no YouTube: {ex}")
                            
                    # 2. TikTok
                    if post_tiktok and conn_info["tiktok"]:
                        try:
                            logger.info(f"[SCHEDULER] Enviando para TikTok conta @{conn_info['tiktok']}")
                            import tiktok_service
                            pub_id = tiktok_service.upload_video_to_tiktok(
                                video_path=video_path,
                                title=tiktok_caption[:150],
                                privacy_level="PUBLIC_TO_EVERYONE"
                            )
                            results.append(f"🎵 TikTok: ✅ Postado! (ID: {pub_id})")
                        except Exception as ex:
                            errors.append(f"TikTok: {ex}")
                            logger.error(f"[SCHEDULER] Erro no TikTok: {ex}")
                            
                    # Limpar arquivo de vídeo
                    if os.path.exists(video_path):
                        try:
                            os.remove(video_path)
                            post_dir = os.path.dirname(video_path)
                            os.rmdir(post_dir)
                        except Exception as rm_ex:
                            logger.error(f"[SCHEDULER] Erro ao limpar video_path: {rm_ex}")
                            
                    # Atualiza o status
                    if errors:
                        err_str = "; ".join(errors)
                        update_scheduled_post_status(post_id, "failed", err_str[:250])
                        notify_text = f"❌ *Falha no agendamento #{post_id}!*\n\n`Erro: {err_str}`"
                    else:
                        update_scheduled_post_status(post_id, "completed")
                        res_str = "\n".join(results)
                        notify_text = f"✅ *Publicação Programada #{post_id} enviada com sucesso!*\n\n{res_str}"
                        
                    # Notificar chat do Telegram
                    try:
                        loop.run_until_complete(bot.send_message(chat_id=chat_id, text=notify_text, parse_mode="Markdown"))
                    except Exception as notify_ex:
                        logger.error(f"[SCHEDULER] Erro ao enviar notificacao: {notify_ex}")
                        
        except Exception as e:
            logger.error(f"Erro geral no scheduler worker: {e}")
            
        time.sleep(30)


if __name__ == "__main__":
    main()
