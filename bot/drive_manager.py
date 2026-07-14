"""
Google Drive Manager - Modulo padronizado
Todas as operacoes de Drive usam esse modulo.
"""

import os
import io
import shutil
import subprocess
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

# Caminhos padronizados no Drive
DRIVE_BASE = "DRAMA/PIPELINE"
DRIVE_ATIVO = f"{DRIVE_BASE}/ATIVO"
DRIVE_WATERMARK = f"{DRIVE_BASE}/WATERMARK"
DRIVE_ENHANCER = f"{DRIVE_BASE}/ENHANCER"
DRIVE_OMNI = f"{DRIVE_BASE}/OMNI"
DRIVE_RENDER = f"{DRIVE_BASE}/RENDER"
DRIVE_FINAL = f"{DRIVE_BASE}/FINAL"
DRIVE_ARQUIVO = "DRAMA/ARQUIVO"


class DriveManager:
    """Gerenciador centralizado do Google Drive."""

    def __init__(self, refresh_token=None, client_id=None, client_secret=None):
        self.refresh_token = refresh_token or os.getenv("DRIVE_REFRESH_TOKEN", "")
        self.client_id = client_id or os.getenv("DRIVE_CLIENT_ID", "")
        self.client_secret = client_secret or os.getenv("DRIVE_CLIENT_SECRET", "")
        self.service = None
        self._authenticate()

    def _authenticate(self):
        """Autentica com o Google Drive via OAuth."""
        try:
            creds = Credentials(
                token=None,
                refresh_token=self.refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=self.client_id,
                client_secret=self.client_secret,
                scopes=["https://www.googleapis.com/auth/drive"]
            )
            creds.refresh(Request())
            self.service = build("drive", "v3", credentials=creds)
            print("Google Drive autenticado!")
        except Exception as e:
            self.service = None
            print(f"Falha na autenticacao do Drive: {e}")

    @staticmethod
    def _esc(name):
        """Escapa aspas simples para queries do Drive API."""
        return name.replace("'", "\\'")

    def _buscar_id(self, caminho_no_drive):
        """Resolve caminho do Drive para file ID."""
        partes = caminho_no_drive.strip("/").split("/")
        parent_id = "root"
        for parte in partes:
            query = f"name='{self._esc(parte)}' and '{parent_id}' in parents and trashed=false"
            # Adicionado orderBy para garantir que arquivos mais novos fiquem no topo se houver duplicidade
            results = self.service.files().list(q=query, fields="files(id, mimeType)", orderBy="modifiedTime desc").execute()
            arquivos = results.get("files", [])
            if not arquivos:
                return None
            parent_id = arquivos[0]["id"]
        return parent_id

    def _garantir_pasta(self, caminho_pasta):
        """Garante que a hierarquia de pastas existe, criando se necessario."""
        partes = caminho_pasta.strip("/").split("/")
        parent_id = "root"
        for pasta in partes:
            query = f"name='{self._esc(pasta)}' and '{parent_id}' in parents and trashed=false and mimeType='application/vnd.google-apps.folder'"
            results = self.service.files().list(q=query, fields="files(id)").execute()
            existentes = results.get("files", [])
            if existentes:
                parent_id = existentes[0]["id"]
            else:
                nova = self.service.files().create(
                    body={"name": pasta, "mimeType": "application/vnd.google-apps.folder", "parents": [parent_id]},
                    fields="id"
                ).execute()
                parent_id = nova["id"]
        return parent_id

    def baixar(self, caminho_drive, destino_local):
        """Baixa arquivo do Drive para local."""
        if os.path.exists(destino_local):
            return True
        if not self.service:
            return False
        try:
            file_id = self._buscar_id(caminho_drive)
            if not file_id:
                print(f"  Arquivo nao encontrado: {caminho_drive}")
                return False
            request = self.service.files().get_media(fileId=file_id)
            os.makedirs(os.path.dirname(destino_local) or ".", exist_ok=True)
            with open(destino_local, "wb") as fh:
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done:
                    _, done = downloader.next_chunk()
            print(f"  Baixado: {caminho_drive}")
            return True
        except Exception as e:
            print(f"  Erro ao baixar {caminho_drive}: {e}")
            return False

    def salvar(self, caminho_local, caminho_drive):
        """Salva arquivo local no Drive (cria ou atualiza)."""
        if not self.service or not os.path.exists(caminho_local):
            return False
        try:
            partes = caminho_drive.strip("/").split("/")
            nome_arquivo = partes[-1]
            pasta_drive = "/".join(partes[:-1]) if len(partes) > 1 else ""
            parent_id = self._garantir_pasta(pasta_drive) if pasta_drive else "root"

            query = f"name='{self._esc(nome_arquivo)}' and '{parent_id}' in parents and trashed=false"
            results = self.service.files().list(q=query, fields="files(id)", orderBy="modifiedTime desc").execute()
            existentes = results.get("files", [])
            media = MediaFileUpload(caminho_local, resumable=True)

            if existentes:
                self.service.files().update(fileId=existentes[0]["id"], media_body=media).execute()
                # Limpar quaisquer arquivos duplicados adicionais mais antigos com o mesmo nome
                for ext in existentes[1:]:
                    try:
                        self.service.files().delete(fileId=ext["id"]).execute()
                        print(f"  Deletado duplicado histórico do arquivo no salvar: {caminho_drive} (ID: {ext['id']})")
                    except Exception as ed:
                        print(f"  Erro ao deletar duplicado antigo no salvar: {ed}")
            else:
                self.service.files().create(
                    body={"name": nome_arquivo, "parents": [parent_id]},
                    media_body=media, fields="id"
                ).execute()
            print(f"  Salvo: {caminho_drive}")
            return True
        except Exception as e:
            print(f"  Erro ao salvar {caminho_drive}: {e}")
            return False

    def listar_arquivos(self, caminho_pasta):
        """Lista arquivos em uma pasta do Drive."""
        if not self.service:
            return []
        folder_id = self._buscar_id(caminho_pasta)
        if not folder_id:
            return []
        results = self.service.files().list(
            q=f"'{folder_id}' in parents and trashed=false",
            fields="files(id, name, mimeType, size)"
        ).execute()
        return results.get("files", [])

    def copiar_arquivo(self, caminho_origem, caminho_destino):
        """Copia um arquivo no Drive de um caminho para outro, prevenindo duplicados."""
        try:
            arq_id = self._buscar_id(caminho_origem)
            if not arq_id:
                print(f"Origem não encontrada: {caminho_origem}")
                return False
                
            dir_dest, nome_dest = caminho_destino.rsplit("/", 1)
            dir_dest_id = self._garantir_pasta(dir_dest)
            
            # Prevenir duplicidades deletando o arquivo de mesmo nome existente no destino
            existente_id = self._buscar_id(caminho_destino)
            if existente_id:
                try:
                    self.service.files().delete(fileId=existente_id).execute()
                    print(f"  Deletado arquivo duplicado existente no destino: {caminho_destino}")
                except Exception as ed:
                    print(f"  Erro ao deletar duplicado no destino: {ed}")
            
            body = {
                'name': nome_dest,
                'parents': [dir_dest_id]
            }
            self.service.files().copy(fileId=arq_id, body=body).execute()
            print(f"  Copiado: {caminho_origem} -> {caminho_destino}")
            return True
        except Exception as e:
            print(f"Erro ao copiar {caminho_origem} para {caminho_destino}: {e}")
            return False

    def mover_arquivo(self, file_id, nova_pasta_id):
        """Move um arquivo para outra pasta."""
        if not self.service:
            return
        file_info = self.service.files().get(fileId=file_id, fields="parents").execute()
        previous_parents = ",".join(file_info.get("parents", []))
        self.service.files().update(
            fileId=file_id,
            addParents=nova_pasta_id,
            removeParents=previous_parents,
            fields="id, parents"
        ).execute()

    def get_file_link(self, caminho_drive):
        """Retorna o webViewLink de um arquivo no Drive."""
        if not self.service:
            return None
        file_id = self._buscar_id(caminho_drive)
        if not file_id:
            return None
        try:
            file_info = self.service.files().get(fileId=file_id, fields="webViewLink").execute()
            return file_info.get("webViewLink")
        except Exception as e:
            print(f"Erro ao obter link do arquivo {caminho_drive}: {e}")
            return None

    def limpar_pasta_ativo(self):
        """Deleta todo o conteúdo de ATIVO e das demais pastas do pipeline."""
        if not self.service:
            return

        print("🧹 Iniciando limpeza profunda do projeto anterior...")
        
        pastas_para_limpar = [
            DRIVE_ATIVO, DRIVE_WATERMARK, DRIVE_ENHANCER, 
            DRIVE_OMNI, DRIVE_RENDER, DRIVE_FINAL
        ]
        
        total_deletado = 0
        for pasta in pastas_para_limpar:
            arquivos = self.listar_arquivos(pasta)
            for arq in arquivos:
                try:
                    self.service.files().delete(fileId=arq["id"]).execute()
                    print(f"  🗑️ Deletado de {pasta}: {arq['name']}")
                    total_deletado += 1
                except Exception as e:
                    print(f"  ❌ Erro ao deletar {arq['name']} em {pasta}: {e}")
                    
        print(f"✅ Limpeza concluída. {total_deletado} arquivos antigos removidos do Drive.")

    def limpar_audio_dub_cache(self):
        """Apaga os JSONs de cache e outputs do AUDIO_DUB para forçar reprocessamento no Omni.
        PRESERVA: pasta CLONAGEM, arquivos de referência de voz (.wav), pasta INPUT.
        """
        if not self.service:
            return
        # 1. Limpar arquivos soltos na raiz do AUDIO_DUB (transcrições, roteiros, guias)
        try:
            arqs_raiz = self.listar_arquivos("DRAMA/AUDIO_DUB")
            for arq in arqs_raiz:
                nome = arq["name"].lower()
                # Proteger pastas (INPUT, OUTPUT, CLONAGEM, etc)
                if arq.get("mimeType") == "application/vnd.google-apps.folder":
                    continue
                # Foca apenas em arquivos soltos que o omni gera (.json, .txt)
                if nome.endswith(".json") or nome.endswith(".txt"):
                    try:
                        self.service.files().delete(fileId=arq["id"]).execute()
                        print(f"  Resquício removido da raiz: {arq['name']}")
                    except Exception as e:
                        print(f"  Erro ao remover {arq['name']}: {e}")
        except Exception as e:
            print(f"  Erro ao listar raiz AUDIO_DUB: {e}")

        # 2. Limpar pasta OUTPUT (mp3/srt de projetos anteriores)
        try:
            arqs = self.listar_arquivos("DRAMA/AUDIO_DUB/OUTPUT")
            for arq in arqs:
                try:
                    self.service.files().delete(fileId=arq["id"]).execute()
                    print(f"  Output antigo removido: DRAMA/AUDIO_DUB/OUTPUT/{arq['name']}")
                except Exception:
                    pass
        except Exception:
            pass

        # 3. Limpar pasta INPUT (áudio antigo do projeto anterior)
        #    PRESERVA: subpasta CLONAGEM (contém áudio de referência de voz)
        try:
            arqs = self.listar_arquivos("KAGGLE/AUDIO_DUB/INPUT")
            for arq in arqs:
                # Proteger a pasta CLONAGEM
                if arq.get("mimeType") == "application/vnd.google-apps.folder":
                    print(f"  Pasta preservada: INPUT/{arq['name']}")
                    continue
                try:
                    self.service.files().delete(fileId=arq["id"]).execute()
                    print(f"  Input antigo removido: KAGGLE/AUDIO_DUB/INPUT/{arq['name']}")
                except Exception:
                    pass
        except Exception:
                pass


