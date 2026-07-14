/**
 * Hook para gerenciar sessão do pipeline.
 * Valida o token da URL, carrega vídeo e legendas placeholder automaticamente,
 * e permite salvar config no Drive.
 */
import { useState, useEffect, useRef } from 'react';
import { useProjectStore } from '../store/projectStore';
import { extractFrames } from '../utils/frameExtractor';
import { parseSrt } from '../utils/srtParser';

export interface SessionInfo {
  valid: boolean;
  project_id?: string;
  token?: string;
  apiUrl?: string;
}

export function useSession() {
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saveResult, setSaveResult] = useState<string | null>(null);
  const videoLoaded = useRef(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const token = params.get('session');
    // Se o bot mandar um URL do ngrok no param 'api', usamos ele. Senão cai no .env ou localhost
    const apiUrlParam = params.get('api');
    const apiBase = apiUrlParam || import.meta.env.VITE_API_URL || window.location.origin;

    if (!token) {
      setSession(null);
      setLoading(false);
      return;
    }

    // Validar sessão
    fetch(`${apiBase}/api/session/validate?token=${token}`)
      .then(r => r.json())
      .then(data => {
        if (data.valid) {
          const s = { valid: true, project_id: data.project_id, token, apiUrl: apiBase };
          setSession(s);
          // Carregar vídeo e legendas placeholder automaticamente
          if (!videoLoaded.current) {
            videoLoaded.current = true;
            loadSessionVideo(s);
          }
        } else {
          setSession({ valid: false });
        }
      })
      .catch(() => setSession({ valid: false }))
      .finally(() => setLoading(false));
  }, []);

  /**
   * Carrega o vídeo da sessão (da pasta uploads/ via API) e gera legendas placeholder.
   */
  async function loadSessionVideo(s: SessionInfo) {
    if (!s.token || !s.apiUrl) return;
    try {
      const videoUrl = `${s.apiUrl}/api/session/video?token=${s.token}`;

      // Verificar se o vídeo existe
      const headRes = await fetch(videoUrl, { method: 'HEAD' }).catch(() => null);
      if (!headRes || !headRes.ok) {
        console.warn('[Session] Vídeo não encontrado na API, sessão sem vídeo.');
        return;
      }

      // Baixar o vídeo como blob
      const res = await fetch(videoUrl);
      if (!res.ok) return;
      const blob = await res.blob();
      const file = new File([blob], 'session_video.mp4', { type: 'video/mp4' });

      // Extrair frames e info
      const { frames, info } = await extractFrames(file, 8);
      const url = URL.createObjectURL(file);

      const store = useProjectStore.getState();
      store.setVideoFile(file, url, info);
      store.setExtractedFrames(frames);
      if (frames.length > 0) store.setSelectedFrame(frames[0].id);

      // Gerar legendas placeholder (para o usuário pré-visualizar o estilo)
      if (store.srtEntries.length === 0) {
        const placeholderSrt = generatePlaceholderSrt(info.duration);
        const entries = parseSrt(placeholderSrt);
        const srtFile = new File([placeholderSrt], 'placeholder.srt', { type: 'text/plain' });
        store.setSrtFile(srtFile, entries);
      }

      console.log('[Session] Vídeo e legendas placeholder carregados automaticamente.');
    } catch (e) {
      console.warn('[Session] Falha ao carregar vídeo da sessão:', e);
    }
  }

  const saveToePipeline = async (config: object, assContent?: string, maskDataUrl?: string) => {
    if (!session?.valid || !session.token || !session.apiUrl) return;

    setSaving(true);
    setSaveResult(null);

    try {
      const res = await fetch(`${session.apiUrl}/api/session/save-config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          token: session.token,
          config,
          ass: assContent || null,
          mask: maskDataUrl || null,
        }),
      });

      const data = await res.json();
      if (data.ok) {
        setSaveResult('success');
      } else {
        setSaveResult(data.error || 'Erro ao salvar');
      }
    } catch (e) {
      setSaveResult('Erro de conexão');
    } finally {
      setSaving(false);
    }
  };

  return {
    session,
    loading,
    saving,
    saveResult,
    saveToePipeline,
    isSessionMode: !!session?.valid,
  };
}

/**
 * Gera um SRT placeholder com blocos de texto de exemplo
 * para que o usuário possa pré-visualizar o estilo da legenda.
 */
function generatePlaceholderSrt(duration: number): string {
  const blocks = [
    'Texto de exemplo para ajustar a legenda',
    'Configure a fonte, cor e posição',
    'O estilo será aplicado no vídeo final',
    'Ajuste o tamanho e contorno',
    'Esta é uma legenda placeholder',
    'O conteúdo real virá do Omni',
  ];

  const blockDuration = Math.min(4, duration / blocks.length);
  let srt = '';

  for (let i = 0; i < blocks.length; i++) {
    const startSec = i * blockDuration;
    const endSec = startSec + blockDuration - 0.2;
    if (startSec >= duration) break;

    const startTime = formatSrtTime(startSec);
    const endTime = formatSrtTime(Math.min(endSec, duration));

    srt += `${i + 1}\n${startTime} --> ${endTime}\n${blocks[i]}\n\n`;
  }

  return srt;
}

function formatSrtTime(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  const ms = Math.floor((seconds % 1) * 1000);
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')},${String(ms).padStart(3, '0')}`;
}
