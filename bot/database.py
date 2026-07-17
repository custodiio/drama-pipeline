"""
Database Manager — Azure PostgreSQL
Gerencia o status do pipeline com tracking granular por célula.
"""

import os
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")


def _get_conn():
    """Cria conexão com o banco de dados."""
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def init_db():
    """Cria as tabelas se não existirem."""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""
        -- Tabela principal de projetos
        CREATE TABLE IF NOT EXISTS pipeline_projects (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            project_name TEXT NOT NULL,
            telegram_chat_id TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            
            status TEXT DEFAULT 'pending'
                CHECK (status IN ('pending','running','paused','waiting_config','completed','error')),
            current_step TEXT,
            
            -- Status por etapa (cada uma: pending/running/done/error)
            step_upload TEXT DEFAULT 'pending',
            step_split TEXT DEFAULT 'pending',
            step_omni TEXT DEFAULT 'pending',
            step_watermark_pt1 TEXT DEFAULT 'pending',
            step_watermark_pt2 TEXT DEFAULT 'pending',
            step_watermark_pt3 TEXT DEFAULT 'pending',
            step_watermark_pt4 TEXT DEFAULT 'pending',
            step_watermark_pt5 TEXT DEFAULT 'pending',
            step_enhancer_pt1 TEXT DEFAULT 'pending',
            step_enhancer_pt2 TEXT DEFAULT 'pending',
            step_enhancer_pt3 TEXT DEFAULT 'pending',
            step_enhancer_pt4 TEXT DEFAULT 'pending',
            step_enhancer_pt5 TEXT DEFAULT 'pending',
            step_session_created TEXT DEFAULT 'pending',
            step_config_ready TEXT DEFAULT 'pending',
            step_render_pt1 TEXT DEFAULT 'pending',
            step_render_pt2 TEXT DEFAULT 'pending',
            step_render_pt3 TEXT DEFAULT 'pending',
            step_render_pt4 TEXT DEFAULT 'pending',
            step_render_pt5 TEXT DEFAULT 'pending',
            step_merge TEXT DEFAULT 'pending',
            
            -- Metadados
            drive_folder_path TEXT,
            session_url TEXT,
            error_message TEXT,
            
            -- Opções de criação do projeto
            manual_mode BOOLEAN DEFAULT FALSE,
            thumbnail_enabled BOOLEAN DEFAULT TRUE,
            bg_audio BOOLEAN DEFAULT FALSE,
            srt_type TEXT DEFAULT 'normal',
            azure_enabled BOOLEAN DEFAULT TRUE,
            
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ
        );

        -- Tabela de log genérico
        CREATE TABLE IF NOT EXISTS pipeline_logs (
            id SERIAL PRIMARY KEY,
            project_id UUID REFERENCES pipeline_projects(id) ON DELETE CASCADE,
            step TEXT NOT NULL,
            status TEXT NOT NULL,
            message TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );

        -- Tabela de tracking granular por CÉLULA de notebook
        CREATE TABLE IF NOT EXISTS pipeline_cell_tracking (
            id SERIAL PRIMARY KEY,
            project_id UUID REFERENCES pipeline_projects(id) ON DELETE CASCADE,
            notebook TEXT NOT NULL,         -- ex: 'watermark-remover-pt-1'
            cell_index INTEGER NOT NULL,    -- número da célula (0, 1, 2...)
            cell_name TEXT,                 -- nome descritivo (ex: 'Setup', 'Processamento', 'Upload')
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','running','done','error')),
            started_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ,
            duration_seconds FLOAT,
            message TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );

        -- Index para busca rápida
        CREATE INDEX IF NOT EXISTS idx_cell_tracking_project 
            ON pipeline_cell_tracking(project_id, notebook);

        -- Tabela para salvar logos/overlays persistentemente
        CREATE TABLE IF NOT EXISTS pipeline_overlays (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name TEXT NOT NULL,
            image_data TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );

        -- Tabela para salvar presets de configuração (acessível em qualquer dispositivo)
        CREATE TABLE IF NOT EXISTS pipeline_presets (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name TEXT NOT NULL UNIQUE,
            preset_data JSONB NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );
    """)
    conn.commit()
    cur.close()
    conn.close()
    print("[OK] Banco de dados inicializado (com tracking por celula).")

    # Migração: adicionar colunas se não existirem (banco já existente)
    _migrate_db()


def _migrate_db():
    """Adiciona colunas novas ao banco se ainda não existirem."""
    conn = _get_conn()
    cur = conn.cursor()
    migrations = [
        "ALTER TABLE pipeline_projects ADD COLUMN IF NOT EXISTS manual_mode BOOLEAN DEFAULT FALSE",
        "ALTER TABLE pipeline_projects ADD COLUMN IF NOT EXISTS thumbnail_enabled BOOLEAN DEFAULT TRUE",
        "ALTER TABLE pipeline_projects ADD COLUMN IF NOT EXISTS bg_audio BOOLEAN DEFAULT FALSE",
        "ALTER TABLE pipeline_projects ADD COLUMN IF NOT EXISTS srt_type TEXT DEFAULT 'normal'",
        "ALTER TABLE pipeline_projects ADD COLUMN IF NOT EXISTS step_watermark_pt3 TEXT DEFAULT 'pending'",
        "ALTER TABLE pipeline_projects ADD COLUMN IF NOT EXISTS step_watermark_pt4 TEXT DEFAULT 'pending'",
        "ALTER TABLE pipeline_projects ADD COLUMN IF NOT EXISTS step_watermark_pt5 TEXT DEFAULT 'pending'",
        "ALTER TABLE pipeline_projects ADD COLUMN IF NOT EXISTS step_enhancer_pt3 TEXT DEFAULT 'pending'",
        "ALTER TABLE pipeline_projects ADD COLUMN IF NOT EXISTS step_enhancer_pt4 TEXT DEFAULT 'pending'",
        "ALTER TABLE pipeline_projects ADD COLUMN IF NOT EXISTS step_enhancer_pt5 TEXT DEFAULT 'pending'",
        "ALTER TABLE pipeline_projects ADD COLUMN IF NOT EXISTS step_render_pt3 TEXT DEFAULT 'pending'",
        "ALTER TABLE pipeline_projects ADD COLUMN IF NOT EXISTS step_render_pt4 TEXT DEFAULT 'pending'",
        "ALTER TABLE pipeline_projects ADD COLUMN IF NOT EXISTS step_render_pt5 TEXT DEFAULT 'pending'",
        "ALTER TABLE pipeline_projects ADD COLUMN IF NOT EXISTS azure_enabled BOOLEAN DEFAULT TRUE",
    ]
    for sql in migrations:
        try:
            cur.execute(sql)
        except Exception:
            pass
    conn.commit()
    cur.close()
    conn.close()


# ═══════════════════════════════════════════════════════════════════
# PROJETOS
# ═══════════════════════════════════════════════════════════════════

def create_project(project_name: str, chat_id: str) -> dict:
    """Cria um novo projeto no pipeline."""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO pipeline_projects (project_name, telegram_chat_id, status, current_step, started_at)
        VALUES (%s, %s, 'running', 'upload', NOW())
        RETURNING *
    """, (project_name, chat_id))
    project = dict(cur.fetchone())
    conn.commit()
    cur.close()
    conn.close()
    return project


