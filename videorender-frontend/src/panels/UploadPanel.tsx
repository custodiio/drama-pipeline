import { useCallback, useRef, useState } from 'react';
import { useProjectStore } from '../store/projectStore';
import { extractFrames, formatDuration } from '../utils/frameExtractor';
import { parseSrt } from '../utils/srtParser';

export function UploadPanel() {
  const {
    videoInfo, extractedFrames, selectedFrameId,
    setVideoFile, setExtractedFrames, setSelectedFrame,
    setSrtFile, srtEntries, setActivePanel,
  } = useProjectStore();

  const [extracting, setExtracting] = useState(false);
  const [progress, setProgress] = useState(0);
  const [draggingVideo, setDraggingVideo] = useState(false);
  const [frameCount, setFrameCount] = useState(8);
  const videoInputRef = useRef<HTMLInputElement>(null);
  const srtInputRef = useRef<HTMLInputElement>(null);

  const handleVideoFile = useCallback(async (file: File) => {
    setExtracting(true);
    setProgress(0);
    try {
      const { frames, info } = await extractFrames(file, frameCount, setProgress);
      const url = URL.createObjectURL(file);
      setVideoFile(file, url, info);
      setExtractedFrames(frames);
      if (frames.length > 0) setSelectedFrame(frames[0].id);
    } catch (e) {
      console.error(e);
      alert('Erro ao processar vídeo. Tente outro arquivo.');
    } finally {
      setExtracting(false);
    }
  }, [frameCount, setVideoFile, setExtractedFrames, setSelectedFrame]);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDraggingVideo(false);
    const file = e.dataTransfer.files[0];
    if (file && file.type.startsWith('video/')) {
      handleVideoFile(file);
    }
  }, [handleVideoFile]);

  const handleSrtFile = useCallback(async (file: File) => {
    const text = await file.text();
    const entries = parseSrt(text);
    setSrtFile(file, entries);
  }, [setSrtFile]);

  return (
    <div className="panel-content">
      <h2 style={{ fontFamily: 'Montserrat', fontWeight: 900, fontSize: 20, marginBottom: 6 }}>
        📤 Upload & Referência Visual
      </h2>
      <p style={{ color: 'var(--text-muted)', marginBottom: 20, fontSize: 13 }}>
        Faça upload do vídeo para extrair frames de referência. O vídeo não é enviado para nenhum servidor.
      </p>

      {/* Video Upload */}
      <div
        className={`upload-zone ${draggingVideo ? 'dragging' : ''}`}
        onDrop={handleDrop}
        onDragOver={(e) => { e.preventDefault(); setDraggingVideo(true); }}
        onDragLeave={() => setDraggingVideo(false)}
        onClick={() => videoInputRef.current?.click()}
      >
        <input
          ref={videoInputRef}
          type="file"
          accept="video/*"
          style={{ display: 'none' }}
          onChange={(e) => e.target.files?.[0] && handleVideoFile(e.target.files[0])}
        />
        {videoInfo ? (
          <div>
            <span className="upload-icon">🎬</span>
            <div className="upload-title">{videoInfo.fileName}</div>
            <div style={{ display: 'flex', justifyContent: 'center', gap: 16, marginTop: 10 }}>
              <span className="info-chip">
                <strong>{videoInfo.width}×{videoInfo.height}</strong>
              </span>
              <span className="info-chip">
                <strong>{formatDuration(videoInfo.duration)}</strong>
              </span>
              <span className="info-chip">
                <strong>{videoInfo.aspect}</strong>
              </span>
            </div>
            <p style={{ color: 'var(--text-muted)', fontSize: 12, marginTop: 10 }}>
              Clique para trocar o vídeo
            </p>
          </div>
        ) : (
          <>
            <span className="upload-icon">🎞️</span>
            <div className="upload-title">Solte seu vídeo aqui</div>
            <div className="upload-sub">MP4, MOV, MKV, AVI · Máx. sem limite (processado localmente)</div>
          </>
        )}
      </div>

      {/* Frame count config */}
      <div className="form-group" style={{ marginTop: 16 }}>
        <div className="form-label">
          <span>Frames a extrair</span>
          <span className="form-label-value">{frameCount} frames</span>
        </div>
        <input
          type="range"
          min={4} max={20} step={1}
          value={frameCount}
          onChange={(e) => setFrameCount(Number(e.target.value))}
        />
      </div>

      {/* Extraction progress */}
      {extracting && (
        <div style={{ marginBottom: 16 }}>
          <div className="form-label" style={{ marginBottom: 8 }}>
            <span style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <div className="spinner" />
              Extraindo frames...
            </span>
            <span className="form-label-value">{Math.round(progress)}%</span>
          </div>
          <div className="progress-bar">
            <div className="progress-fill" style={{ width: `${progress}%` }} />
          </div>
        </div>
      )}

      {/* SRT Upload */}
      <div style={{ marginTop: 20 }}>
        <div
          className="upload-zone"
          style={{ padding: '24px 24px' }}
          onClick={() => srtInputRef.current?.click()}
        >
          <input
            ref={srtInputRef}
            type="file"
            accept=".srt,.ass,.vtt"
            style={{ display: 'none' }}
            onChange={(e) => e.target.files?.[0] && handleSrtFile(e.target.files[0])}
          />
          {srtEntries.length > 0 ? (
            <>
              <span className="upload-icon" style={{ fontSize: 32 }}>📝</span>
              <div className="upload-title">{srtEntries.length} entradas de legenda carregadas</div>
              <p style={{ color: 'var(--text-muted)', fontSize: 12, marginTop: 6 }}>Clique para trocar</p>
            </>
          ) : (
            <>
              <span className="upload-icon" style={{ fontSize: 32 }}>📄</span>
              <div className="upload-title">Upload do SRT</div>
              <div className="upload-sub">Arquivo .srt com legendas palavra por palavra</div>
            </>
          )}
        </div>
      </div>

      {/* Extracted Frames */}
      {extractedFrames.length > 0 && (
        <div style={{ marginTop: 24 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
            <h3 style={{ fontSize: 14, fontWeight: 700 }}>🎞️ Frames Extraídos</h3>
            <button className="btn btn-sm btn-secondary" onClick={() => setActivePanel('subtitles')}>
              Ir para Legendas →
            </button>
          </div>
          <div className="frames-grid" style={{ padding: 0 }}>
            {extractedFrames.map((frame) => (
              <div
                key={frame.id}
                className={`frame-card ${selectedFrameId === frame.id ? 'selected' : ''}`}
                onClick={() => setSelectedFrame(frame.id)}
              >
                <img src={frame.dataUrl} alt={`Frame ${frame.id}`} loading="lazy" />
                <div className="frame-time">{formatDuration(frame.timeSeconds)}</div>
                <div className="frame-check">✓</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

