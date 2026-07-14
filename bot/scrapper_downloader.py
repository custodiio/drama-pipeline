import os
import re
import time
import httpx
import logging
import asyncio
import subprocess
from telegram import Update
from telegram.ext import ContextTypes
from bot.drive_manager import DriveManager

logger = logging.getLogger(__name__)

DOUYIN_API_BASE = os.getenv("DOUYIN_API_BASE", "http://localhost:5555")

def get_video_duration(video_path: str) -> float:
    """Retorna a duração do vídeo em segundos usando ffprobe."""
    if not os.path.exists(video_path):
        return 0.0
    cmd = [
        'ffprobe', '-v', 'quiet', '-print_format', 'json',
        '-show_format', '-show_streams', video_path
    ]
    try:
        import json
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        duration = data.get('format', {}).get('duration')
        if duration:
            return float(duration)
        for stream in data.get('streams', []):
            duration = stream.get('duration')
            if duration:
                return float(duration)
        return 0.0
    except Exception as e:
        logger.error(f"Erro ao obter duração com ffprobe: {e}")
        return 0.0

def truncate_video(input_path: str, output_path: str, seconds: float = 175.0) -> bool:
    """Corta o vídeo para uma duração máxima em segundos de forma ultrarrápida (sem re-codificar)."""
    if not os.path.exists(input_path):
        return False
    cmd = [
        'ffmpeg', '-y', '-i', input_path, '-t', str(seconds),
        '-c:v', 'copy', '-c:a', 'copy', output_path
    ]
    try:
        subprocess.run(cmd, capture_output=True, check=True)
        return os.path.exists(output_path) and os.path.getsize(output_path) > 0
    except Exception as e:
        logger.error(f"Erro ao cortar vídeo com ffmpeg: {e}")
        return False

def extract_audio(video_path: str, audio_path: str) -> bool:
    """Extrai a faixa de áudio de um vídeo e a converte para MP3 usando ffmpeg."""
    if not os.path.exists(video_path):
        return False
    cmd = [
        'ffmpeg', '-y', '-i', video_path, '-vn',
        '-acodec', 'libmp3lame', '-q:a', '2', audio_path
    ]
    try:
        subprocess.run(cmd, capture_output=True, check=True)
        return os.path.exists(audio_path) and os.path.getsize(audio_path) > 0
    except Exception as e:
        logger.error(f"Erro ao extrair áudio com ffmpeg: {e}")
        return False