def set_project_opts(project_id: str, manual_mode: bool, thumbnail_enabled: bool, bg_audio: bool = False, srt_type: str = 'normal', azure_enabled: bool = True):
    """Salva as opções de modo, thumbnail, processamento de áudio/legenda e Azure do projeto."""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""
        UPDATE pipeline_projects
        SET manual_mode = %s, thumbnail_enabled = %s, bg_audio = %s, srt_type = %s, azure_enabled = %s, updated_at = NOW()
        WHERE id = %s::uuid
    """, (manual_mode, thumbnail_enabled, bg_audio, srt_type, azure_enabled, project_id))
    conn.commit()
    cur.close()
    conn.close()


def update_step(project_id: str, step: str, status: str, message: str = ""):
    """
    Atualiza o status de uma etapa do pipeline.
    step: ex: 'step_watermark_pt1', 'step_omni'
    status: 'pending', 'running', 'done', 'error'
    """
    conn = _get_conn()
    cur = conn.cursor()

    cur.execute(f"""
        UPDATE pipeline_projects 
        SET {step} = %s, 
            current_step = %s,
            updated_at = NOW()
        WHERE id = %s::uuid
    """, (status, step.replace("step_", ""), project_id))

    if status == "error":
        cur.execute("""
            UPDATE pipeline_projects 
            SET status = 'error', error_message = %s
            WHERE id = %s::uuid
        """, (message, project_id))

    # Log
    cur.execute("""
        INSERT INTO pipeline_logs (project_id, step, status, message)
        VALUES (%s::uuid, %s, %s, %s)
    """, (project_id, step, status, message))

    conn.commit()
    cur.close()
    conn.close()


def get_running_projects() -> list:
    """Retorna todos os projetos com status ativo (running/waiting_config)."""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT * FROM pipeline_projects
        WHERE status IN ('running', 'waiting_config')
        ORDER BY created_at DESC
    """)
    results = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(r) for r in results]


