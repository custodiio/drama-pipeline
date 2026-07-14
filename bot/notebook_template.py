"""
Template de código padrão para notebooks Kaggle do pipeline.
Cada notebook usa cell_start() no topo e cell_end() no final de cada célula.
"""

# ═══════════════════════════════════════════════════════════════════
# CÉLULA 0 — SETUP PADRÃO (Cole no início de TODOS os notebooks)
# ═══════════════════════════════════════════════════════════════════
CELL_0_SETUP = '''
import os, sys, json, subprocess, time, io
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
import requests as http_requests

# ─── Configuração do Notebook ───
NOTEBOOK_NAME = "{notebook_name}"  # ex: "watermark-remover-pt-1"
STEP_NAME = "{step_name}"          # ex: "step_watermark_pt1"

# ─── Carregar Secrets ───
def _load_secrets():
    try:
        from kaggle_secrets import UserSecretsClient
        _s = UserSecretsClient()
        def _get(name):
            try: return _s.get_secret(name)
            except: return ""
        print("🔑 Carregando chaves do Kaggle Secrets...")
        return _get
    except ImportError:
        from dotenv import load_dotenv
        load_dotenv()
        print("🔑 Carregando do .env local...")
        return lambda name: os.getenv(name, "")

_get = _load_secrets()

DRIVE_REFRESH_TOKEN  = _get("DRIVE_REFRESH_TOKEN")
DRIVE_CLIENT_ID      = _get("DRIVE_CLIENT_ID")
DRIVE_CLIENT_SECRET  = _get("DRIVE_CLIENT_SECRET")
HF_TOKEN             = _get("HF_TOKEN")
GEMINI_API_KEY       = _get("GEMINI_API_KEY")
OPENAI_API_KEY       = _get("OPENAI_API_KEY")
PIPELINE_WEBHOOK_URL = _get("PIPELINE_WEBHOOK_URL")
DATABASE_URL         = _get("DATABASE_URL")
PROJECT_ID           = _get("PIPELINE_PROJECT_ID")

print("✅ Chaves carregadas." if DRIVE_REFRESH_TOKEN else "⚠️ DRIVE_REFRESH_TOKEN não encontrada!")

# ─── Google Drive ───
print("☁️ Autenticando Google Drive...")
try:
    _creds = Credentials(
        token=None,
        refresh_token=DRIVE_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=DRIVE_CLIENT_ID,
        client_secret=DRIVE_CLIENT_SECRET,
        scopes=["https://www.googleapis.com/auth/drive"]
    )
    _creds.refresh(Request())
    drive_service = build("drive", "v3", credentials=_creds)
    print("☁️ Google Drive autenticado!")
except Exception as e:
    drive_service = None
    print(f"❌ Falha na autenticação Drive: {{e}}")

# ─── Funções de Drive ───
def _buscar_id(caminho):
    partes = caminho.strip("/").split("/")
    pid = "root"
    for p in partes:
        q = f"name='{{p}}' and '{{pid}}' in parents and trashed=false"
        r = drive_service.files().list(q=q, fields="files(id,mimeType)", orderBy="modifiedTime desc").execute()
        a = r.get("files", [])
        if not a: return None
        pid = a[0]["id"]
    return pid

def _garantir_pasta(caminho):
    partes = caminho.strip("/").split("/")
    pid = "root"
    for p in partes:
        q = f"name='{{p}}' and '{{pid}}' in parents and trashed=false and mimeType='application/vnd.google-apps.folder'"
        r = drive_service.files().list(q=q, fields="files(id)").execute()
        e = r.get("files", [])
        if e:
            pid = e[0]["id"]
        else:
            nova = drive_service.files().create(
                body={{"name": p, "mimeType": "application/vnd.google-apps.folder", "parents": [pid]}},
                fields="id"
            ).execute()
            pid = nova["id"]
    return pid

def baixar_do_drive(caminho_drive, destino_local):
    if os.path.exists(destino_local): return True
    try:
        fid = _buscar_id(caminho_drive)
        if not fid: return False
        req = drive_service.files().get_media(fileId=fid)
        os.makedirs(os.path.dirname(destino_local) or ".", exist_ok=True)
        with open(destino_local, "wb") as fh:
            dl = MediaIoBaseDownload(fh, req)
            done = False
            while not done: _, done = dl.next_chunk()
        print(f"  ⬇️ {{caminho_drive}}")
        return True
    except Exception as ex:
        print(f"  ❌ {{caminho_drive}}: {{ex}}")
        return False

def salvar_no_drive(caminho_local, caminho_drive):
    if not drive_service or not os.path.exists(caminho_local): return
    try:
        partes = caminho_drive.strip("/").split("/")
        nome = partes[-1]
        pasta = "/".join(partes[:-1]) if len(partes) > 1 else ""
        pid = _garantir_pasta(pasta) if pasta else "root"
        q = f"name='{{nome}}' and '{{pid}}' in parents and trashed=false"
        r = drive_service.files().list(q=q, fields="files(id)").execute()
        e = r.get("files", [])
        media = MediaFileUpload(caminho_local, resumable=True)
        if e:
            drive_service.files().update(fileId=e[0]["id"], media_body=media).execute()
        else:
            drive_service.files().create(
                body={{"name": nome, "parents": [pid]}}, media_body=media, fields="id"
            ).execute()
        print(f"  ⬆️ {{caminho_drive}}")
    except Exception as ex:
        print(f"  ❌ Erro ao salvar {{caminho_drive}}: {{ex}}")

# ─── Tracking por Célula ───
_cell_timers = {{}}

def _db_execute(query, params):
    """Executa query direto no banco (fallback quando não tem webhook)."""
    if not DATABASE_URL: return False
    try:
        import psycopg2
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute(query, params)
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"  ⚠️ DB: {{e}}")
        return False

def _try_webhook(endpoint, data):
    """Tenta enviar pro webhook, fallback pro banco direto."""
    if PIPELINE_WEBHOOK_URL:
        try:
            r = http_requests.post(f"{{PIPELINE_WEBHOOK_URL}}{{endpoint}}", json=data, timeout=15)
            if r.status_code == 200: return True
        except: pass
    return False

def cell_start(cell_index, cell_name=""):
    """Marca INÍCIO da célula. Cole no TOPO de cada célula."""
    _cell_timers[cell_index] = time.time()
    print(f"\\n{'='*60}")
    print(f"  ▶️ CÉLULA [{{cell_index}}] — {{cell_name or 'Sem nome'}}")
    print(f"{'='*60}")
    
    if not PROJECT_ID: return
    
    data = {{"project_id": PROJECT_ID, "notebook": NOTEBOOK_NAME, 
             "cell_index": cell_index, "cell_name": cell_name}}
    if not _try_webhook("/webhook/cell-start", data):
        _db_execute(\"\"\"
            INSERT INTO pipeline_cell_tracking 
                (project_id, notebook, cell_index, cell_name, status, started_at)
            VALUES (%s::uuid, %s, %s, %s, 'running', NOW())
            ON CONFLICT DO NOTHING
        \"\"\", (PROJECT_ID, NOTEBOOK_NAME, cell_index, cell_name))
        _db_execute(\"\"\"
            UPDATE pipeline_cell_tracking 
            SET status='running', started_at=NOW(), finished_at=NULL, cell_name=%s
            WHERE project_id=%s::uuid AND notebook=%s AND cell_index=%s
        \"\"\", (cell_name, PROJECT_ID, NOTEBOOK_NAME, cell_index))

def cell_end(cell_index, status="done", message=""):
    """Marca FIM da célula. Cole no FINAL de cada célula."""
    elapsed = ""
    if cell_index in _cell_timers:
        secs = int(time.time() - _cell_timers.pop(cell_index))
        mins = secs // 60
        elapsed = f" ({{mins}}m{{secs%60}}s)" if mins else f" ({{secs}}s)"
    
    icon = "✅" if status == "done" else "❌"
    print(f"  {{icon}} CÉLULA [{{cell_index}}] → {{status}}{{elapsed}}: {{message}}")
    print(f"{'─'*60}\\n")
    
    if not PROJECT_ID: return
    
    data = {{"project_id": PROJECT_ID, "notebook": NOTEBOOK_NAME,
             "cell_index": cell_index, "status": status, "message": message}}
    if not _try_webhook("/webhook/cell-end", data):
        _db_execute(\"\"\"
            UPDATE pipeline_cell_tracking 
            SET status=%s, finished_at=NOW(), 
                duration_seconds=EXTRACT(EPOCH FROM (NOW()-started_at)), message=%s
            WHERE project_id=%s::uuid AND notebook=%s AND cell_index=%s
        \"\"\", (status, message, PROJECT_ID, NOTEBOOK_NAME, cell_index))

def report_step(status, message=""):
    """Reporta status da etapa MACRO. Chamar UMA VEZ no final do notebook."""
    print(f"\\n{'🎉' if status=='done' else '❌'} NOTEBOOK FINALIZADO: {{STEP_NAME}} → {{status}}")
    if not PROJECT_ID: return
    
    data = {{"project_id": PROJECT_ID, "step": STEP_NAME, "status": status, "message": message}}
    if not _try_webhook("/webhook/status", data):
        _db_execute(f\"\"\"
            UPDATE pipeline_projects 
            SET {{STEP_NAME}}=%s, current_step=%s, updated_at=NOW()
            WHERE id=%s::uuid
        \"\"\", (status, STEP_NAME.replace("step_", ""), PROJECT_ID))

# ─── Caminhos padronizados ───
DRIVE_ATIVO = "KAGGLE/PIPELINE/ATIVO"
DRIVE_WATERMARK = "KAGGLE/PIPELINE/WATERMARK"
DRIVE_ENHANCER = "KAGGLE/PIPELINE/ENHANCER"
DRIVE_OMNI = "KAGGLE/PIPELINE/OMNI"
DRIVE_RENDER = "KAGGLE/PIPELINE/RENDER"
DRIVE_FINAL = "KAGGLE/PIPELINE/FINAL"

BASE_PATH = "/kaggle/working"
os.makedirs(BASE_PATH, exist_ok=True)

cell_end(0, "done", "Setup padrão concluído")
'''

