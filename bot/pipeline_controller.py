"""
Pipeline Controller - Orquestrador Central
Gerencia o fluxo completo de processamento de video.
"""

import os
import re
import asyncio
from bot.database import (
    create_project, update_step, get_project,
    mark_project_completed, mark_project_waiting_config
)
from bot.drive_manager import DriveManager, split_video, merge_videos, DRIVE_ATIVO, DRIVE_OMNI
from bot.github_actions import dispatch_workflow, dispatch_parallel


class PipelineController:
    """Controlador central do pipeline de processamento."""

    def __init__(self):
        self.drive = DriveManager()

    def iniciar_projeto(self, project_name, chat_id,
                               video_path, audio_path, mask_path=None, opts=None):
        """
        Etapa 1-3: Cria projeto, limpa Drive, faz upload e divide o video.
        Agora recebe opts para registrar Watermark e Enhancer.
        """
        project = create_project(project_name, chat_id)
        pid = str(project["id"])
        print(f"Projeto criado: {pid}")

        try:
            update_step(pid, "step_upload", "running", "Limpando Drive...")
            # Limpa pasta ATIVO e os JSONs de sessão do AUDIO_DUB
            self.drive.limpar_pasta_ativo()
            self.drive.limpar_audio_dub_cache()

            # O áudio vai para DRAMA/AUDIO_DUB/INPUT/drama_audio.mp3
            # (caminho que o notebook Omni espera)
            self.drive.salvar(audio_path, "DRAMA/AUDIO_DUB/INPUT/drama_audio.mp3")

            # O vídeo original também vai para ATIVO (para referência)
            self.drive.salvar(video_path, f"{DRIVE_ATIVO}/video_original.mp4")
            if mask_path and os.path.exists(mask_path):
                self.drive.salvar(mask_path, f"{DRIVE_ATIVO}/mask.png")

            update_step(pid, "step_upload", "done", "Upload concluido")

            update_step(pid, "step_split", "running", "Dividindo video...")
            
            # Obter duração do vídeo
            from bot.drive_manager import FFPROBE
            import math
            import subprocess
            result = subprocess.run(
                [FFPROBE, "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", video_path],
                capture_output=True, text=True
            )
            try:
                duration = float(result.stdout.strip())
            except Exception:
                duration = 165.0
            
            if duration <= 600:
                parts = 5
            elif duration <= 1200:
                parts = 10
            else:
                parts = min(30, math.ceil(duration / 110))
            
            # Registrar video_parts no banco
            from bot.database import _get_conn
            conn = _get_conn()
            cur = conn.cursor()
            cur.execute("UPDATE pipeline_projects SET video_parts = %s WHERE id = %s::uuid", (parts, pid))
            conn.commit()
            cur.close()
            conn.close()
            
            # Se opts diz que não quer, marcamos como skipped
            if opts:
                if not opts.get("watermark", True):
                    for i in range(1, 31):
                        update_step(pid, f"step_watermark_pt{i}", "skipped", "User disabled")
                if not opts.get("enhancer", False):
                    for i in range(0, 31):
                        update_step(pid, f"step_enhancer_pt{i}", "skipped", "User disabled")
                else:
                    # Se enhancer ativo, pt0 inicia como skipped aguardando partes 1 a N
                    update_step(pid, "step_enhancer_pt0", "skipped", "Aguardando partes 1-N")
            
            # Marcar partes não utilizadas como skipped
            for i in range(parts + 1, 31):
                update_step(pid, f"step_watermark_pt{i}", "skipped", "Excedente")
                update_step(pid, f"step_enhancer_pt{i}", "skipped", "Excedente")
                update_step(pid, f"step_render_pt{i}", "skipped", "Excedente")
                
            temp_dir = os.path.join(os.path.dirname(video_path), "split_temp")
            parts_paths = split_video(video_path, temp_dir, parts=parts)
            for p_path in parts_paths:
                if p_path.endswith(".json"):
                    self.drive.salvar(p_path, f"{DRIVE_ATIVO}/split_info.json")
                else:
                    base = os.path.basename(p_path)
                    if "video_pt" in base:
                        idx = int(base.split("video_pt")[-1].split(".mp4")[0])
                        self.drive.salvar(p_path, f"{DRIVE_ATIVO}/video_pt{idx}.mp4")
                        
            update_step(pid, "step_split", "done", f"Video dividido em {parts} partes")

            return project

        except Exception as e:
            update_step(pid, "step_upload", "error", str(e))
            raise

    def iniciar_projeto_manual(self, project_name, chat_id,
                               video_path, audio_path, mask_path=None, opts=None):
        """
        Inicia o projeto mas não dispara o Omni. 
        Define os status como 'manual' para que o _pipeline_poll_loop o ignore.
        """
        project = create_project(project_name, chat_id)
        pid = str(project["id"])
        print(f"Projeto manual criado: {pid}")

        try:
            update_step(pid, "step_upload", "running", "Limpando Drive...")
            self.drive.limpar_pasta_ativo()
            self.drive.limpar_audio_dub_cache()

            self.drive.salvar(audio_path, "DRAMA/AUDIO_DUB/INPUT/drama_audio.mp3")
            self.drive.salvar(video_path, f"{DRIVE_ATIVO}/video_original.mp4")
            if mask_path and os.path.exists(mask_path):
                self.drive.salvar(mask_path, f"{DRIVE_ATIVO}/mask.png")

            update_step(pid, "step_upload", "done", "Upload concluido")

            update_step(pid, "step_split", "running", "Dividindo video...")
            
            # Obter duração do vídeo
            from bot.drive_manager import FFPROBE
            import math
            import subprocess
            result = subprocess.run(
                [FFPROBE, "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", video_path],
                capture_output=True, text=True
            )
            duration = float(result.stdout.strip())
            
            if duration <= 600:
                parts = 5
            elif duration <= 1200:
                parts = 10
            else:
                parts = min(30, math.ceil(duration / 110))
            
            # Registrar video_parts no banco
            from bot.database import _get_conn
            conn = _get_conn()
            cur = conn.cursor()
            cur.execute("UPDATE pipeline_projects SET video_parts = %s WHERE id = %s::uuid", (parts, pid))
            conn.commit()
            cur.close()
            conn.close()
            
            # Marcar partes não utilizadas como skipped
            for i in range(parts + 1, 31):
                update_step(pid, f"step_watermark_pt{i}", "skipped", "Excedente")
                update_step(pid, f"step_enhancer_pt{i}", "skipped", "Excedente")
                update_step(pid, f"step_render_pt{i}", "skipped", "Excedente")
                
            temp_dir = os.path.join(os.path.dirname(video_path), "split_temp")
            parts_paths = split_video(video_path, temp_dir, parts=parts)
            for p_path in parts_paths:
                if p_path.endswith(".json"):
                    self.drive.salvar(p_path, f"{DRIVE_ATIVO}/split_info.json")
                else:
                    base = os.path.basename(p_path)
                    if "video_pt" in base:
                        idx = int(base.split("video_pt")[-1].split(".mp4")[0])
                        self.drive.salvar(p_path, f"{DRIVE_ATIVO}/video_pt{idx}.mp4")
            
            # Definir todos os passos como 'manual'
            update_step(pid, "step_split", "done", f"Video dividido em {parts} partes")
            update_step(pid, "step_omni", "manual", "")
            update_step(pid, "step_config_ready", "manual", "")
            for i in range(1, 31):
                update_step(pid, f"step_watermark_pt{i}", "manual", "")
            for i in range(0, 31):
                update_step(pid, f"step_enhancer_pt{i}", "manual", "")
                update_step(pid, f"step_render_pt{i}", "manual", "")
            update_step(pid, "step_merge", "manual", "")

            return project

        except Exception as e:
            update_step(pid, "step_upload", "error", str(e))
            raise

    # ------------------ CHECKERS DE DEPENDÊNCIA ------------------
    def check_omni_ready(self):
        arquivos = self.drive.listar_arquivos("DRAMA/AUDIO_DUB/INPUT")
        if not any(a["name"] == "drama_audio.mp3" for a in arquivos):
            return False, "drama_audio.mp3 não encontrado em DRAMA/AUDIO_DUB/INPUT"
        return True, ""

    def check_watermark_ready(self, part=None, total_parts=None):
        arquivos_ativo = self.drive.listar_arquivos(DRIVE_ATIVO)
        pts_ok = any(a["name"].startswith("video_pt") for a in arquivos_ativo)
        if not pts_ok:
            return False, "Partes de vídeo não encontradas no DRIVE ATIVO."
        return True, ""

    def check_enhancer_ready(self, part=None, total_parts=None):
        arquivos_wm = self.drive.listar_arquivos("DRAMA/PIPELINE/WATERMARK")
        arquivos_ativo = self.drive.listar_arquivos("DRAMA/PIPELINE/ATIVO")
        if part is not None:
            if part == 0:
                has_v0 = any(a["name"] == "video_pt0.mp4" for a in arquivos_ativo)
                has_wm0 = any(a["name"] == "pt0_limpo.mp4" for a in arquivos_wm)
                if not (has_v0 or has_wm0):
                    return False, "Vídeo pt0 da introdução não encontrado."
                return True, ""
            has_wm = any(a["name"] == f"pt{part}_limpo.mp4" for a in arquivos_wm)
            has_v = any(a["name"] == f"video_pt{part}.mp4" for a in arquivos_ativo)
            if not (has_wm or has_v):
                return False, f"Vídeo pt{part} não encontrado no Drive."
        return True, ""

    def check_render_ready(self, part=None, total_parts=None):
        return True, ""

    def check_merge_ready(self, total_parts=None):
        arquivos = self.drive.listar_arquivos("DRAMA/PIPELINE/RENDER")
        parts_to_check = range(1, (total_parts or 5) + 1)
        for i in parts_to_check:
            if not any(a["name"] == f"pt{i}_renderizado.mp4" for a in arquivos):
                return False, f"pt{i}_renderizado.mp4 não encontrado no RENDER."
        return True, ""
    # -----------------------------------------------------------

    def disparar_omni_imediatamente(self, project_id):
        """Etapa inicial: Dispara Omni (Dublagem) imediatamente após upload."""
        update_step(project_id, "step_omni", "running")
        dispatch_workflow("omni", project_id)

    def gerar_seo_automatico(self, project_id):
        """
        Chamado quando step_cel5 (tradução) é marcado como done.
        Baixa os JSONs do Drive, envia pro SEO server e retorna o guia.
        """
        import json, requests, tempfile, os
        SEO_URL = os.getenv("SEO_SERVER_URL", "http://localhost:3333")

        tmp = tempfile.mkdtemp()
        try:
            trad_path = os.path.join(tmp, "traducao_simplificada.json")
            ident_path = os.path.join(tmp, "identificacao_drama.json")

            self.drive.baixar("DRAMA/AUDIO_DUB/traducao_simplificada.json", trad_path)
            self.drive.baixar("DRAMA/AUDIO_DUB/identificacao_drama.json", ident_path)

            with open(trad_path, "r", encoding="utf-8") as f:
                roteiro = json.load(f)
            with open(ident_path, "r", encoding="utf-8") as f:
                identificacao = json.load(f)

            proj = get_project(project_id)
            ep_num = 1
            if proj and proj.get("project_name"):
                m = re.search(r"_EP(\d+)", proj.get("project_name"), re.IGNORECASE)
                if m:
                    ep_num = int(m.group(1))

            if isinstance(identificacao, dict):
                identificacao["episodio_num"] = ep_num
                identificacao["sequencia"] = f"EP {ep_num}"

            resp = requests.post(f"{SEO_URL}/api/auto-guide",
                json={"roteiro": roteiro, "identificacao": identificacao},
                timeout=120)
            resp.raise_for_status()
            data = resp.json()
            guia = data.get("guia")

            if guia:
                guia_file = os.path.join(tmp, "guia_postagem.json")
                with open(guia_file, "w", encoding="utf-8") as f:
                    json.dump(guia, f, ensure_ascii=False, indent=2)

                print(f"[{project_id}] Uploading guia_postagem.json para Drive (DRAMA/PIPELINE/FINAL)...")
                self.drive.upload(guia_file, "DRAMA/PIPELINE/FINAL/guia_postagem.json")
                print(f"[{project_id}] guia_postagem.json enviado com sucesso para o Drive!")

            return guia, roteiro, identificacao
        except Exception as e:
            print(f"[SEO] Erro ao gerar SEO: {e}")
            return None, None, None
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def preparar_sessao_seo(self, project_id, chat_id, telegram_info=None):
        """
        Cria sessão SEO e inicia pré-análise + pré-extração de frames em background.
        Retorna o token da sessão.
        telegram_info: dict com {"token": str, "message_id": int, "guia": dict}
        """
        import json, requests, tempfile, os, threading, shutil
        SEO_URL = os.getenv("SEO_SERVER_URL", "http://localhost:3333")

        tmp = tempfile.mkdtemp()
        try:
            trad_path = os.path.join(tmp, "traducao_simplificada.json")
            ident_path = os.path.join(tmp, "identificacao_drama.json")

            self.drive.baixar("DRAMA/AUDIO_DUB/traducao_simplificada.json", trad_path)
            self.drive.baixar("DRAMA/AUDIO_DUB/identificacao_drama.json", ident_path)

            with open(trad_path, "r", encoding="utf-8") as f:
                roteiro = json.load(f)
            with open(ident_path, "r", encoding="utf-8") as f:
                identificacao = json.load(f)

            # Preparar payload
            payload = {
                "project_id": project_id,
                "chat_id": chat_id,
                "roteiro": roteiro,
                "identificacao": identificacao
            }
            if telegram_info:
                payload["telegram_token"] = telegram_info.get("token")
                payload["message_id"] = telegram_info.get("message_id")
                payload["guia"] = telegram_info.get("guia")

            # Criar sessão no servidor SEO
            resp = requests.post(f"{SEO_URL}/api/create-seo-session", json=payload, timeout=10)
            resp.raise_for_status()
            token = resp.json()["token"]

            # Encontrar vídeo local
            video_local = self._encontrar_video_local(project_id)
            if not video_local:
                # Tentar baixar do Drive em background — salva em uploads/ (permanente)
                base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                uploads_dir = os.path.join(base_dir, "uploads")
                os.makedirs(uploads_dir, exist_ok=True)
                vid_dest = os.path.abspath(os.path.join(uploads_dir, f"seo_video_{project_id[:8]}.mp4"))
                
                def baixar_e_pre_analisar():
                    try:
                        self.drive.baixar("DRAMA/PIPELINE/ATIVO/video_original.mp4", vid_dest)
                        requests.post(f"{SEO_URL}/api/pre-analyze",
                            json={"token": token, "video_path": vid_dest}, timeout=10)
                    except Exception as e:
                        print(f"[SEO] Erro ao baixar vídeo para pré-análise: {e}")
                    finally:
                        shutil.rmtree(tmp, ignore_errors=True)
                threading.Thread(target=baixar_e_pre_analisar, daemon=True).start()
            else:
                # Vídeo já existe localmente — chamar pre-analyze direto
                def pre_analisar():
                    try:
                        requests.post(f"{SEO_URL}/api/pre-analyze",
                            json={"token": token, "video_path": video_local}, timeout=10)
                    except Exception as e:
                        print(f"[SEO] Erro na pré-análise: {e}")
                    finally:
                        shutil.rmtree(tmp, ignore_errors=True)
                threading.Thread(target=pre_analisar, daemon=True).start()

            return token
        except Exception as e:
            print(f"[SEO] Erro ao preparar sessão: {e}")
            shutil.rmtree(tmp, ignore_errors=True)
            return None

    def _encontrar_video_local(self, project_id):
        """Procura o vídeo original nos uploads locais."""
        import glob
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        uploads_dir = os.path.join(base_dir, "uploads")
        
        padroes = [
            os.path.join(uploads_dir, f"*{project_id}*.mp4"),
            os.path.join(uploads_dir, "*.mp4")
        ]
        for p in padroes:
            files = glob.glob(p)
            if files:
                return os.path.abspath(files[0])
        return None

    def disparar_watermark(self, project_id, parts_list):
        for i in parts_list: update_step(project_id, f"step_watermark_pt{i}", "running")
        dispatch_parallel([f"wm-pt{i}" for i in parts_list], project_id)

    def disparar_enhancer(self, project_id, parts_list):
        for i in parts_list: update_step(project_id, f"step_enhancer_pt{i}", "running")
        dispatch_parallel([f"enhancer-pt{i}" for i in parts_list], project_id)

    def criar_sessao_videorender(self, project_id, session_url):
        """Etapa 7: Marca sessao criada e envia link pro Telegram."""
        mark_project_waiting_config(project_id, session_url)

    def disparar_render(self, project_id, parts_list):
        for i in parts_list: update_step(project_id, f"step_render_pt{i}", "running")
        dispatch_parallel([f"render-pt{i}" for i in parts_list], project_id)

    def disparar_merge(self, project_id):
        """Etapa 10: Dispara merge final."""
        update_step(project_id, "step_merge", "running")
        dispatch_workflow("merge", project_id)

    def converter_json_para_ass(self, project_id):
        """
        Gera o arquivo ASS final combinando:
        - O subtitleStyle do videorender-project.json (definido pelo usuário no frontend)
        - O traducao.srt gerado pelo Omni (conteúdo real das legendas)
        
        Se o frontend já enviou um ASS com conteúdo real (não placeholder), ele mantém.
        """
        import tempfile
        import shutil
        import json
        import re
        print(f"[{project_id}] Iniciando geração do ASS final...")
        try:
            tmp_dir = tempfile.mkdtemp()
            config_path = os.path.join(tmp_dir, "videorender-project.json")
            srt_path = os.path.join(tmp_dir, "omni_output.srt")
            existing_ass = os.path.join(tmp_dir, "legendas_existente.ass")

            # Baixar config do VideoRender
            has_config = self.drive.baixar("DRAMA/PIPELINE/OMNI/videorender-project.json", config_path)
            has_srt = self.drive.baixar("DRAMA/PIPELINE/OMNI/omni_output.srt", srt_path)
            if not has_srt or not os.path.exists(srt_path):
                try:
                    q = "trashed=false and name contains '.srt' and not name contains 'intro'"
                    res = self.drive.service.files().list(q=q, fields="files(id, name)").execute()
                    f_list = res.get("files", [])
                    if f_list:
                        best_srt = f_list[0]
                        print(f"[{project_id}] Baixando SRT flexível: {best_srt['name']}")
                        has_srt = self.drive.baixar_por_id(best_srt["id"], srt_path)
                        if has_srt and os.path.exists(srt_path):
                            self.drive.salvar(srt_path, "DRAMA/PIPELINE/OMNI/omni_output.srt")
                except Exception as ex_s:
                    print(f"[{project_id}] Erro ao buscar SRT flexível: {ex_s}")

            if not has_srt or not os.path.exists(srt_path):
                print(f"[{project_id}] AVISO: traducao.srt não encontrado. Pulando geração de ASS.")
                shutil.rmtree(tmp_dir, ignore_errors=True)
                return

            # Ler estilo do config (ou usar defaults)
            style = {}
            if has_config and os.path.exists(config_path):
                import json as json_mod
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json_mod.load(f)
                # O config pode ter o estilo em "subtitles.style" (exportProject) ou "subtitleStyle"
                style = config.get("subtitles", {}).get("style", {})
                if not style:
                    style = config.get("subtitleStyle", {})
                video_info = config.get("video", {}).get("info", {})
                out_format = config.get("video", {}).get("outputFormat", "9:16")
            else:
                out_format = "9:16"
                video_info = {}

            # Defaults para o estilo
            font = style.get("font", "Montserrat")
            size = style.get("size", 52)
            color = style.get("color", "#FFFFFF")
            outline_color = style.get("outlineColor", "#000000")
            outline_width = style.get("outlineWidth", 2.5)
            shadow_offset = style.get("shadowOffset", 1)
            bold = style.get("bold", True)
            italic = style.get("italic", False)
            alignment = style.get("alignment", 2)
            position_y = style.get("positionY", 85)
            fade_in = style.get("fadeIn", 100)
            fade_out = style.get("fadeOut", 80)
            fade_in_pct = style.get("fadeInLimitPct", 20)
            fade_out_pct = style.get("fadeOutLimitPct", 15)
            bg_box = style.get("bgBox", False)
            bg_box_color = style.get("bgBoxColor", "#000000")
            bg_box_opacity = style.get("bgBoxOpacity", 0.5)
            all_caps = style.get("allCaps", False)
            srt_type = style.get("type") or style.get("srt_type") or "normal"

            glow = style.get("glow", False)
            glow_color = style.get("glowColor", "#FF6B6B")
            glow_blur = style.get("glowBlur", 10)
            glow_intensity = style.get("glowIntensity", 1)


            # Resolução do vídeo
            if out_format == "9:16":
                play_w, play_h = 1080, 1920
            elif out_format == "1:1":
                play_w, play_h = 1080, 1080
            elif out_format == "4:5":
                play_w, play_h = 1080, 1350
            else:
                play_w, play_h = 1920, 1080

            # Converter cores para formato ASS (&HAABBGGRR)
            def hex_to_ass(h, alpha=0):
                h = h.lstrip("#")
                if len(h) < 6:
                    h = "FFFFFF"
                r, g, b = h[0:2], h[2:4], h[4:6]
                a = f"{int(alpha * 255):02X}"
                return f"&H{a}{b}{g}{r}"

            primary_col = hex_to_ass(color)
            outline_col = hex_to_ass(outline_color)
            back_col = hex_to_ass(bg_box_color, 1 - bg_box_opacity) if bg_box else "&HFFFFFFFF"
            ass_font_size = round((size / 1920) * play_h)
            bold_flag = "-1" if bold else "0"
            italic_flag = "-1" if italic else "0"
            margin_v = round(play_h * (1 - position_y / 100))

            # Tentar extrair o cabeçalho de estilos do legendas.ass placeholder do frontend se existir
            placeholder_ass_path = os.path.join(tmp_dir, "placeholder_legendas.ass")
            has_placeholder = (
                self.drive.baixar("DRAMA/PIPELINE/OMNI/legendas.ass", placeholder_ass_path) or
                self.drive.baixar("DRAMA/AUDIO_DUB/legendas.ass", placeholder_ass_path)
            )

            custom_header = None
            if has_placeholder and os.path.exists(placeholder_ass_path):
                try:
                    with open(placeholder_ass_path, "r", encoding="utf-8") as f_ph:
                        ph_text = f_ph.read()
                    if "[V4+ Styles]" in ph_text and "[Events]" in ph_text:
                        header_part = ph_text.split("[Events]")[0].strip()
                        custom_header = f"{header_part}\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
                        print(f"[{project_id}] Estilo extraído diretamente do legendas.ass placeholder do frontend!")
                except Exception as ex_ph:
                    print(f"[{project_id}] Aviso ao ler placeholder legendas.ass: {ex_ph}")

            if custom_header:
                header = custom_header
            else:
                header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {play_w}