def get_project(project_id: str) -> dict:
    """Busca um projeto pelo ID."""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM pipeline_projects WHERE id = %s::uuid", (project_id,))
    result = cur.fetchone()
    cur.close()
    conn.close()
    return dict(result) if result else None


def get_latest_project(chat_id: str) -> dict:
    """Retorna o projeto mais recente criado pelo usuário (independente do status)."""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT * FROM pipeline_projects 
        WHERE telegram_chat_id = %s 
        ORDER BY created_at DESC LIMIT 1
    """, (chat_id,))
    result = cur.fetchone()
    cur.close()
    conn.close()
    return dict(result) if result else None

def get_active_project(chat_id: str) -> dict:
    """Busca o projeto ativo (mais recente não-completed) para um chat."""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT * FROM pipeline_projects 
        WHERE telegram_chat_id = %s 
            AND status NOT IN ('completed', 'error')
        ORDER BY created_at DESC
        LIMIT 1
    """, (chat_id,))
    result = cur.fetchone()
    cur.close()
    conn.close()
    return dict(result) if result else None


def get_project_logs(project_id: str) -> list:
    """Busca os logs de um projeto."""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT * FROM pipeline_logs 
        WHERE project_id = %s::uuid 
        ORDER BY created_at ASC
    """, (project_id,))
    results = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(r) for r in results]


def mark_project_completed(project_id: str):
    """Marca o projeto como concluído."""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""
        UPDATE pipeline_projects 
        SET status = 'completed', completed_at = NOW(), updated_at = NOW()
        WHERE id = %s::uuid
    """, (project_id,))
    conn.commit()
    cur.close()
    conn.close()


