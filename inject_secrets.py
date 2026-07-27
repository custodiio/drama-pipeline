"""
Injeta secrets do GitHub Actions diretamente no código-fonte do notebook .ipynb.
Roda no GitHub Actions ANTES do kaggle push.
Preserva a estrutura de linhas do notebook para evitar SyntaxError.
"""
import json, os, sys

notebook_name = os.environ.get("NOTEBOOK", "")
if not notebook_name:
    print("ERRO: variável NOTEBOOK não definida")
    sys.exit(1)

file_path = f"{notebook_name}.ipynb"
if not os.path.exists(file_path):
    # Tenta dentro de notebooks/
    file_path = os.path.join("notebooks", f"{notebook_name}.ipynb")

print(f"📄 Abrindo: {file_path}")

with open(file_path, "r", encoding="utf-8") as f:
    nb = json.load(f)

# Mapa de secrets a injetar
secrets = {
    "DATABASE_URL": os.environ.get("DATABASE_URL", ""),
    "DRIVE_REFRESH_TOKEN": os.environ.get("DRIVE_REFRESH_TOKEN", ""),
    "DRIVE_CLIENT_ID": os.environ.get("DRIVE_CLIENT_ID", ""),
    "DRIVE_CLIENT_SECRET": os.environ.get("DRIVE_CLIENT_SECRET", ""),
    "HF_TOKEN": os.environ.get("HF_TOKEN", ""),
    "GEMINI_API_KEY": os.environ.get("GEMINI_API_KEY", ""),
    "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY", ""),
    "PIPELINE_PROJECT_ID": os.environ.get("PROJECT_ID", ""),
    "PIPELINE_WEBHOOK_URL": os.environ.get("PIPELINE_WEBHOOK_URL", ""),
    "PIPELINE_TASK_KEY": os.environ.get("TASK_KEY", ""),
    "AZURE_OPENAI_ENDPOINT": os.environ.get("AZURE_OPENAI_ENDPOINT", ""),
    "AZURE_OPENAI_API_KEY": os.environ.get("AZURE_OPENAI_API_KEY", ""),
    "AZURE_OPENAI_DEPLOYMENT": os.environ.get("AZURE_OPENAI_DEPLOYMENT", ""),
}

replaced_count = 0

for cell in nb["cells"]:
    if cell["cell_type"] != "code":
        continue

    # Processar LINHA A LINHA para preservar as quebras de linha
    new_source = []
    for line in cell["source"]:
        for key, value in secrets.items():
            safe_val = json.dumps(value)  # Escapa aspas e caracteres especiais
            old_line = line
            # Todos os padrões usados nos notebooks
            for fn in ["_get", "_ks", "_get_secret"]:
                line = line.replace(f'{fn}("{key}")', safe_val)
                line = line.replace(f"{fn}('{key}')", safe_val)
            if line != old_line:
                replaced_count += 1
        new_source.append(line)
    cell["source"] = new_source

with open(file_path, "w", encoding="utf-8") as f:
    json.dump(nb, f, ensure_ascii=False, indent=1)

print(f"✅ {replaced_count} substituições feitas no notebook!")
