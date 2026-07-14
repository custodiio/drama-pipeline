"""
GitHub Actions Dispatcher
Dispara notebooks no Kaggle via GitHub Actions (repository_dispatch).
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "custodiio/drama-pipeline")

# Mapeamento: notebook -> conta Kaggle
ACCOUNT_MAP = {
    "wm-pt1": 1,
    "wm-pt2": 2,
    "wm-pt3": 4,
    "wm-pt4": 5,
    "wm-pt5": 6,
    "enhancer-pt1": 1,
    "enhancer-pt2": 2,
    "enhancer-pt3": 4,
    "enhancer-pt4": 5,
    "enhancer-pt5": 6,
    "omni": 3,
    "render-pt1": 1,
    "render-pt2": 2,
    "render-pt3": 4,
    "render-pt4": 5,
    "render-pt5": 6,
    "merge": 6,
}

# Notebooks Kaggle por nome
NOTEBOOK_MAP = {
    "wm-pt1": "watermark-remover-pt-1",
    "wm-pt2": "watermark-remover-pt-2",
    "wm-pt3": "watermark-remover-pt-3",
    "wm-pt4": "watermark-remover-pt-4",
    "wm-pt5": "watermark-remover-pt-5",
    "enhancer-pt1": "video-enhancer-pt-1",
    "enhancer-pt2": "video-enhancer-pt-2",
    "enhancer-pt3": "video-enhancer-pt-3",
    "enhancer-pt4": "video-enhancer-pt-4",
    "enhancer-pt5": "video-enhancer-pt-5",
    "omni": "omni-drama-ver-final",
    "render-pt1": "renderizador-kaggle-pt-1",
    "render-pt2": "renderizador-kaggle-pt-2",
    "render-pt3": "renderizador-kaggle-pt-3",
    "render-pt4": "renderizador-kaggle-pt-4",
    "render-pt5": "renderizador-kaggle-pt-5",
    "merge": "merge-final",
}


def dispatch_workflow(task, project_id, extra_payload=None):
    """
    Dispara um workflow do GitHub Actions via repository_dispatch.
    
    task: chave do ACCOUNT_MAP (ex: 'wm-pt1', 'omni')
    project_id: ID do projeto no banco de dados
    extra_payload: dados adicionais para o notebook
    """
    if task not in ACCOUNT_MAP:
        raise ValueError(f"Task desconhecida: {task}. Validas: {list(ACCOUNT_MAP.keys())}")

    account_num = ACCOUNT_MAP[task]
    notebook_name = NOTEBOOK_MAP[task]

    payload = {
        "event_type": f"run-{task}",
        "client_payload": {
            "project_id": project_id,
            "task": task,
            "notebook": notebook_name,
            "kaggle_account": account_num,
            **(extra_payload or {}),
        }
    }

    url = f"https://api.github.com/repos/{GITHUB_REPO}/dispatches"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    for attempt in range(3):
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)

            if response.status_code == 204:
                print(f"  Workflow disparado: {task} (Conta {account_num})")
                return True
            else:
                print(f"  Erro ao disparar {task}: {response.status_code} - {response.text}")
                return False
        except requests.exceptions.Timeout:
            print(f"  Timeout ao disparar {task} (tentativa {attempt+1}/3)")
            if attempt < 2:
                import time
                time.sleep(5)
        except requests.exceptions.ConnectionError as e:
            print(f"  Erro de conexão ao disparar {task} (tentativa {attempt+1}/3): {e}")
            if attempt < 2:
                import time
                time.sleep(5)

    print(f"  Falha definitiva ao disparar {task} após 3 tentativas")
    return False


def dispatch_parallel(tasks, project_id, extra_payload=None):
    """
    Dispara multiplos workflows simultaneamente.
    tasks: lista de chaves do ACCOUNT_MAP
    """
    results = {}
    for task in tasks:
        results[task] = dispatch_workflow(task, project_id, extra_payload)
    return results