def mark_project_waiting_config(project_id: str, session_url: str):
    """Marca o projeto como esperando config do usuário."""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""
        UPDATE pipeline_projects 
        SET status = 'waiting_config', 
            session_url = %s,
            step_session_created = 'done',
            updated_at = NOW()
        WHERE id = %s::uuid
    """, (session_url, project_id))
    conn.commit()
    cur.close()
    conn.close()


# ═══════════════════════════════════════════════════════════════════
# TRACKING GRANULAR POR CÉLULA
# ═══════════════════════════════════════════════════════════════════

def cell_start(project_id: str, notebook: str, cell_index: int, cell_name: str = ""):
    """
    Marca o INÍCIO de uma célula de notebook.
    Chamar no começo de cada célula do notebook.
    
    Exemplo no notebook:
        cell_start(PROJECT_ID, "watermark-remover-pt-1", 0, "Setup e Download")
    """
    conn = _get_conn()
    cur = conn.cursor()

    # Verifica se já existe registro para essa célula
    cur.execute("""
        SELECT id FROM pipeline_cell_tracking 
        WHERE project_id = %s::uuid AND notebook = %s AND cell_index = %s
    """, (project_id, notebook, cell_index))
    existing = cur.fetchone()

    if existing:
        cur.execute("""
            UPDATE pipeline_cell_tracking 
            SET status = 'running', started_at = NOW(), finished_at = NULL, 
                duration_seconds = NULL, cell_name = %s, message = ''
            WHERE id = %s
        """, (cell_name, existing["id"]))
    else:
        cur.execute("""
            INSERT INTO pipeline_cell_tracking 
                (project_id, notebook, cell_index, cell_name, status, started_at)
            VALUES (%s::uuid, %s, %s, %s, 'running', NOW())
        """, (project_id, notebook, cell_index, cell_name))

    conn.commit()
    cur.close()
    conn.close()


def cell_end(project_id: str, notebook: str, cell_index: int, 
             status: str = "done", message: str = ""):
    """
    Marca o FIM de uma célula de notebook.
    Chamar no final de cada célula do notebook.
    
    Exemplo no notebook:
        cell_end(PROJECT_ID, "watermark-remover-pt-1", 0, "done", "Setup concluído em 16s")
    """
    conn = _get_conn()
    cur = conn.cursor()

    cur.execute("""
        UPDATE pipeline_cell_tracking 
        SET status = %s, 
            finished_at = NOW(),
            duration_seconds = EXTRACT(EPOCH FROM (NOW() - started_at)),
            message = %s
        WHERE project_id = %s::uuid AND notebook = %s AND cell_index = %s
    """, (status, message, project_id, notebook, cell_index))

    conn.commit()
    cur.close()
    conn.close()


def get_cell_tracking(project_id: str, notebook: str = None) -> list:
    """
    Busca o tracking de células de um projeto.
    Se notebook for especificado, filtra por notebook.
    """
    conn = _get_conn()
    cur = conn.cursor()

    if notebook:
        cur.execute("""
            SELECT * FROM pipeline_cell_tracking 
            WHERE project_id = %s::uuid AND notebook = %s
            ORDER BY cell_index ASC
        """, (project_id, notebook))
    else:
        cur.execute("""
            SELECT * FROM pipeline_cell_tracking 
            WHERE project_id = %s::uuid 
            ORDER BY notebook, cell_index ASC
        """, (project_id,))

    results = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(r) for r in results]


# ═══════════════════════════════════════════════════════════════════
# FORMATAÇÃO
# ═══════════════════════════════════════════════════════════════════

def format_status(project: dict) -> str:
    """Formata o status do projeto para exibição no Telegram."""
    if not project:
        return "❌ Nenhum projeto ativo."

    ICONS = {
        "pending": "⏳",
        "running": "🔄",
        "done": "✅",
        "error": "❌"
    }

    steps = [
        ("step_upload", "Upload & Preparação"),
        ("step_split", "Divisão em 5 partes"),
        ("step_omni", "Omni-Anime-Ver"),
    ]
    for i in range(1, 6): steps.append((f"step_watermark_pt{i}", f"Watermark PT{i}"))
    for i in range(1, 6): steps.append((f"step_enhancer_pt{i}", f"Enhancer PT{i}"))
    steps.append(("step_session_created", "Sessão VideoRender"))
    steps.append(("step_config_ready", "Config Pronta"))
    for i in range(1, 6): steps.append((f"step_render_pt{i}", f"Render PT{i}"))
    steps.append(("step_merge", "Merge Final"))

    lines = [
        f"📽️ *{project['project_name']}*",
        f"📊 Status: *{project['status'].upper()}*",
        "",
    ]

    for key, label in steps:
        s = project.get(key, "pending")
        icon = ICONS.get(s, "❓")
        lines.append(f"  {icon} {label}")

    if project.get("error_message"):
        lines.append(f"\n⚠️ Erro: {project['error_message']}")

    if project.get("session_url"):
        lines.append(f"\n🔗 Sessão: {project['session_url']}")

    return "\n".join(lines)


def format_cell_status(project_id: str, notebook: str = None) -> str:
    """Formata o tracking de células para Telegram."""
    cells = get_cell_tracking(project_id, notebook)
    if not cells:
        return "📝 Nenhum tracking de célula encontrado."

    ICONS = {
        "pending": "⏳",
        "running": "🔄",
        "done": "✅",
        "error": "❌"
    }

    current_nb = ""
    lines = []

    for cell in cells:
        nb = cell["notebook"]
        if nb != current_nb:
            current_nb = nb
            lines.append(f"\n📓 *{nb}*")

        icon = ICONS.get(cell["status"], "❓")
        name = cell.get("cell_name") or f"Célula {cell['cell_index']}"
        dur = ""
        if cell.get("duration_seconds"):
            secs = int(cell["duration_seconds"])
            if secs >= 60:
                dur = f" ({secs // 60}m{secs % 60}s)"
            else:
                dur = f" ({secs}s)"
        msg = f" — {cell['message']}" if cell.get("message") else ""
        lines.append(f"  {icon} [{cell['cell_index']}] {name}{dur}{msg}")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
# OVERLAYS (Galeria Persistente no DB)
# ═══════════════════════════════════════════════════════════════════

def get_all_overlays() -> list:
    """Retorna todas as overlays salvas no DB."""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, name, image_data, created_at FROM pipeline_overlays ORDER BY created_at DESC")
    overlays = [dict(row) for row in cur.fetchall()]
    for o in overlays:
        o["id"] = str(o["id"])
        o["created_at"] = o["created_at"].isoformat()
    cur.close()
    conn.close()
    return overlays

def save_overlay(name: str, image_data: str) -> dict:
    """Salva uma nova overlay no DB e retorna o registro criado."""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO pipeline_overlays (name, image_data)
        VALUES (%s, %s)
        RETURNING id, name, image_data, created_at
    """, (name, image_data))
    row = dict(cur.fetchone())
    row["id"] = str(row["id"])
    row["created_at"] = row["created_at"].isoformat()
    conn.commit()
    cur.close()
    conn.close()
    return row

