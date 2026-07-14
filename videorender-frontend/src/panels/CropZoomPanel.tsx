import { useState, useEffect, useRef } from 'react';
import { useProjectStore } from '../store/projectStore';

function getSliderValue(scale: number) {
  if (scale >= 1.0) {
    return ((scale - 1.0) / 4.0) * 50;
  } else {
    return ((scale - 1.0) / 0.9) * 50;
  }
}

function getScaleValue(slider: number) {
  if (slider >= 0) {
    return 1.0 + (slider / 50) * 4.0;
  } else {
    return 1.0 + (slider / 50) * 0.9;
  }
}

function Toggle({ checked, onChange, onRelease }: { checked: boolean; onChange: (v: boolean) => void; onRelease?: () => void }) {
  return (
    <label className="toggle">
      <input 
        type="checkbox" 
        checked={checked} 
        onChange={(e) => {
          onChange(e.target.checked);
          if (onRelease) setTimeout(onRelease, 50);
        }} 
      />
      <span className="toggle-slider" />
    </label>
  );
}

// Math helper for Static Crop
function getNormalizedCrop(
  aspectRatio: string,
  sizePct: number,
  posX: number,
  posY: number,
  videoAspect: number,
  marginL = 0,
  marginR = 0,
  marginT = 0,
  marginB = 0
) {
  if (aspectRatio === 'custom') {
    const x = marginL;
    const y = marginT;
    const width = Math.max(10, 100 - marginL - marginR);
    const height = Math.max(10, 100 - marginT - marginB);
    return { x, y, width, height };
  }

  let R = videoAspect; // default original
  if (aspectRatio === '9:16') R = 9 / 16;
  else if (aspectRatio === '16:9') R = 16 / 9;
  else if (aspectRatio === '3:4') R = 3 / 4;
  else if (aspectRatio === '1:1') R = 1 / 1;

  let maxW = 100;
  let maxH = 100;
  if (R > videoAspect) {
    maxW = 100;
    maxH = 100 * (videoAspect / R);
  } else {
    maxH = 100;
    maxW = 100 * (R / videoAspect);
  }

  const width = maxW * (sizePct / 100);
  const height = maxH * (sizePct / 100);

  // posX and posY center the box within the available margin
  const x = (posX / 100) * (100 - width);
  const y = (posY / 100) * (100 - height);

  return { x, y, width, height };
}