async def run_scrapper_download(
    chat_id: str,
    context: ContextTypes.DEFAULT_TYPE,
    url: str,
    user_uploads: dict
) -> bool:
    """Baixa o vídeo da API do Evil0ctal, extrai o áudio, e salva no Drive e localmente."""
    status_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=f"📥 **Iniciando Download do Drama...**\n"
             f"🔗 **URL:** {url}\n"
             f"⏳ Conectando à API de Download em {DOUYIN_API_BASE}...",
        parse_mode="Markdown",
        disable_web_page_preview=True
    )

    uploads_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")
    os.makedirs(uploads_dir, exist_ok=True)

    temp_video_path = os.path.join(uploads_dir, "video_original.mp4")
    temp_audio_path = os.path.join(uploads_dir, "drama_audio.mp3")

    # Limpa mídias locais antigas
    for p in [temp_video_path, temp_audio_path]:
        if os.path.exists(p):
            try: os.remove(p)
            except: pass

    api_download_url = f"{DOUYIN_API_BASE}/api/download"
    download_success = False

    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            async with client.stream("GET", api_download_url, params={"url": url, "with_watermark": "false"}) as r:
                resp_content_type = r.headers.get("Content-Type", "")
                if r.status_code == 200 and "application/json" not in resp_content_type:
                    total_size = int(r.headers.get("Content-Length", 0))
                    downloaded = 0
                    last_update = time.time()
                    last_percent = 0

                    with open(temp_video_path, "wb") as f:
                        async for chunk in r.aiter_bytes(chunk_size=16384):
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total_size > 0:
                                percent = int((downloaded / total_size) * 100)
                                now = time.time()
                                if (percent - last_percent >= 10) or (now - last_update >= 5.0) or (percent == 100):
                                    last_percent = percent
                                    last_update = now
                                    try:
                                        await status_msg.edit_text(
                                            f"📥 **Baixando vídeo do Drama...**\n"
                                            f"⏳ Progresso: **{percent}%** ({downloaded/(1024*1024):.1f}MB / {total_size/(1024*1024):.1f}MB)...",
                                            parse_mode="Markdown"
                                        )
                                    except: pass
                    download_success = os.path.exists(temp_video_path) and os.path.getsize(temp_video_path) > 0
                else:
                    await r.aread()
                    try:
                        err_data = r.json()
                        err_msg = err_data.get("message", "Erro na API de Download")
                    except:
                        err_msg = f"HTTP {r.status_code}: {r.text[:200]}"
                    await status_msg.edit_text(f"❌ **Falha ao baixar vídeo pela API**:\n`{err_msg}`", parse_mode="Markdown")
                    return False
    except Exception as e:
        logger.error(f"Exceção no download: {e}")
        await status_msg.edit_text(f"❌ **Exceção no download pela API**:\n`{e}`", parse_mode="Markdown")
        return False

    if not download_success:
        await status_msg.edit_text("❌ Falha no download do vídeo da API.", parse_mode="Markdown")
        return False

    await status_msg.edit_text("✂️ **Vídeo baixado!** Analisando duração e processando mídia...", parse_mode="Markdown")
    
    # Lógica de truncamento para Shorts (se o vídeo estiver entre 3 e 4 minutos, ajusta para 2.55 min/175s)
    loop = asyncio.get_running_loop()
    duration = await loop.run_in_executor(None, get_video_duration, temp_video_path)
    
    if 180.0 < duration <= 240.0:
        await status_msg.edit_text(f"✂️ **Duração do vídeo:** {duration:.1f}s (> 3min). Truncando para 175s (2.5min)...", parse_mode="Markdown")
        truncated_path = os.path.join(uploads_dir, "video_original_truncated.mp4")
        if os.path.exists(truncated_path):
            try: os.remove(truncated_path)
            except: pass
            
        truncate_success = await loop.run_in_executor(None, truncate_video, temp_video_path, truncated_path, 175.0)
        if truncate_success:
            try:
                os.remove(temp_video_path)
                os.rename(truncated_path, temp_video_path)
                await status_msg.edit_text(f"✂️ **Vídeo ajustado!** Extraindo faixa de áudio em MP3 via FFmpeg...", parse_mode="Markdown")
            except Exception as e:
                logger.error(f"Erro ao substituir vídeo truncado: {e}")
        else:
            await status_msg.edit_text(f"⚠️ Falha no truncamento. Usando vídeo original.", parse_mode="Markdown")
            
    # Extrai o áudio
    audio_success = await loop.run_in_executor(None, extract_audio, temp_video_path, temp_audio_path)
    if not audio_success:
        await status_msg.edit_text("❌ Falha ao extrair áudio com FFmpeg.", parse_mode="Markdown")
        return False

    await status_msg.edit_text("📤 **Processamento local concluído!** Iniciando upload para o Google Drive...", parse_mode="Markdown")

    try:
        drive = DriveManager()
        
        # Upload do vídeo
        await status_msg.edit_text("📤 Subindo vídeo `video_original.mp4` para `DRAMA/PIPELINE/ATIVO/`...", parse_mode="Markdown")
        video_success = await loop.run_in_executor(None, drive.salvar, temp_video_path, "DRAMA/PIPELINE/ATIVO/video_original.mp4")
        
        # Upload do áudio
        await status_msg.edit_text("📤 Subindo áudio `drama_audio.mp3` para `DRAMA/AUDIO_DUB/INPUT/`...", parse_mode="Markdown")
        audio_success = await loop.run_in_executor(None, drive.salvar, temp_audio_path, "DRAMA/AUDIO_DUB/INPUT/drama_audio.mp3")

        if not video_success or not audio_success:
            await status_msg.edit_text("❌ Erro ao enviar os arquivos para o Google Drive.", parse_mode="Markdown")
            return False

        # Registra os uploads na sessão em memória do bot para comandos locais
        user_uploads[chat_id] = {
            "video": temp_video_path,
            "audio": temp_audio_path
        }

        success_text = (
            f"✅ **Drama Baixado e Configurado com Sucesso!**\n\n"
            f"🎬 **Duração:** {get_video_duration(temp_video_path):.1f}s\n"
            f"📂 **Arquivos no Drive:**\n"
            f"├ 🎥 `video_original.mp4` em `DRAMA/PIPELINE/ATIVO/`\n"
            f"└ 🎵 `drama_audio.mp3` em `DRAMA/AUDIO_DUB/INPUT/`\n\n"
            f"🚀 **Próximo passo:** Use o comando `/novo Nome do Drama` para iniciar o pipeline."
        )
        await status_msg.edit_text(success_text, parse_mode="Markdown")
        return True

    except Exception as e:
        logger.error(f"Erro no upload/conclusão: {e}")
        await status_msg.edit_text(f"❌ Erro na finalização/upload do Drive: `{e}`", parse_mode="Markdown")
        return False