def _find_bin(name):
    """Encontra o caminho completo de um binario (ffmpeg/ffprobe).
    Resolve o problema de PATH restrito em servicos systemd."""
    path = shutil.which(name)
    if path:
        return path
    # Fallback para caminhos comuns no Linux
    for p in ["/usr/bin/" + name, "/usr/local/bin/" + name, "/snap/bin/" + name]:
        if os.path.isfile(p):
            return p
    return name  # Ultima tentativa: retorna o nome puro


FFPROBE = _find_bin("ffprobe")
FFMPEG = _find_bin("ffmpeg")


def split_video(input_path, output_dir, parts=5):
    """
    Divide um video em N partes iguais usando FFmpeg.
    Retorna uma lista com os caminhos dos arquivos gerados.
    """
    os.makedirs(output_dir, exist_ok=True)

    result = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", input_path],
        capture_output=True, text=True
    )
    duration = float(result.stdout.strip())
    part_duration = duration / parts

    paths = []
    
    for i in range(parts):
        pt_path = os.path.join(output_dir, f"video_pt{i+1}.mp4")
        start_time = i * part_duration
        
        cmd = [
            FFMPEG, "-y", "-ss", str(start_time), "-i", input_path
        ]
        
        if i < parts - 1:
            cmd.extend(["-t", str(part_duration)])
            
        cmd.extend([
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18", "-c:a", "copy",
            pt_path
        ])
        
        subprocess.run(cmd, check=True, capture_output=True)
        paths.append(pt_path)

    import json
    info_path = os.path.join(output_dir, "split_info.json")
    with open(info_path, "w") as f:
        json.dump({"duration": duration, "parts": parts, "part_duration": part_duration}, f)
    paths.append(info_path)

    print(f"  Video dividido: {duration:.1f}s -> {parts} partes de ~{part_duration:.1f}s")
    return paths


def merge_videos(parts_paths, audio_path, output_path):
    """Junta N partes de video + audio de dublagem."""
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    concat_file = output_path + ".concat.txt"
    with open(concat_file, "w") as f:
        for pt_path in parts_paths:
            f.write(f"file '{pt_path}'\n")

    subprocess.run([
        FFMPEG, "-y",
        "-f", "concat", "-safe", "0", "-i", concat_file,
        "-i", audio_path,
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        output_path
    ], check=True, capture_output=True)

    os.remove(concat_file)
    print(f"  Merge concluido: {output_path}")
