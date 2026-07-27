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

NOTEBOOK_PREFIX = os.getenv("NOTEBOOK_PREFIX", "drama")

# Mapeamento: notebook -> conta Kaggle (1 a 11)
# Contas de processamento disponíveis para Watermark, Enhancer e Render (7 no total)
avail_accounts = [1, 2, 4, 5, 6, 7, 9]

ACCOUNT_MAP = {
    "omni": 3,
    "omni-main": 3,
    "omni-tts-pt1": 3,
    "omni-tts-pt2": 8,
    "omni-tts-pt3": 10,
    "omni-tts-pt4": 11,
    "omni-assemble": 3,
    
    "enhancer-pt0": 3,
    "render-pt0": 3,
    
    "merge": 6,
}

NOTEBOOK_MAP = {
    "omni": f"{NOTEBOOK_PREFIX}-omni-main",
    "omni-main": f"{NOTEBOOK_PREFIX}-omni-main",
    "omni-tts-pt1": f"{NOTEBOOK_PREFIX}-omni-tts-pt1",
    "omni-tts-pt2": f"{NOTEBOOK_PREFIX}-omni-tts-pt2",
    "omni-tts-pt3": f"{NOTEBOOK_PREFIX}-omni-tts-pt3",
    "omni-tts-pt4": f"{NOTEBOOK_PREFIX}-omni-tts-pt4",
    "omni-assemble": f"{NOTEBOOK_PREFIX}-omni-assemble",
    
    "enhancer-pt0": f"{NOTEBOOK_PREFIX}-video-enhancer-pt-0",
    "render-pt0": f"{NOTEBOOK_PREFIX}-renderizador-kaggle-pt-0",
    
    "merge": f"{NOTEBOOK_PREFIX}-merge-final",
}

# Preencher dinamicamente mapeamento de 1 a 30 partes
for i in range(1, 31):
    acc = avail_accounts[(i - 1) % len(avail_accounts)]
    
    ACCOUNT_MAP[f"wm-pt{i}"] = acc
    NOTEBOOK_MAP[f"wm-pt{i}"] = f"{NOTEBOOK_PREFIX}-watermark-remover-pt-{i}"
    
    ACCOUNT_MAP[f"enhancer-pt{i}"] = acc
    NOTEBOOK_MAP[f"enhancer-pt{i}"] = f"{NOTEBOOK_PREFIX}-video-enhancer-pt-{i}"
    
    ACCOUNT_MAP[f"render-pt{i}"] = acc
    NOTEBOOK_MAP[f"render-pt{i}"] = f"{NOTEBOOK_PREFIX}-renderizador-kaggle-pt-{i}"



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
