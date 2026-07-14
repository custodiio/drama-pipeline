"""
Main - Ponto de entrada do Agente de Postagem
Roda o Bot Telegram + Webhook Server simultaneamente.
"""

import sys
import os

# Fix encoding para Windows
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from dotenv import load_dotenv
load_dotenv()

from bot.database import init_db
from bot.telegram_bot import main as run_bot


if __name__ == "__main__":
    print("=" * 60)
    print("  Agente de Postagem - AnimeRecap Pipeline")
    print("=" * 60)

    # Inicializar banco de dados
    init_db()

    # Iniciar bot Telegram (webhook eh iniciado dentro de run_bot)
    print("Iniciando Bot Telegram...")
    run_bot()
