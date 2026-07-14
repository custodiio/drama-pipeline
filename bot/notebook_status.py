"""
Notebook Status Reporter — Com tracking por célula
Módulo leve que os notebooks Kaggle importam para reportar status.
"""

import os
import requests as http_requests
import time


# URL do webhook — configurada via Kaggle Secret ou env
WEBHOOK_URL = os.getenv("PIPELINE_WEBHOOK_URL", "")
PROJECT_ID = os.getenv("PIPELINE_PROJECT_ID", "")
NOTEBOOK_NAME = os.getenv("PIPELINE_NOTEBOOK", "")

# Fallback: conexão direta com banco (para quando webhook não está disponível)
DATABASE_URL = os.getenv("DATABASE_URL", "")


def _load_from_secrets():
    """Tenta carregar variáveis via Kaggle Secrets."""
    global WEBHOOK_URL, PROJECT_ID, NOTEBOOK_NAME, DATABASE_URL
    try:
        from kaggle_secrets import UserSecretsClient
        s = UserSecretsClient()
        def _try_get(name):
            try:
                return s.get_secret(name)
            except:
                return ""
        WEBHOOK_URL = _try_get("PIPELINE_WEBHOOK_URL") or WEBHOOK_URL
        PROJECT_ID = _try_get("PIPELINE_PROJECT_ID") or PROJECT_ID
        NOTEBOOK_NAME = _try_get("PIPELINE_NOTEBOOK") or NOTEBOOK_NAME
        DATABASE_URL = _try_get("DATABASE_URL") or DATABASE_URL
    except ImportError:
        pass


_load_from_secrets()

# Timer para calcular duração
_cell_timers = {}


def _send_webhook(endpoint: str, data: dict):
    """Envia dados para o webhook."""
    if not WEBHOOK_URL:
        return False
    try:
        resp = http_requests.post(
            f"{WEBHOOK_URL}{endpoint}",
            json=data,
            timeout=15,
        )
        return resp.status_code == 200
    except:
        return False


def _send_direct_db(action: str, **kwargs):
    """Fallback: escreve direto no banco quando não tem webhook."""
    if not DATABASE_URL:
        return False
    try:
        import psycopg2
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()

        if action == "cell_start":
            cur.execute("""
                INSERT INTO pipeline_cell_tracking 
                    (project_id, notebook, cell_index, cell_name, status, started_at)
                VALUES (%s::uuid, %s, %s, %s, 'running', NOW())
                ON CONFLICT DO NOTHING
            """, (kwargs["project_id"], kwargs["notebook"], 
                  kwargs["cell_index"], kwargs.get("cell_name", "")))
            # Tentar update caso já exista
            cur.execute("""
                UPDATE pipeline_cell_tracking 
                SET status = 'running', started_at = NOW(), finished_at = NULL,
                    duration_seconds = NULL, cell_name = %s
                WHERE project_id = %s::uuid AND notebook = %s AND cell_index = %s
            """, (kwargs.get("cell_name", ""), kwargs["project_id"], 
                  kwargs["notebook"], kwargs["cell_index"]))

        elif action == "cell_end":
            cur.execute("""
                UPDATE pipeline_cell_tracking 
                SET status = %s, finished_at = NOW(),
                    duration_seconds = EXTRACT(EPOCH FROM (NOW() - started_at)),
                    message = %s
                WHERE project_id = %s::uuid AND notebook = %s AND cell_index = %s
            """, (kwargs.get("status", "done"), kwargs.get("message", ""),
                  kwargs["project_id"], kwargs["notebook"], kwargs["cell_index"]))

        elif action == "step_update":
            step = kwargs["step"]
            cur.execute(f"""
                UPDATE pipeline_projects 
                SET {step} = %s, current_step = %s, updated_at = NOW()
                WHERE id = %s::uuid
            """, (kwargs["status"], step.replace("step_", ""), kwargs["project_id"]))
            cur.execute("""
                INSERT INTO pipeline_logs (project_id, step, status, message)
                VALUES (%s::uuid, %s, %s, %s)
            """, (kwargs["project_id"], step, kwargs["status"], kwargs.get("message", "")))

        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"  ⚠️ DB direto falhou: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════
# FUNÇÕES PARA OS NOTEBOOKS
# ═══════════════════════════════════════════════════════════════════

def cell_start(cell_index: int, cell_name: str = "",
               project_id: str = None, notebook: str = None):
    """
    Marca o INÍCIO de uma célula. Coloque no TOPO de cada célula.
    
    Exemplo:
        cell_start(0, "Setup e Download")
        # ... código da célula ...
        cell_end(0, "done", "Setup concluído")
    """
    pid = project_id or PROJECT_ID
    nb = notebook or NOTEBOOK_NAME
    
    if not pid:
        print(f"  📊 [CELL {cell_index}] ▶️ Iniciando: {cell_name or 'sem nome'}")
        return

    _cell_timers[cell_index] = time.time()

    data = {
        "project_id": pid,
        "notebook": nb,
        "cell_index": cell_index,
        "cell_name": cell_name,
    }

    ok = _send_webhook("/webhook/cell-start", data)
    if not ok:
        _send_direct_db("cell_start", **data)

    print(f"  📊 [CELL {cell_index}] ▶️ {cell_name or 'Iniciando...'}")


def cell_end(cell_index: int, status: str = "done", message: str = "",
             project_id: str = None, notebook: str = None):
    """
    Marca o FIM de uma célula. Coloque no FINAL de cada célula.
    
    Exemplo:
        cell_start(1, "Processamento de frames")
        # ... código pesado ...
        cell_end(1, "done", f"{total_frames} frames processados")
    """
    pid = project_id or PROJECT_ID
    nb = notebook or NOTEBOOK_NAME

    # Calcular duração local
    elapsed = ""
    if cell_index in _cell_timers:
        secs = int(time.time() - _cell_timers.pop(cell_index))
        if secs >= 60:
            elapsed = f" ({secs // 60}m{secs % 60}s)"
        else:
            elapsed = f" ({secs}s)"

    if not pid:
        icon = "✅" if status == "done" else "❌"
        print(f"  📊 [CELL {cell_index}] {icon} {status}{elapsed}: {message}")
        return

    data = {
        "project_id": pid,
        "notebook": nb,
        "cell_index": cell_index,
        "status": status,
        "message": message,
    }

    ok = _send_webhook("/webhook/cell-end", data)
    if not ok:
        _send_direct_db("cell_end", **data)

    icon = "✅" if status == "done" else "❌"
    print(f"  📊 [CELL {cell_index}] {icon} {status}{elapsed}: {message}")


def report_status(step: str, status: str, message: str = "",
                  project_id: str = None):
    """
    Reporta status de uma etapa macro (step_watermark_pt1, etc).
    Chamar uma vez no final do notebook inteiro.
    """
    pid = project_id or PROJECT_ID

    if not pid:
        print(f"  📊 [STEP] {step} → {status}: {message}")
        return

    data = {
        "project_id": pid,
        "step": step,
        "status": status,
        "message": message,
    }

    ok = _send_webhook("/webhook/status", data)
    if not ok:
        _send_direct_db("step_update", **data)

    print(f"  📊 [STEP] {step} → {status}")