export function CropZoomPanel() {
  const { 
    cropZoom, setCropZoom,
    staticCrop, setStaticCrop,
    videoPosition, setVideoPosition,
    videoEdit, setVideoEdit,
    videoInfo
  } = useProjectStore();

  const [activeTab, setActiveTab] = useState<'crop' | 'zoom' | 'edit'>('crop');

  // Aspect ratio check
  const videoAspect = videoInfo ? videoInfo.width / videoInfo.height : 16 / 9;

  // History stack for Undo/Redo
  const historyRef = useRef<any[]>([]);
  const historyIndexRef = useRef<number>(-1);

  const pushHistory = () => {
    const sCrop = useProjectStore.getState().staticCrop;
    const vPos = useProjectStore.getState().videoPosition;
    const vEdit = useProjectStore.getState().videoEdit;

    const current = historyRef.current[historyIndexRef.current];
    if (current && 
        JSON.stringify(current.staticCrop) === JSON.stringify(sCrop) &&
        JSON.stringify(current.videoPosition) === JSON.stringify(vPos) &&
        JSON.stringify(current.videoEdit) === JSON.stringify(vEdit)) {
      return;
    }

    const newHistory = historyRef.current.slice(0, historyIndexRef.current + 1);
    newHistory.push({
      staticCrop: JSON.parse(JSON.stringify(sCrop)),
      videoPosition: JSON.parse(JSON.stringify(vPos)),
      videoEdit: JSON.parse(JSON.stringify(vEdit)),
    });

    if (newHistory.length > 50) newHistory.shift();

    historyRef.current = newHistory;
    historyIndexRef.current = newHistory.length - 1;
  };

  useEffect(() => {
    if (historyRef.current.length === 0 && (staticCrop || videoPosition || videoEdit)) {
      pushHistory();
    }
  }, []);

  const handleUndo = () => {
    if (historyIndexRef.current > 0) {
      historyIndexRef.current--;
      const prevState = historyRef.current[historyIndexRef.current];
      setStaticCrop(prevState.staticCrop);
      setVideoPosition(prevState.videoPosition);
      setVideoEdit(prevState.videoEdit);
    }
  };

  const handleRedo = () => {
    if (historyIndexRef.current < historyRef.current.length - 1) {
      historyIndexRef.current++;
      const nextState = historyRef.current[historyIndexRef.current];
      setStaticCrop(nextState.staticCrop);
      setVideoPosition(nextState.videoPosition);
      setVideoEdit(nextState.videoEdit);
    }
  };

  // Helper to update static crop values and calculate normalized x/y/w/h
  const updateCrop = (changes: Partial<typeof staticCrop>) => {
    const nextConfig = { ...staticCrop, ...changes };
    const normalized = getNormalizedCrop(
      nextConfig.aspectRatio,
      nextConfig.sizePct,
      nextConfig.posX,
      nextConfig.posY,
      videoAspect,
      nextConfig.marginL,
      nextConfig.marginR,
      nextConfig.marginT,
      nextConfig.marginB
    );
    setStaticCrop({ ...nextConfig, ...normalized });
  };

  const handleResetCrop = () => {
    setStaticCrop({
      enabled: false,
      aspectRatio: 'original',
      x: 0,
      y: 0,
      width: 100,
      height: 100,
      sizePct: 100,
      posX: 50,
      posY: 50,
      marginL: 0,
      marginR: 0,
      marginT: 0,
      marginB: 0,
    });
    setVideoPosition({
      enabled: false,
      x: 0,
      y: 0,
      scale: 1.0,
    });
    setTimeout(pushHistory, 50);
  };

  const handleResetEdit = () => {
    setVideoEdit({
      speed: 1.0,
      hFlip: false,
      vFlip: false,
      rotate: 0,
      volume: 100,
      audioFadeIn: 0,
      audioFadeOut: 0,
    });
    setTimeout(pushHistory, 50);
  };

  const hasUndo = historyIndexRef.current > 0;
  const hasRedo = historyIndexRef.current < historyRef.current.length - 1;

  return (
    <div className="panel-content">
      {/* Title */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <h2 style={{ fontFamily: 'Montserrat', fontWeight: 900, fontSize: 20 }}>
          ✂️ Recorte & Zoom
        </h2>
        {/* Undo / Redo visual buttons */}
        <div style={{ display: 'flex', gap: 6 }}>
          <button 
            className="btn btn-ghost btn-sm btn-icon" 
            onClick={handleUndo} 
            disabled={!hasUndo}
            title="Desfazer ação"
            style={{ opacity: hasUndo ? 1 : 0.35, cursor: hasUndo ? 'pointer' : 'default' }}
          >
            ↩️
          </button>
          <button 
            className="btn btn-ghost btn-sm btn-icon" 
            onClick={handleRedo} 
            disabled={!hasRedo}
            title="Refazer ação"
            style={{ opacity: hasRedo ? 1 : 0.35, cursor: hasRedo ? 'pointer' : 'default' }}
          >
            ↪️
          </button>
        </div>
      </div>

      <p style={{ color: 'var(--text-muted)', marginBottom: 16, fontSize: 13 }}>
        Ajuste o enquadramento, recorte a imagem, reposicione o vídeo final ou aplique efeitos geométricos e ajustes de áudio.
      </p>

      {/* Tabs */}
      <div className="segmented" style={{ marginBottom: 20 }}>
        <button 
          className={activeTab === 'crop' ? 'active' : ''} 
          onClick={() => setActiveTab('crop')}
        >
          Recorte & Posição
        </button>
        <button 
          className={activeTab === 'zoom' ? 'active' : ''} 
          onClick={() => setActiveTab('zoom')}
        >
          Zoom Progressivo
        </button>
        <button 
          className={activeTab === 'edit' ? 'active' : ''} 
          onClick={() => setActiveTab('edit')}
        >
          Edição Avançada
        </button>
      </div>

      {/* TAB 1: CROP & POSITION */}
      {activeTab === 'crop' && (
        <div>
          {/* Enable Static Crop */}
          <div className="toggle-row" style={{ marginBottom: 16 }}>
            <span className="toggle-label" style={{ fontWeight: 600, color: 'var(--text-primary)' }}>Ativar Recorte Estático</span>
            <Toggle 
              checked={staticCrop.enabled} 
              onChange={(v) => updateCrop({ enabled: v })}
              onRelease={pushHistory}
            />
          </div>

          <div style={{ opacity: staticCrop.enabled ? 1 : 0.4, pointerEvents: staticCrop.enabled ? 'auto' : 'none', transition: 'opacity 0.2s' }}>
            {/* Proporção Aspect Ratio */}
            <div className="form-group">
              <label className="form-label">Proporção do Recorte</label>
              <select 
                value={staticCrop.aspectRatio} 
                onChange={(e) => {
                  updateCrop({ aspectRatio: e.target.value as any });
                  setTimeout(pushHistory, 50);
                }}
              >
                <option value="original">Original ({videoAspect.toFixed(2)})</option>
                <option value="9:16">9:16 (Vertical)</option>
                <option value="16:9">16:9 (Horizontal)</option>
                <option value="3:4">3:4 (Tradicional)</option>
                <option value="1:1">1:1 (Quadrado)</option>
                <option value="custom">Livre (Corte pelas Margens)</option>
              </select>
            </div>

            {/* If not custom, show crop size and center position */}
            {staticCrop.aspectRatio !== 'custom' ? (
              <>
                {/* Crop Size */}
                <div className="form-group">
                  <div className="form-label">
                    <span>Tamanho da Área</span>
                    <span className="form-label-value">{staticCrop.sizePct}%</span>
                  </div>
                  <input 
                    type="range" min={10} max={100} step={1}
                    value={staticCrop.sizePct}
                    onChange={(e) => updateCrop({ sizePct: Number(e.target.value) })}
                    onMouseUp={pushHistory}
                    onTouchEnd={pushHistory}
                  />
                </div>

                {/* posX */}
                <div className="form-group">
                  <div className="form-label">
                    <span>Posição Horizontal</span>
                    <span className="form-label-value">{staticCrop.posX}%</span>
                  </div>
                  <input 
                    type="range" min={0} max={100} step={1}
                    value={staticCrop.posX}
                    onChange={(e) => updateCrop({ posX: Number(e.target.value) })}
                    onMouseUp={pushHistory}
                    onTouchEnd={pushHistory}
                  />
                </div>

                {/* posY */}
                <div className="form-group">
                  <div className="form-label">
                    <span>Posição Vertical</span>
                    <span className="form-label-value">{staticCrop.posY}%</span>
                  </div>
                  <input 
                    type="range" min={0} max={100} step={1}
                    value={staticCrop.posY}
                    onChange={(e) => updateCrop({ posY: Number(e.target.value) })}
                    onMouseUp={pushHistory}
                    onTouchEnd={pushHistory}
                  />
                </div>
              </>
            ) : (
              /* If custom, show Margin controls */
              <div style={{ background: 'rgba(0,0,0,0.15)', padding: '12px 12px 2px', borderRadius: 8, marginBottom: 16 }}>
                <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: 0.5 }}>
                  Recorte pelas Margens (%)
                </div>
                <div className="grid-2">
                  <div className="form-group">
                    <div className="form-label"><span>Esquerda</span><span className="form-label-value">{staticCrop.marginL}%</span></div>
                    <input 
                      type="range" min={0} max={49} step={1}
                      value={staticCrop.marginL}
                      onChange={(e) => updateCrop({ marginL: Number(e.target.value) })}
                      onMouseUp={pushHistory}
                      onTouchEnd={pushHistory}
                    />
                  </div>
                  <div className="form-group">
                    <div className="form-label"><span>Direita</span><span className="form-label-value">{staticCrop.marginR}%</span></div>
                    <input 
                      type="range" min={0} max={49} step={1}
                      value={staticCrop.marginR}
                      onChange={(e) => updateCrop({ marginR: Number(e.target.value) })}
                      onMouseUp={pushHistory}
                      onTouchEnd={pushHistory}
                    />
                  </div>
                </div>
                <div className="grid-2">
                  <div className="form-group">
                    <div className="form-label"><span>Superior</span><span className="form-label-value">{staticCrop.marginT}%</span></div>
                    <input 
                      type="range" min={0} max={49} step={1}
                      value={staticCrop.marginT}
                      onChange={(e) => updateCrop({ marginT: Number(e.target.value) })}
                      onMouseUp={pushHistory}
                      onTouchEnd={pushHistory}
                    />
                  </div>
                  <div className="form-group">
                    <div className="form-label"><span>Inferior</span><span className="form-label-value">{staticCrop.marginB}%</span></div>
                    <input 
                      type="range" min={0} max={49} step={1}
                      value={staticCrop.marginB}
                      onChange={(e) => updateCrop({ marginB: Number(e.target.value) })}
                      onMouseUp={pushHistory}
                      onTouchEnd={pushHistory}
                    />
                  </div>
                </div>
              </div>
            )}
          </div>

          <div className="divider" />

          {/* Video canvas positioning */}
          <div className="toggle-row" style={{ marginBottom: 12 }}>
            <span className="toggle-label" style={{ fontWeight: 600, color: 'var(--text-primary)' }}>Posição & Escala do Vídeo</span>
            <Toggle 
              checked={videoPosition.enabled} 
              onChange={(v) => setVideoPosition({ enabled: v })}
              onRelease={pushHistory}
            />
          </div>

          <div style={{ opacity: videoPosition.enabled ? 1 : 0.4, pointerEvents: videoPosition.enabled ? 'auto' : 'none', transition: 'opacity 0.2s' }}>
            {/* Translation X */}
            <div className="form-group">
              <div className="form-label">
                <span>Deslocamento Horizontal</span>
                <span className="form-label-value">{videoPosition.x > 0 ? '+' : ''}{videoPosition.x}%</span>
              </div>
              <input 
                type="range" min={-100} max={100} step={1}
                value={videoPosition.x}
                onChange={(e) => setVideoPosition({ x: Number(e.target.value) })}
                onMouseUp={pushHistory}
                onTouchEnd={pushHistory}
              />
            </div>

            {/* Translation Y */}
            <div className="form-group">
              <div className="form-label">
                <span>Deslocamento Vertical</span>
                <span className="form-label-value">{videoPosition.y > 0 ? '+' : ''}{videoPosition.y}%</span>
              </div>
              <input 
                type="range" min={-100} max={100} step={1}
                value={videoPosition.y}
                onChange={(e) => setVideoPosition({ y: Number(e.target.value) })}
                onMouseUp={pushHistory}
                onTouchEnd={pushHistory}
              />
            </div>

            {/* Scale */}
            <div className="form-group">
              <div className="form-label">
                <span>Escala (Zoom Final)</span>
                <span className="form-label-value">{videoPosition.scale.toFixed(2)}x</span>
              </div>
              <input 
                type="range" min={0.5} max={2.5} step={0.05}
                value={videoPosition.scale}
                onChange={(e) => setVideoPosition({ scale: Number(e.target.value) })}
                onMouseUp={pushHistory}
                onTouchEnd={pushHistory}
              />
            </div>
          </div>

          <div style={{ display: 'flex', gap: 10, marginTop: 20 }}>
            <button className="btn btn-secondary btn-sm" style={{ flex: 1 }} onClick={handleResetCrop}>
              🔄 Resetar Tudo
            </button>
          </div>
        </div>
      )}

      {/* TAB 2: PROGRESSIVE ZOOM */}
      {activeTab === 'zoom' && (
        <div>
          <div className="toggle-row" style={{ marginBottom: 16 }}>
            <span className="toggle-label" style={{ fontWeight: 600, color: 'var(--text-primary)' }}>Ativar Zoom & Foco</span>
            <Toggle 
              checked={cropZoom.enabled} 
              onChange={(v) => setCropZoom({ enabled: v })}
              onRelease={pushHistory}
            />
          </div>

          <div style={{ opacity: cropZoom.enabled ? 1 : 0.4, pointerEvents: cropZoom.enabled ? 'auto' : 'none', transition: 'opacity 0.2s' }}>
            <div className="toggle-row" style={{ marginBottom: 16, background: 'rgba(0,0,0,0.2)', padding: 8, borderRadius: 8 }}>
              <span className="toggle-label" style={{ fontSize: 13 }}>Zoom Animado (Início/Fim)</span>
              <Toggle 
                checked={cropZoom.animatedZoom ?? true} 
                onChange={(v) => setCropZoom({ animatedZoom: v })}
                onRelease={pushHistory}
              />
            </div>

            {/* Zoom values */}
            <div className="grid-2">
              <div className="form-group">
                <div className="form-label">
                  <span>{cropZoom.animatedZoom ? 'Zoom Inicial' : 'Nível de Zoom'}</span>
                  <span className="form-label-value">
                    {cropZoom.zoomStart >= 1.0 ? '+' : ''}{Math.round(getSliderValue(cropZoom.zoomStart))} ({(cropZoom.zoomStart).toFixed(2)}×)
                  </span>
                </div>
                <input
                  type="range" min={-50} max={50} step={1}
                  value={getSliderValue(cropZoom.zoomStart)}
                  onChange={(e) => {
                    const scale = getScaleValue(Number(e.target.value));
                    setCropZoom({ zoomStart: scale, zoomEnd: cropZoom.animatedZoom ? cropZoom.zoomEnd : scale });
                  }}
                  onMouseUp={pushHistory}
                  onTouchEnd={pushHistory}
                />
              </div>
              {cropZoom.animatedZoom !== false && (
                <div className="form-group">
                  <div className="form-label">
                    <span>Zoom Final</span>
                    <span className="form-label-value">
                      {cropZoom.zoomEnd >= 1.0 ? '+' : ''}{Math.round(getSliderValue(cropZoom.zoomEnd))} ({(cropZoom.zoomEnd).toFixed(2)}×)
                    </span>
                  </div>
                  <input
                    type="range" min={-50} max={50} step={1}
                    value={getSliderValue(cropZoom.zoomEnd)}
                    onChange={(e) => setCropZoom({ zoomEnd: getScaleValue(Number(e.target.value)) })}
                    onMouseUp={pushHistory}
                    onTouchEnd={pushHistory}
                  />
                </div>
              )}
            </div>

            {/* Focus point */}
            <div className="form-group">
              <div className="form-label" style={{ marginBottom: 8 }}>Ponto de Foco</div>
              <div className="grid-2">
                <div>
                  <div className="form-label">
                    <span>Horizontal</span>
                    <span className="form-label-value">{Math.round(cropZoom.focusX * 100)}%</span>
                  </div>
                  <input
                    type="range" min={0} max={1} step={0.01}
                    value={cropZoom.focusX}
                    onChange={(e) => setCropZoom({ focusX: Number(e.target.value) })}
                    onMouseUp={pushHistory}
                    onTouchEnd={pushHistory}
                  />
                </div>
                <div>
                  <div className="form-label">
                    <span>Vertical</span>
                    <span className="form-label-value">{Math.round(cropZoom.focusY * 100)}%</span>
                  </div>
                  <input
                    type="range" min={0} max={1} step={0.01}
                    value={cropZoom.focusY}
                    onChange={(e) => setCropZoom({ focusY: Number(e.target.value) })}
                    onMouseUp={pushHistory}
                    onTouchEnd={pushHistory}
                  />
                </div>
              </div>
            </div>

            {/* Focus point visual box */}
            <div
              style={{
                width: '100%',
                aspectRatio: '16/9',
                background: 'var(--bg-card)',
                borderRadius: 'var(--radius)',
                border: '1px solid var(--border)',
                position: 'relative',
                marginBottom: 16,
                overflow: 'hidden',
              }}
            >
              <div style={{
                position: 'absolute',
                left: `${cropZoom.focusX * 100}%`,
                top: `${cropZoom.focusY * 100}%`,
                transform: 'translate(-50%, -50%)',
                width: 16,
                height: 16,
                background: 'var(--accent)',
                borderRadius: '50%',
                boxShadow: '0 0 0 4px rgba(124,58,237,0.3)',
                pointerEvents: 'none',
                transition: 'left 0.1s, top 0.1s',
              }} />
              <div style={{
                position: 'absolute',
                left: '50%',
                bottom: 0,
                transform: 'translateX(-50%)',
                height: `${cropZoom.removeBottomSubtitlesPct}%`,
                width: '100%',
                background: 'rgba(239,68,68,0.2)',
                borderTop: '2px dashed rgba(239,68,68,0.6)',
              }}>
                <div style={{ position: 'absolute', top: -18, right: 8, fontSize: 10, color: 'rgba(239,68,68,0.8)' }}>
                  Legenda original
                </div>
              </div>
            </div>

            {/* Duration and remove subtitles */}
            <div className="grid-2">
              <div className="form-group">
                <div className="form-label">
                  <span>Duração Anim.</span>
                  <span className="form-label-value">{cropZoom.animDuration}s</span>
                </div>
                <input
                  type="range" min={0.5} max={5} step={0.1}
                  value={cropZoom.animDuration}
                  onChange={(e) => setCropZoom({ animDuration: Number(e.target.value) })}
                  onMouseUp={pushHistory}
                  onTouchEnd={pushHistory}
                />
              </div>
              <div className="form-group">
                <div className="form-label">
                  <span>Corte inferior</span>
                  <span className="form-label-value">{cropZoom.removeBottomSubtitlesPct}%</span>
                </div>
                <input
                  type="range" min={0} max={30} step={1}
                  value={cropZoom.removeBottomSubtitlesPct}
                  onChange={(e) => setCropZoom({ removeBottomSubtitlesPct: Number(e.target.value) })}
                  onMouseUp={pushHistory}
                  onTouchEnd={pushHistory}
                />
              </div>
            </div>
          </div>
        </div>
      )}

      {/* TAB 3: ADVANCED VIDEO EDIT */}
      {activeTab === 'edit' && (
        <div>
          {/* Flip controls */}
          <div className="form-group" style={{ marginBottom: 18 }}>
            <label className="form-label">Espelhamento de Vídeo</label>
            <div className="grid-2">
              <button 
                className={`btn btn-sm ${videoEdit.hFlip ? 'btn-primary' : 'btn-secondary'}`}
                onClick={() => {
                  setVideoEdit({ hFlip: !videoEdit.hFlip });
                  setTimeout(pushHistory, 50);
                }}
                style={{ justifyContent: 'center' }}
              >
                {videoEdit.hFlip ? '✓ Espelhado H' : 'Espelhar Horizontal ↔'}
              </button>
              <button 
                className={`btn btn-sm ${videoEdit.vFlip ? 'btn-primary' : 'btn-secondary'}`}
                onClick={() => {
                  setVideoEdit({ vFlip: !videoEdit.vFlip });
                  setTimeout(pushHistory, 50);
                }}
                style={{ justifyContent: 'center' }}
              >
                {videoEdit.vFlip ? '✓ Espelhado V' : 'Espelhar Vertical ↕'}
              </button>
            </div>
          </div>

          {/* Rotation controls */}
          <div className="form-group" style={{ marginBottom: 18 }}>
            <label className="form-label">Rotação do Vídeo</label>
            <div className="grid-3" style={{ gridTemplateColumns: 'repeat(4, 1fr)', gap: 4 }}>
              {([0, 90, 180, 270] as const).map((angle) => (
                <button
                  key={angle}
                  className={`btn btn-sm ${videoEdit.rotate === angle ? 'btn-primary' : 'btn-secondary'}`}
                  onClick={() => {
                    setVideoEdit({ rotate: angle });
                    setTimeout(pushHistory, 50);
                  }}
                  style={{ justifyContent: 'center', padding: '6px 2px' }}
                >
                  {angle}°
                </button>
              ))}
            </div>
          </div>

          {/* Playback speed control */}
          <div className="form-group" style={{ marginBottom: 18 }}>
            <div className="form-label">
              <span>Velocidade de Reprodução</span>
              <span className="form-label-value">{videoEdit.speed.toFixed(2)}x</span>
            </div>
            <input 
              type="range" min={0.5} max={2.0} step={0.05}
              value={videoEdit.speed}
              onChange={(e) => setVideoEdit({ speed: Number(e.target.value) })}
              onMouseUp={pushHistory}
              onTouchEnd={pushHistory}
            />
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: 'var(--text-muted)', marginTop: 4 }}>
              <span>Câmera Lenta (0.5x)</span>
              <span>Normal (1.0x)</span>
              <span>Acelerado (2.0x)</span>
            </div>
          </div>

          <div className="divider" />

          {/* Audio volume control */}
          <div className="form-group" style={{ marginBottom: 16 }}>
            <div className="form-label">
              <span>Volume de Áudio</span>
              <span className="form-label-value">{videoEdit.volume}%</span>
            </div>
            <input 
              type="range" min={0} max={200} step={5}
              value={videoEdit.volume}
              onChange={(e) => setVideoEdit({ volume: Number(e.target.value) })}
              onMouseUp={pushHistory}
              onTouchEnd={pushHistory}
            />
          </div>

          {/* Audio Fades */}
          <div className="grid-2">
            <div className="form-group">
              <div className="form-label">
                <span>Áudio Fade In</span>
                <span className="form-label-value">{videoEdit.audioFadeIn}s</span>
              </div>
              <input 
                type="range" min={0} max={5} step={0.5}
                value={videoEdit.audioFadeIn}
                onChange={(e) => setVideoEdit({ audioFadeIn: Number(e.target.value) })}
                onMouseUp={pushHistory}
                onTouchEnd={pushHistory}
              />
            </div>
            <div className="form-group">
              <div className="form-label">
                <span>Áudio Fade Out</span>
                <span className="form-label-value">{videoEdit.audioFadeOut}s</span>
              </div>
              <input 
                type="range" min={0} max={5} step={0.5}
                value={videoEdit.audioFadeOut}
                onChange={(e) => setVideoEdit({ audioFadeOut: Number(e.target.value) })}
                onMouseUp={pushHistory}
                onTouchEnd={pushHistory}
              />
            </div>
          </div>

          <div style={{ display: 'flex', gap: 10, marginTop: 20 }}>
            <button className="btn btn-secondary btn-sm" style={{ flex: 1 }} onClick={handleResetEdit}>
              🔄 Resetar Edição
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