def delete_overlay(overlay_id: str) -> bool:
    """Exclui uma overlay do DB pelo ID."""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM pipeline_overlays WHERE id = %s::uuid RETURNING id", (overlay_id,))
    deleted = cur.fetchone() is not None
    conn.commit()
    cur.close()
    conn.close()
    return deleted


# ═══════════════════════════════════════════════════════════════════
# PRESETS (Configurações Globais — acessíveis em qualquer dispositivo)
# ═══════════════════════════════════════════════════════════════════

def get_all_presets() -> list:
    """Retorna todos os presets salvos no DB."""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, name, preset_data, created_at, updated_at
        FROM pipeline_presets
        ORDER BY name ASC
    """)
    presets = [dict(row) for row in cur.fetchall()]
    for p in presets:
        p["id"] = str(p["id"])
        p["created_at"] = p["created_at"].isoformat()
        p["updated_at"] = p["updated_at"].isoformat()
        # preset_data já vem como dict via psycopg2 JSONB
        if not isinstance(p["preset_data"], dict):
            import json
            p["preset_data"] = json.loads(p["preset_data"])
    cur.close()
    conn.close()
    return presets


def save_preset(name: str, preset_data: dict) -> dict:
    """Cria ou atualiza um preset pelo nome (upsert). Retorna o registro."""
    import json
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO pipeline_presets (name, preset_data)
        VALUES (%s, %s::jsonb)
        ON CONFLICT (name) DO UPDATE
            SET preset_data = EXCLUDED.preset_data,
                updated_at = NOW()
        RETURNING id, name, preset_data, created_at, updated_at
    """, (name, json.dumps(preset_data)))
    row = dict(cur.fetchone())
    row["id"] = str(row["id"])
    row["created_at"] = row["created_at"].isoformat()
    row["updated_at"] = row["updated_at"].isoformat()
    if not isinstance(row["preset_data"], dict):
        row["preset_data"] = json.loads(row["preset_data"])
    conn.commit()
    cur.close()
    conn.close()
    return row


def delete_preset(preset_id: str) -> bool:
    """Exclui um preset do DB pelo ID."""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM pipeline_presets WHERE id = %s::uuid RETURNING id", (preset_id,))
    deleted = cur.fetchone() is not None
    conn.commit()
    cur.close()
    conn.close()
    return deleted
