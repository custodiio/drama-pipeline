import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "posts.db")

def get_connection():
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS scheduled_posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        video_path TEXT,
        thumbnail_youtube TEXT,
        thumbnail_tiktok TEXT,
        title_youtube TEXT,
        title_shorts TEXT,
        tiktok_caption TEXT,
        instagram_caption TEXT,
        post_youtube INTEGER DEFAULT 0,
        post_shorts INTEGER DEFAULT 0,
        post_tiktok INTEGER DEFAULT 0,
        post_instagram INTEGER DEFAULT 0,
        tiktok_privacy TEXT,
        scheduled_time TEXT, -- Formato YYYY-MM-DD HH:MM:SS
        status TEXT DEFAULT 'pending', -- 'pending', 'processing', 'completed', 'failed'
        error_message TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        shorts_description TEXT,
        chat_id INTEGER,
        email TEXT
    )
    """)
    
    # Migrações caso o banco já exista sem as colunas novas
    try:
        cursor.execute("ALTER TABLE scheduled_posts ADD COLUMN chat_id INTEGER")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE scheduled_posts ADD COLUMN email TEXT")
    except sqlite3.OperationalError:
        pass
        
    conn.commit()
    conn.close()

def add_scheduled_post(video_path, title_shorts, shorts_description, tiktok_caption, 
                       post_shorts=1, post_tiktok=1, scheduled_time=None, chat_id=None, email=None):
    """Adiciona um post agendado na fila."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO scheduled_posts (
        video_path, title_shorts, shorts_description, tiktok_caption,
        post_shorts, post_tiktok, scheduled_time, chat_id, email, status
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
    """, (video_path, title_shorts, shorts_description, tiktok_caption,
          post_shorts, post_tiktok, scheduled_time, chat_id, email))
    post_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return post_id

def get_pending_scheduled_posts():
    """Busca posts agendados pendentes que ja venceram o horario."""
    conn = get_connection()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
    SELECT id, video_path, title_shorts, shorts_description, tiktok_caption,
           post_shorts, post_tiktok, scheduled_time, chat_id, email
    FROM scheduled_posts
    WHERE status = 'pending' AND scheduled_time <= ?
    """, (now_str,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def update_scheduled_post_status(post_id, status, error_message=None):
    """Atualiza o status de um post agendado."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    UPDATE scheduled_posts
    SET status = ?, error_message = ?
    WHERE id = ?
    """, (status, error_message, post_id))
    conn.commit()
    conn.close()

def get_all_pending_scheduled():
    """Busca todos os agendamentos pendentes na fila."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT id, scheduled_time, title_shorts, tiktok_caption, post_shorts, post_tiktok, status
    FROM scheduled_posts
    WHERE status = 'pending'
    ORDER BY scheduled_time ASC
    """)
    rows = cursor.fetchall()
    conn.close()
    return rows