PlayResY: {play_h}
ScaledBorderAndShadow: yes
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},{ass_font_size},{primary_col},{primary_col},{outline_col},{back_col},{bold_flag},{italic_flag},0,0,100,100,0,0,1,{outline_width},{shadow_offset},{alignment},0,0,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

            def srt_to_ass_time(srt_time):
                srt_time = srt_time.strip().replace(",", ".")
                parts = srt_time.split(":")
                if len(parts) == 3:
                    h = int(parts[0])
                    m = parts[1]
                    s = parts[2]
                    if "." in s:
                        sec, ms = s.split(".")
                        cs = ms[:2].ljust(2, "0")
                    else:
                        sec = s
                        cs = "00"
                    return f"{h}:{m}:{int(sec):02d}.{cs}"
                return "0:00:00.00"

            def time_to_ms(t):
                p = t.replace(",", ".").strip().split(":")
                return (int(p[0]) * 3600 + int(p[1]) * 60 + float(p[2])) * 1000

            def ms_to_ass_time(ms):
                ms = max(0, ms)
                total_s = ms / 1000.0
                h = int(total_s // 3600)
                m = int((total_s % 3600) // 60)
                s = total_s % 60
                sec = int(s)
                cs = int((s - sec) * 100)
                return f"{h}:{m:02d}:{sec:02d}.{cs:02d}"

            def wrap_text(text, max_chars=70):
                """Quebra texto em no maximo 2 linhas usando \\N do ASS (1080p)."""
                # Respeitar \n do SRT como ponto de quebra preferencial
                if '\\n' in text:
                    parts = text.split('\\n', 1)  # max 1 quebra = 2 linhas
                    return '\\N'.join(p.strip() for p in parts)
                if len(text) <= max_chars:
                    return text
                # Encontrar melhor ponto de quebra (1 unica) perto do meio
                mid = len(text) // 2
                best = -1
                best_score = 9999
                for i, ch in enumerate(text):
                    if ch == ' ':
                        score = abs(i - mid)
                        # Bonus para virgula antes do espaco
                        if i > 0 and text[i-1] == ',':
                            score -= 20
                        if score < best_score:
                            best_score = score
                            best = i
                if best <= 0:
                    return text
                return text[:best].rstrip() + '\\N' + text[best:].lstrip()

            # Parsear SRT e coletar blocos com timestamps
            parsed_blocks = []
            with open(srt_path, "r", encoding="utf-8") as f:
                srt_content = f.read()

            blocks = re.split(r'\n\s*\n', srt_content.strip())
            for block in blocks:
                lines = block.strip().split('\n')
                if len(lines) >= 3:
                    time_line = lines[1]
                    raw_text = " ".join(lines[2:])
                    if all_caps:
                        raw_text = raw_text.upper()

                    if "-->" in time_line:
                        t_start, t_end = time_line.split("-->")
                        try:
                            start_ms = time_to_ms(t_start)
                            end_ms = time_to_ms(t_end)
                        except Exception:
                            continue

                        texto = wrap_text(raw_text)
                        parsed_blocks.append({
                            "start_ms": start_ms,
                            "end_ms": end_ms,
                            "text": texto
                        })

            project_db = get_project(project_id)
            is_word_by_word = project_db and project_db.get("srt_type") == "word_by_word"
            words_per_block = style.get("wordsPerBlock", 1)

            if is_word_by_word and words_per_block > 1:
                grouped_blocks = []
                current_group = []
                
                for b in parsed_blocks:
                    current_group.append(b)
                    
                    has_strong = any(p in b["text"] for p in ['.', '?', '!'])
                    has_comma = ',' in b["text"]
                    
                    cut = False
                    if has_strong:
                        cut = True
                    elif len(current_group) >= words_per_block:
                        cut = True
                    elif has_comma and len(current_group) >= max(1, words_per_block - 2):
                        cut = True
                        
                    if cut:
                        grouped_blocks.append({
                            "start_ms": current_group[0]["start_ms"],
                            "end_ms": current_group[-1]["end_ms"],
                            "text": wrap_text(" ".join(g["text"] for g in current_group))
                        })
                        current_group = []
                        
                if current_group:
                    grouped_blocks.append({
                        "start_ms": current_group[0]["start_ms"],
                        "end_ms": current_group[-1]["end_ms"],
                        "text": wrap_text(" ".join(g["text"] for g in current_group))
                    })
                parsed_blocks = grouped_blocks

            # Ordenar por start_ms e corrigir sobreposições
            parsed_blocks.sort(key=lambda b: b["start_ms"])
            for i in range(len(parsed_blocks) - 1):
                if parsed_blocks[i]["end_ms"] > parsed_blocks[i + 1]["start_ms"]:
                    # Trim end do bloco atual para não sobrepor o próximo
                    parsed_blocks[i]["end_ms"] = parsed_blocks[i + 1]["start_ms"]

            # Posição absoluta para evitar que o bord desloque as camadas
            pos_x = play_w // 2
            pos_y = play_h - margin_v
            pos_tag = f"\\pos({pos_x},{pos_y})"

            # Gerar dialogues
            dialogues = []
            for pb in parsed_blocks:
                start = ms_to_ass_time(pb["start_ms"])
                end = ms_to_ass_time(pb["end_ms"])
                texto = pb["text"]
                dur_ms = pb["end_ms"] - pb["start_ms"]

                # Calcular fade
                try:
                    eff_in = min(fade_in, dur_ms * fade_in_pct / 100)
                    eff_out = min(fade_out, dur_ms * fade_out_pct / 100)
                    fade_tag = f"\\\\fad({int(eff_in)},{int(eff_out)})"
                except Exception:
                    fade_tag = ""

                if glow:
                    glow_col = hex_to_ass(glow_color)
                    gAlpha = f"{int((1 - min(1, glow_intensity)) * 255):02X}"
                    # Usa pos_tag para travar as camadas na mesma posição física
                    glow_effect = f"{pos_tag}\\1c{glow_col}\\3c{glow_col}\\1a&H{gAlpha}&\\3a&H{gAlpha}&\\bord{max(outline_width, glow_blur)}\\blur{glow_blur}"
                    dialogues.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{{{fade_tag}{glow_effect}}}{texto}")
                    main_effect = f"{pos_tag}\\1c{primary_col}\\3c{outline_col}\\1a&H00&\\3a&H00&\\bord{outline_width}\\blur0"
                    dialogues.append(f"Dialogue: 1,{start},{end},Default,,0,0,0,,{{{fade_tag}{main_effect}}}{texto}")
                else:
                    dialogues.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{{{fade_tag}{pos_tag}}}{texto}")

            out_ass = os.path.join(tmp_dir, "legendas_final.ass")
            with open(out_ass, "w", encoding="utf-8") as f:
                f.write(header)
                f.write("\n".join(dialogues))

            self.drive.salvar(out_ass, "DRAMA/PIPELINE/OMNI/legendas.ass")
            print(f"[{project_id}] ASS final gerado ({len(dialogues)} diálogos) e salvo no Drive.")

            # Gerar intro_legendas.ass se intro_output.srt ou intro_info.json existir
            intro_srt_path = os.path.join(tmp_dir, "intro_output.srt")
            has_intro_srt = self.drive.baixar("DRAMA/PIPELINE/OMNI/intro_output.srt", intro_srt_path) or self.drive.baixar("DRAMA/AUDIO_DUB/intro_output.srt", intro_srt_path)
            intro_json_path = os.path.join(tmp_dir, "intro_info.json")
            has_intro_json = self.drive.baixar("DRAMA/AUDIO_DUB/intro_info.json", intro_json_path)

            if has_intro_srt or has_intro_json:
                try:
                    intro_blocks = []
                    if has_intro_srt and os.path.exists(intro_srt_path):
                        with open(intro_srt_path, "r", encoding="utf-8") as f_is:
                            intro_srt_content = f_is.read()
                        i_blocks = re.split(r'\n\s*\n', intro_srt_content.strip())
                        for ib in i_blocks:
                            i_lines = ib.strip().split('\n')
                            if len(i_lines) >= 3 and "-->" in i_lines[1]:
                                t_s, t_e = i_lines[1].split("-->")
                                try:
                                    s_ms = time_to_ms(t_s)
                                    e_ms = time_to_ms(t_e)
                                    raw_t = " ".join(i_lines[2:])
                                    if all_caps: raw_t = raw_t.upper()
                                    intro_blocks.append({"start_ms": s_ms, "end_ms": e_ms, "text": wrap_text(raw_t)})
                                except Exception: pass
                    
                    if not intro_blocks and has_intro_json and os.path.exists(intro_json_path):
                        with open(intro_json_path, "r", encoding="utf-8") as fj:
                            intro_data = json.load(fj)
                        intro_text = intro_data.get("intro_text", "")
                        words = intro_text.split()
                        if words:
                            time_per_word = 10000 / len(words)
                            for idx_w, w in enumerate(words):
                                s_ms = idx_w * time_per_word
                                e_ms = (idx_w + 1) * time_per_word
                                txt = w.upper() if all_caps else w
                                intro_blocks.append({"start_ms": s_ms, "end_ms": e_ms, "text": txt})

                    # Se o estilo não for palavra por palavra, agrupa palavras da introdução em frases normais
                    if srt_type != "word_by_word" and intro_blocks:
                        grouped_intro = []
                        curr_words = []
                        curr_start = None
                        curr_end = None
                        for ib in intro_blocks:
                            if curr_start is None:
                                curr_start = ib["start_ms"]
                            word = ib["text"]
                            proposed_text = " ".join(curr_words + [word])
                            if len(proposed_text) > 42 or (curr_end and ib["start_ms"] - curr_end > 700):
                                if curr_words:
                                    txt_fin = " ".join(curr_words)
                                    if all_caps: txt_fin = txt_fin.upper()
                                    grouped_intro.append({"start_ms": curr_start, "end_ms": curr_end, "text": wrap_text(txt_fin)})
                                curr_words = [word]
                                curr_start = ib["start_ms"]
                            else:
                                curr_words.append(word)
                            curr_end = ib["end_ms"]
                        if curr_words and curr_start is not None and curr_end is not None:
                            txt_fin = " ".join(curr_words)
                            if all_caps: txt_fin = txt_fin.upper()
                            grouped_intro.append({"start_ms": curr_start, "end_ms": curr_end, "text": wrap_text(txt_fin)})
                        intro_blocks = grouped_intro
                    else:
                        for ib in intro_blocks:
                            if all_caps: ib["text"] = ib["text"].upper()
                            ib["text"] = wrap_text(ib["text"])

                    if intro_blocks:
                        intro_dialogues = []
                        for ib in intro_blocks:
                            st = ms_to_ass_time(ib["start_ms"])
                            et = ms_to_ass_time(ib["end_ms"])
                            tx = ib["text"]
                            if glow:
                                glow_col = hex_to_ass(glow_color)
                                gAlpha = f"{int((1 - min(1, glow_intensity)) * 255):02X}"
                                glow_effect = f"{pos_tag}\\1c{glow_col}\\3c{glow_col}\\1a&H{gAlpha}&\\3a&H{gAlpha}&\\bord{max(outline_width, glow_blur)}\\blur{glow_blur}"
                                intro_dialogues.append(f"Dialogue: 0,{st},{et},Default,,0,0,0,,{{{glow_effect}}}{tx}")
                                main_effect = f"{pos_tag}\\1c{primary_col}\\3c{outline_col}\\1a&H00&\\3a&H00&\\bord{outline_width}\\blur0"
                                intro_dialogues.append(f"Dialogue: 1,{st},{et},Default,,0,0,0,,{{{main_effect}}}{tx}")
                            else:
                                intro_dialogues.append(f"Dialogue: 0,{st},{et},Default,,0,0,0,,{{{pos_tag}}}{tx}")

                        out_intro_ass = os.path.join(tmp_dir, "intro_legendas.ass")
                        with open(out_intro_ass, "w", encoding="utf-8") as f:
                            f.write(header)
                            f.write("\n".join(intro_dialogues))
                            
                        self.drive.salvar(out_intro_ass, "DRAMA/PIPELINE/OMNI/intro_legendas.ass")
                        print(f"[{project_id}] ASS da introdução (intro_legendas.ass) gerado com {len(intro_dialogues)} diálogos e salvo no Drive.")
                except Exception as ie:
                    print(f"[{project_id}] Erro ao gerar ASS da introdução: {ie}")

            shutil.rmtree(tmp_dir, ignore_errors=True)

        except Exception as e:
            print(f"[{project_id}] Erro ao gerar ASS final: {e}")
            import traceback
            traceback.print_exc()


    def criar_pt0_introducao(self, project_id, project):
        """
        Gera o vídeo base da introdução pt0_limpo.mp4 recortando cenas do Enhanced (ou Watermark se Enhancer desativado).
        """
        import tempfile
        import shutil
        import json
        import subprocess
        
        print(f"[{project_id}] Iniciando criação do vídeo de introdução pt0...")
        tmp_dir = tempfile.mkdtemp()
        try:
            # 1. Baixar split_info.json e intro_info.json
            split_path = os.path.join(tmp_dir, "split_info.json")
            intro_path = os.path.join(tmp_dir, "intro_info.json")
            
            if not self.drive.baixar("DRAMA/PIPELINE/ATIVO/split_info.json", split_path):
                print(f"[{project_id}] split_info.json não encontrado no Drive.")
                return False
            if not self.drive.baixar("DRAMA/AUDIO_DUB/intro_info.json", intro_path):
                print(f"[{project_id}] intro_info.json não encontrado no Drive.")
                return False
                
            with open(split_path, "r", encoding="utf-8") as f:
                split_info = json.load(f)
            with open(intro_path, "r", encoding="utf-8") as f:
                intro_data = json.load(f)
                
            part_duration = split_info["part_duration"]
            scenes = intro_data.get("scenes", [])
            if not scenes:
                print(f"[{project_id}] Sem cenas listadas no intro_info.json.")
                return False
                
            # Limitar a exatamente 2 cenas conforme regra do usuário
            scenes = scenes[:2]
            clip_paths = []
            
            video_parts = project.get("video_parts", 5) or 5
            enhancer_enabled = any(project.get(f"step_enhancer_pt{i}") != "skipped" for i in range(1, video_parts + 1))
            
            for idx, scene in enumerate(scenes):
                t_start = scene["start"]
                # Achar em qual parte do vídeo cai este timestamp
                part_idx = int(t_start // part_duration) + 1
                part_idx = min(part_idx, video_parts) # Prevenir overflow
                
                rel_start = t_start % part_duration
                
                # Se o trecho estiver muito no final e estourar a duração da parte, ajustamos rel_start
                if rel_start + 5.0 > part_duration:
                    rel_start = max(0.0, part_duration - 5.0)
                    
                if enhancer_enabled:
                    drive_src = f"DRAMA/PIPELINE/ENHANCER/pt{part_idx}_enhanced.mp4"
                    local_src = os.path.join(tmp_dir, f"pt{part_idx}_enhanced.mp4")
                else:
                    drive_src = f"DRAMA/PIPELINE/WATERMARK/pt{part_idx}_limpo.mp4"
                    local_src = os.path.join(tmp_dir, f"pt{part_idx}_limpo.mp4")
                    
                print(f"[{project_id}] Baixando {drive_src} para recortar cena {idx+1}...")
                if not self.drive.baixar(drive_src, local_src):
                    print(f"[{project_id}] Vídeo fonte {drive_src} ainda não está pronto no Drive.")
                    return False
                    
                # Recortar 5 segundos usando FFmpeg
                clip_path = os.path.join(tmp_dir, f"clip_{idx}.mp4")
                from bot.drive_manager import FFMPEG
                cmd = [
                    FFMPEG, "-y", "-ss", str(rel_start), "-i", local_src,
                    "-t", "5.0", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
                    "-c:a", "copy", clip_path
                ]
                subprocess.run(cmd, check=True, capture_output=True)
                clip_paths.append(clip_path)
                
            if len(clip_paths) < 2:
                print(f"[{project_id}] Erro: não foi possível obter os 2 clipes para a intro.")
                return False
                
            # Concatena os 2 clipes (totalizando 10s)
            concat_txt = os.path.join(tmp_dir, "intro_concat.txt")
            with open(concat_txt, "w") as f_con:
                for c_path in clip_paths:
                    f_con.write(f"file '{os.path.abspath(c_path)}'\n")
                    
            pt0_limpo_path = os.path.join(tmp_dir, "pt0_limpo.mp4")
            cmd_concat = [
                FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", concat_txt,
                "-c", "copy", pt0_limpo_path
            ]
            subprocess.run(cmd_concat, check=True, capture_output=True)
            
            # Salvar no Drive como DRAMA/PIPELINE/WATERMARK/pt0_limpo.mp4
            self.drive.salvar(pt0_limpo_path, "DRAMA/PIPELINE/WATERMARK/pt0_limpo.mp4")
            print(f"[{project_id}] pt0_limpo.mp4 gerado com sucesso!")
            return True
            
        except Exception as e:
            print(f"[{project_id}] Erro ao criar pt0_limpo.mp4: {e}")
            import traceback
            traceback.print_exc()
            return False
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def verificar_e_avancar(self, project_id):
        """
        Verifica o status atual do projeto e avanca para a proxima etapa.
        Suporta fatiamento paralelo do Omni (main -> tts1..4 -> assemble)
        e fila de execução no Kaggle limitada a 7 concorrentes.
        """
        project = get_project(project_id)
        if not project:
            return

        video_parts = project.get("video_parts", 5) or 5
        
        # Obter estados atuais
        w_vals = [project.get(f"step_watermark_pt{i}") for i in range(1, video_parts + 1)]
        e_vals = [project.get(f"step_enhancer_pt{i}") for i in range(1, video_parts + 1)] # Sem pt0
        r_vals = [project.get(f"step_render_pt{i}") for i in range(0, video_parts + 1)] # Inclui pt0
        
        conf = project.get("step_config_ready")
        omni = project.get("step_omni")

        w_ok = all(v in ["done", "skipped"] for v in w_vals)
        e_ok = all(v in ["done", "skipped"] for v in e_vals)
        r_ok = all(v == "done" for v in r_vals)
        split_ok = project.get("step_split") == "done"

        # ── RECONCILIAÇÃO AUTOMÁTICA VIA DRIVE ──
        if w_ok and any(v not in ["done", "skipped"] for v in e_vals):
            try:
                arqs_enh = self.drive.listar_arquivos("DRAMA/PIPELINE/ENHANCER")
                for i in range(1, video_parts + 1):
                    if project.get(f"step_enhancer_pt{i}") not in ["done", "skipped"]:
                        if any(a["name"] == f"pt{i}_enhanced.mp4" for a in arqs_enh):
                            print(f"[{project_id}] Auto-sync Drive: pt{i}_enhanced.mp4 detectado. Atualizando step_enhancer_pt{i} = done.")
                            update_step(project_id, f"step_enhancer_pt{i}", "done")
                            project[f"step_enhancer_pt{i}"] = "done"
            except Exception as ex_sync_e:
                print(f"[{project_id}] Erro auto-sync enhancer: {ex_sync_e}")

        # Sanity check: se marcado como done no banco mas o arquivo não está no Drive, reseta para pending
        if any(v == "done" for v in e_vals):
            try:
                arqs_enh = self.drive.listar_arquivos("DRAMA/PIPELINE/ENHANCER")
                for i in range(1, video_parts + 1):
                    if project.get(f"step_enhancer_pt{i}") == "done":
                        if not any(a["name"] == f"pt{i}_enhanced.mp4" for a in arqs_enh):
                            print(f"[{project_id}] Drive sanity check: pt{i}_enhanced.mp4 ausente no Drive. Resetando step_enhancer_pt{i} = pending.")
                            update_step(project_id, f"step_enhancer_pt{i}", "pending")
                            project[f"step_enhancer_pt{i}"] = "pending"
            except Exception as ex_sc_e:
                print(f"[{project_id}] Erro sanity check enhancer: {ex_sc_e}")

        if conf == "done" and w_ok and e_ok and omni == "done" and any(v != "done" for v in r_vals):
            try:
                arqs_ren = self.drive.listar_arquivos("DRAMA/PIPELINE/RENDER")
                for i in range(0, video_parts + 1):
                    if project.get(f"step_render_pt{i}") != "done":
                        if any(a["name"] == f"pt{i}_renderizado.mp4" for a in arqs_ren):
                            print(f"[{project_id}] Auto-sync Drive: pt{i}_renderizado.mp4 detectado. Atualizando step_render_pt{i} = done.")
                            update_step(project_id, f"step_render_pt{i}", "done")
                            project[f"step_render_pt{i}"] = "done"
            except Exception as ex_sync_r:
                print(f"[{project_id}] Erro auto-sync render: {ex_sync_r}")

        # Sanity check render: se marcado como done no banco mas o arquivo não está no Drive, reseta para pending
        if any(v == "done" for v in r_vals):
            try:
                arqs_ren = self.drive.listar_arquivos("DRAMA/PIPELINE/RENDER")
                for i in range(0, video_parts + 1):
                    if project.get(f"step_render_pt{i}") == "done":
                        if not any(a["name"] == f"pt{i}_renderizado.mp4" for a in arqs_ren):
                            print(f"[{project_id}] Drive sanity check: pt{i}_renderizado.mp4 ausente no Drive. Resetando step_render_pt{i} = pending.")
                            update_step(project_id, f"step_render_pt{i}", "pending")
                            project[f"step_render_pt{i}"] = "pending"
            except Exception as ex_sc_r:
                print(f"[{project_id}] Erro sanity check render: {ex_sc_r}")

        if r_ok and project.get("step_merge") != "done":
            try:
                arqs_fin = self.drive.listar_arquivos("DRAMA/PIPELINE/FINAL")
                if any(a["name"] in ["video_final.mp4", "drama_final.mp4"] for a in arqs_fin):
                    print(f"[{project_id}] Auto-sync Drive: video_final.mp4 detectado em FINAL (com Renders OK). Atualizando step_merge = done.")
                    update_step(project_id, "step_merge", "done")
                    project["step_merge"] = "done"
            except Exception as ex_sync_m:
                print(f"[{project_id}] Erro auto-sync merge: {ex_sync_m}")

        # Re-avalia os estados após a reconciliação
        e_vals = [project.get(f"step_enhancer_pt{i}") for i in range(1, video_parts + 1)]
        r_vals = [project.get(f"step_render_pt{i}") for i in range(0, video_parts + 1)]
        e_ok = all(v in ["done", "skipped"] for v in e_vals)
        r_ok = all(v == "done" for v in r_vals)

        # Log de diagnóstico
        if conf == "done" and w_ok and e_ok and r_vals[1] == "pending": # pt1
            if omni != "done":
                print(f"[{project_id}] ⏳ Aguardando Omni (atual: {omni}) para disparar render.")

        if not split_ok:
            return

        # ── TRANSIÇÃO DO OMNI PARALELO ──
        if omni == "pending" and conf == "done":
            print(f"[{project_id}] Disparando etapa inicial: Omni-Main")
            self.disparar_omni_imediatamente(project_id)
            return
            
        elif omni == "main_done":
            print(f"[{project_id}] Omni-Main concluído. Disparando 4 TTS paralelos...")
            update_step(project_id, "step_omni", "tts_running")
            dispatch_parallel(["omni-tts-pt1", "omni-tts-pt2", "omni-tts-pt3", "omni-tts-pt4"], project_id)
            return
            
        elif omni == "tts_running":
            # Verificar se os 4 arquivos zip de áudio já estão no Drive
            arqs_dub = self.drive.listar_arquivos("DRAMA/AUDIO_DUB")
            tts_pt1_ok = any(a["name"] == "omni_tts_pt1.zip" for a in arqs_dub)
            tts_pt2_ok = any(a["name"] == "omni_tts_pt2.zip" for a in arqs_dub)
            tts_pt3_ok = any(a["name"] == "omni_tts_pt3.zip" for a in arqs_dub)
            tts_pt4_ok = any(a["name"] == "omni_tts_pt4.zip" for a in arqs_dub)
            
            if tts_pt1_ok and tts_pt2_ok and tts_pt3_ok and tts_pt4_ok:
                print(f"[{project_id}] Todos os 4 TTS concluídos. Disparando Omni-Assemble...")
                update_step(project_id, "step_omni", "assembling")
                dispatch_workflow("omni-assemble", project_id, extra_payload={"task_key": "omni-assemble"})
                return
            else:
                missing = []
                if not tts_pt1_ok: missing.append("pt1")
                if not tts_pt2_ok: missing.append("pt2")
                if not tts_pt3_ok: missing.append("pt3")
                if not tts_pt4_ok: missing.append("pt4")
                print(f"[{project_id}] ⏳ Aguardando zips do TTS: faltando {missing}")

        elif omni == "assembling":
            arqs_out = self.drive.listar_arquivos("DRAMA/AUDIO_DUB/OUTPUT")
            arqs_omni = self.drive.listar_arquivos("DRAMA/PIPELINE/OMNI")
            has_out_mp3 = any("_Completo.mp3" in a["name"] or a["name"].endswith(".mp3") for a in arqs_out)
            has_omni_mp3 = any(a["name"] == "audio_dublado.mp3" for a in arqs_omni)
            has_omni_srt = any(a["name"] == "omni_output.srt" for a in arqs_omni)
            has_out_srt = any(a["name"].endswith(".srt") for a in arqs_out)

            if (has_out_mp3 or has_omni_mp3) and (has_omni_srt or has_out_srt):
                print(f"[{project_id}] Auto-sync Drive: Omni-Assemble finalizado (áudio e srt encontrados). Atualizando step_omni = done.")
                update_step(project_id, "step_omni", "done")
                omni = "done"

        # Gerar ASS e copiar áudio do Omni assim que ambos estiverem prontos
        if conf == "done" and omni == "done":
            arqs_omni = self.drive.listar_arquivos("DRAMA/PIPELINE/OMNI")
            ass_item = next((a for a in arqs_omni if a["name"] == "legendas.ass"), None)
            srt_item = next((a for a in arqs_omni if a["name"] == "omni_output.srt"), None)
            cfg_item = next((a for a in arqs_omni if a["name"] == "videorender-project.json"), None)
            has_mp3 = any(a["name"] == "audio_dublado.mp3" for a in arqs_omni)

            should_regen = False
            if not ass_item or not has_mp3:
                should_regen = True
            elif ass_item:
                ass_mtime = ass_item.get("modifiedTime", "")
                srt_mtime = srt_item.get("modifiedTime", "") if srt_item else ""
                cfg_mtime = cfg_item.get("modifiedTime", "") if cfg_item else ""
                if srt_mtime and (not ass_mtime or srt_mtime > ass_mtime):
                    should_regen = True
                    print(f"[{project_id}] Novo omni_output.srt detectado ({srt_mtime} > {ass_mtime}). Regerando legendas.ass...")
                elif cfg_mtime and (not ass_mtime or cfg_mtime > ass_mtime):
                    should_regen = True
                    print(f"[{project_id}] Novo estilo em videorender-project.json detectado ({cfg_mtime} > {ass_mtime}). Regerando legendas.ass...")

            if should_regen:
                print(f"[{project_id}] Preparando arquivos do Omni e gerando ASS antecipadamente...")
                arquivos_out = self.drive.listar_arquivos("DRAMA/AUDIO_DUB/OUTPUT")
                mp3_file = (
                    next((a for a in arquivos_out if '_Completo.mp3' in a['name']), None) or
                    next((a for a in arquivos_out if a['name'].endswith('.mp3')), None)
                )
                srt_file = (
                    next((a for a in arquivos_out if '_Completo.srt' in a['name']), None) or
                    next((a for a in arquivos_out if a['name'].endswith('.srt')), None)
                )

                if mp3_file:
                    self.drive.copiar_arquivo(f"DRAMA/AUDIO_DUB/OUTPUT/{mp3_file['name']}", "DRAMA/PIPELINE/OMNI/audio_dublado.mp3")
                else:
                    arqs_in = self.drive.listar_arquivos("DRAMA/AUDIO_DUB/INPUT")
                    in_mp3 = next((a for a in arqs_in if a["name"] == "drama_audio.mp3"), None)
                    if in_mp3:
                        self.drive.copiar_arquivo("DRAMA/AUDIO_DUB/INPUT/drama_audio.mp3", "DRAMA/PIPELINE/OMNI/audio_dublado.mp3")
                if srt_file:
                    self.drive.copiar_arquivo(f"DRAMA/AUDIO_DUB/OUTPUT/{srt_file['name']}", "DRAMA/PIPELINE/OMNI/omni_output.srt")
                else:
                    # Busca flexível por qualquer .srt gerado no Drive
                    try:
                        q = "trashed=false and name contains '.srt' and not name contains 'intro'"
                        res = self.drive.service.files().list(q=q, fields="files(id, name)").execute()
                        f_list = res.get("files", [])
                        if f_list:
                            best_srt = f_list[0]
                            print(f"[{project_id}] SRT encontrado via busca flexível: {best_srt['name']}")
                            tmp_s = os.path.join(tempfile.gettempdir(), "omni_output.srt")
                            if self.drive.baixar_por_id(best_srt["id"], tmp_s):
                                self.drive.salvar(tmp_s, "DRAMA/PIPELINE/OMNI/omni_output.srt")
                    except Exception as ex_s:
                        print(f"[{project_id}] Erro busca flexível SRT: {ex_s}")

                self.converter_json_para_ass(project_id)

        # ── 1. CONFIG SALVA -> FILA WATERMARK (MÁXIMO 7) ──
        if conf == "done" and not w_ok:
            running_wm = sum(1 for i in range(1, video_parts + 1) if project.get(f"step_watermark_pt{i}") == "running")
            if running_wm < 7:
                pending_wm = [i for i in range(1, video_parts + 1) if project.get(f"step_watermark_pt{i}") == "pending"]
                to_trigger = pending_wm[:7 - running_wm]
                if to_trigger:
                    print(f"[{project_id}] Fila Watermark: Disparando partes {to_trigger} (Running: {running_wm})")
                    self.disparar_watermark(project_id, to_trigger)
                    return

        # ── 2. WATERMARK OK -> FILA ENHANCER (MÁXIMO 7) ──
        if w_ok and not e_ok:
            all_wm_skipped = all(project.get(f"step_watermark_pt{i}") == "skipped" for i in range(1, video_parts + 1))
            if all_wm_skipped:
                arqs_wm = self.drive.listar_arquivos("DRAMA/PIPELINE/WATERMARK")
                has_all_limpos = all(any(a["name"] == f"pt{i}_limpo.mp4" for a in arqs_wm) for i in range(1, video_parts + 1))
                if not has_all_limpos:
                    print(f"[{project_id}] Watermark pulado. Copiando vídeo original para WATERMARK/...")
                    for i in range(1, video_parts + 1):
                        self.drive.copiar_arquivo(f"DRAMA/PIPELINE/ATIVO/video_pt{i}.mp4", f"DRAMA/PIPELINE/WATERMARK/pt{i}_limpo.mp4")

            enhancer_enabled = any(project.get(f"step_enhancer_pt{i}") != "skipped" for i in range(1, video_parts + 1))
            
            if not enhancer_enabled:
                arqs_enh = self.drive.listar_arquivos("DRAMA/PIPELINE/ENHANCER")
                has_all_enhanced = all(any(a["name"] == f"pt{i}_enhanced.mp4" for a in arqs_enh) for i in range(1, video_parts + 1))
                if not has_all_enhanced:
                    print(f"[{project_id}] Enhancer desativado. Copiando limpos para ENHANCER/...")
                    for i in range(1, video_parts + 1):
                        self.drive.copiar_arquivo(f"DRAMA/PIPELINE/WATERMARK/pt{i}_limpo.mp4", f"DRAMA/PIPELINE/ENHANCER/pt{i}_enhanced.mp4")
            else:
                running_enh = sum(1 for i in range(1, video_parts + 1) if project.get(f"step_enhancer_pt{i}") == "running")
                if running_enh < 7:
                    pending_enh = [i for i in range(1, video_parts + 1) if project.get(f"step_enhancer_pt{i}") == "pending"]
                    to_trigger = pending_enh[:7 - running_enh]
                    if to_trigger:
                        print(f"[{project_id}] Fila Enhancer: Disparando partes {to_trigger} (Running: {running_enh})")
                        self.disparar_enhancer(project_id, to_trigger)
                        return

        # Garante que pt0_enhanced.mp4 seja criado recortando as partes 1..N quando Watermark/Enhancer estiverem OK
        if w_ok and e_ok:
            arqs_enh = self.drive.listar_arquivos("DRAMA/PIPELINE/ENHANCER")
            if not any(a["name"] == "pt0_enhanced.mp4" for a in arqs_enh):
                print(f"[{project_id}] Partes 1..{video_parts} concluídas. Criando vídeo da introdução pt0_enhanced.mp4...")
                if self.criar_pt0_introducao(project_id, project):
                    self.drive.copiar_arquivo("DRAMA/PIPELINE/WATERMARK/pt0_limpo.mp4", "DRAMA/PIPELINE/ENHANCER/pt0_enhanced.mp4")

        # ── 3. WATERMARK+ENHANCER OK + OMNI OK + CONFIG OK -> FILA RENDER (MÁXIMO 7) ──
        if conf == "done" and w_ok and e_ok and omni == "done" and not r_ok:
            running_render = sum(1 for i in range(0, video_parts + 1) if project.get(f"step_render_pt{i}") == "running")
            if running_render < 7:
                pending_render = [i for i in range(0, video_parts + 1) if project.get(f"step_render_pt{i}") == "pending"]
                to_trigger = pending_render[:7 - running_render]
                if to_trigger:
                    print(f"[{project_id}] Fila Render: Disparando partes {to_trigger} (Running: {running_render})")
                    self.disparar_render(project_id, to_trigger)
                    return

        # ── 4. RENDER CONCLUÍDO -> DISPARAR MERGE ──
        if r_ok and project["step_merge"] == "pending":
            print(f"[{project_id}] Render concluído -> Disparando Merge")
            self.disparar_merge(project_id)
            return

        if project["step_merge"] == "done" and project["status"] != "completed":
            print(f"[{project_id}] Merge done -> Gerando guia de postagem (SEO)...")
            try:
                self.gerar_seo_automatico(project_id)
            except Exception as e:
                print(f"[{project_id}] Erro ao gerar guia SEO: {e}")
            mark_project_completed(project_id)
            print(f"[{project_id}] Projeto concluido!")