# ═══════════════════════════════════════════════════════════════════
# EXEMPLO DE USO EM NOTEBOOK
# ═══════════════════════════════════════════════════════════════════
EXAMPLE_NOTEBOOK = '''
# ───────────────────────────────────────────────────────
# CÉLULA 0: SETUP (Cole CELL_0_SETUP acima)
# ───────────────────────────────────────────────────────
cell_start(0, "Setup e Autenticação")
# ... (código do CELL_0_SETUP) ...
# cell_end(0) já está no final do CELL_0_SETUP

# ───────────────────────────────────────────────────────
# CÉLULA 1: DOWNLOAD DOS ARQUIVOS
# ───────────────────────────────────────────────────────
cell_start(1, "Download dos Arquivos")

baixar_do_drive(f"{DRIVE_ATIVO}/video_pt1.mp4", "/kaggle/working/video_pt1.mp4")
baixar_do_drive(f"{DRIVE_ATIVO}/mask.png", "/kaggle/working/mask.png")

cell_end(1, "done", "Arquivos baixados com sucesso")

# ───────────────────────────────────────────────────────
# CÉLULA 2: PROCESSAMENTO
# ───────────────────────────────────────────────────────
cell_start(2, "Processamento de Frames")

total_frames = 6354  # exemplo
# ... processamento pesado ...

cell_end(2, "done", f"{total_frames} frames processados")

# ───────────────────────────────────────────────────────
# CÉLULA 3: UPLOAD DO RESULTADO
# ───────────────────────────────────────────────────────
cell_start(3, "Upload do Resultado")

salvar_no_drive("/kaggle/working/output.mp4", f"{DRIVE_WATERMARK}/pt1_limpo.mp4")

cell_end(3, "done", "Upload concluído")

# ───────────────────────────────────────────────────────
# CÉLULA 4: FINALIZAR
# ───────────────────────────────────────────────────────
cell_start(4, "Finalização")
report_step("done", "✅ Watermark PT1 concluído com sucesso!")
cell_end(4, "done", "Notebook finalizado")
'''

# Mapeamento notebook → step de status
NOTEBOOK_STEP_MAP = {
    "watermark-remover-pt-1": "step_watermark_pt1",
    "watermark-remover-pt-2": "step_watermark_pt2",
    "video-enhancer-pt-1": "step_enhancer_pt1",
    "video-enhancer-pt-2": "step_enhancer_pt2",
    "omni-anime-ver-final": "step_omni",
    "renderizador-kaggle-pt-1": "step_render_pt1",
    "renderizador-kaggle-pt-2": "step_render_pt2",
    "merge-final": "step_merge",
}
