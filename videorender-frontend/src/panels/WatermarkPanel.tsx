import { useRef, useEffect, useCallback } from 'react';
import { useProjectStore } from '../store/projectStore';
import { useExportActions } from '../hooks/useExportActions';

function genId() {
  return Math.random().toString(36).slice(2);
}

export function WatermarkPanel() {
  const { 
    watermarks, addWatermark, updateWatermark, removeWatermark,
    extractedFrames, selectedFrameId, outputFormat,
    blurBand, cropZoom, staticCrop, videoPosition, videoEdit, colorGrade, background, videoInfo
  } = useProjectStore();
  
  const { exportMask } = useExportActions();
  
  const canvasRef = useRef<HTMLCanvasElement>(null);

  const selectedFrame = extractedFrames.find(f => f.id === selectedFrameId);

  const drawVideoBackground = useCallback((ctx: CanvasRenderingContext2D, canvas: HTMLCanvasElement, img: HTMLImageElement) => {
    // 1. Draw Background
    if (background.type === 'blur') {
      ctx.filter = `blur(${background.blurIntensity}px)`;
      ctx.drawImage(img, -20, -20, canvas.width + 40, canvas.height + 40);
      ctx.filter = 'none';
    } else if (background.type === 'solid') {
      ctx.fillStyle = background.solidColor;
      ctx.fillRect(0, 0, canvas.width, canvas.height);
    } else if (background.type === 'gradient') {
      const grad = ctx.createLinearGradient(0, 0, canvas.width, canvas.height);
      grad.addColorStop(0, background.gradient[0]);
      grad.addColorStop(1, background.gradient[1]);
      ctx.fillStyle = grad;
      ctx.fillRect(0, 0, canvas.width, canvas.height);
    }

    // 2. Crop calculation
    let sx = 0;
    let sy = 0;
    let sw = img.width;
    let sh = img.height;

    if (staticCrop?.enabled) {
      sx = (staticCrop.x / 100) * img.width;
      sy = (staticCrop.y / 100) * img.height;
      sw = (staticCrop.width / 100) * img.width;
      sh = (staticCrop.height / 100) * img.height;
    } else if (cropZoom?.enabled) {
      let currentZoom = cropZoom.zoomStart;
      if (cropZoom.animatedZoom !== false && videoInfo && videoInfo.duration > 0 && selectedFrame) {
        const progress = selectedFrame.timeSeconds / videoInfo.duration;
        currentZoom = cropZoom.zoomStart + (cropZoom.zoomEnd - cropZoom.zoomStart) * progress;
      }
      const czw = img.width / currentZoom;
      const czh = img.height / currentZoom;
      sx = Math.max(0, Math.min(img.width - czw, (img.width - czw) * cropZoom.focusX));
      sy = Math.max(0, Math.min(img.height - czh, (img.height - czh) * cropZoom.focusY));
      sw = czw;
      sh = czh;
    }

    // Aspect ratio fit
    const cropAspect = sw / sh;
    const outAspect = canvas.width / canvas.height;
    let dw = canvas.width;
    let dh = canvas.height;
    let dx = 0;
    let dy = 0;

    if (cropAspect > outAspect) {
      dw = canvas.width;
      dh = dw / cropAspect;
      dx = 0;
      dy = (canvas.height - dh) / 2;
    } else {
      dh = canvas.height;
      dw = dh * cropAspect;
      dx = (canvas.width - dw) / 2;
      dy = 0;
    }

    // Video translation & scaling inside canvas
    if (videoPosition?.enabled) {
      const tx = (videoPosition.x / 100) * canvas.width;
      const ty = (videoPosition.y / 100) * canvas.height;
      dw = dw * videoPosition.scale;
      dh = dh * videoPosition.scale;
      dx = (canvas.width - dw) / 2 + tx;
      dy = (canvas.height - dh) / 2 + ty;
    }

    // Draw original image with flips and rotation (geom transforms from videoEdit)
    ctx.save();
    ctx.translate(dx + dw / 2, dy + dh / 2);
    
    if (videoEdit?.hFlip) ctx.scale(-1, 1);
    if (videoEdit?.vFlip) ctx.scale(1, -1);
    if (videoEdit?.rotate) {
      ctx.rotate((videoEdit.rotate * Math.PI) / 180);
    }
    
    ctx.drawImage(img, sx, sy, sw, sh, -dw / 2, -dh / 2, dw, dh);
    ctx.restore();

    // Color grade simulation (brightness/contrast)
    if (colorGrade.brightness !== 0 || colorGrade.contrast !== 0 || colorGrade.saturation !== 0) {
      ctx.filter = `brightness(${1 + colorGrade.brightness / 100}) contrast(${1 + colorGrade.contrast / 100}) saturate(${1 + colorGrade.saturation / 100})`;
      ctx.drawImage(canvas, 0, 0);
      ctx.filter = 'none';
    }

    // Blur bands
    if (blurBand.enabled) {
      const bandH = (blurBand.height / 100) * canvas.height;
      const bandY = (blurBand.positionY / 100) * canvas.height - bandH / 2;
      const featherPx = bandH * (blurBand.feather / 100) / 2;
      
      // Downscale to make blur safe and fast on all browsers
      const scale = 4;
      const off = document.createElement('canvas');
      off.width = Math.ceil(canvas.width / scale);
      off.height = Math.ceil(canvas.height / scale);
      const octx = off.getContext('2d')!;
      octx.imageSmoothingEnabled = true;
      octx.imageSmoothingQuality = 'high';
      
      octx.filter = `blur(${Math.max(1, blurBand.blurIntensity / scale)}px)`;
      octx.drawImage(canvas, 0, 0, canvas.width, canvas.height, 0, 0, off.width, off.height);
      octx.filter = 'none';

      // Draw color overlay on the blurred offscreen canvas if enabled
      if (blurBand.colorOverlayEnabled && blurBand.opacity > 0) {
        octx.fillStyle = blurBand.color;
        octx.globalAlpha = blurBand.opacity;
        octx.fillRect(0, 0, off.width, off.height);
        octx.globalAlpha = 1.0;
      }

      // Draw back to full size blurred canvas
      const blurredFull = document.createElement('canvas');
      blurredFull.width = canvas.width;
      blurredFull.height = canvas.height;
      const bfctx = blurredFull.getContext('2d')!;
      bfctx.imageSmoothingEnabled = true;
      bfctx.imageSmoothingQuality = 'high';
      bfctx.drawImage(off, 0, 0, off.width, off.height, 0, 0, canvas.width, canvas.height);

      const mask = document.createElement('canvas');
      mask.width = canvas.width;
      mask.height = canvas.height;
      const mctx = mask.getContext('2d')!;
      
      const grad = mctx.createLinearGradient(0, bandY - featherPx, 0, bandY + bandH + featherPx);
      grad.addColorStop(0, 'rgba(0,0,0,0)');
      grad.addColorStop(Math.max(0, Math.min(1, featherPx / (bandH + featherPx * 2))), 'rgba(0,0,0,1)');
      grad.addColorStop(Math.max(0, Math.min(1, 1 - featherPx / (bandH + featherPx * 2))), 'rgba(0,0,0,1)');
      grad.addColorStop(1, 'rgba(0,0,0,0)');
      
      mctx.fillStyle = grad;
      mctx.fillRect(0, bandY - featherPx, canvas.width, bandH + featherPx * 2);

      bfctx.globalCompositeOperation = 'destination-in';
      bfctx.drawImage(mask, 0, 0);

      ctx.drawImage(blurredFull, 0, 0);
    }
  }, [background, staticCrop, cropZoom, videoInfo, selectedFrame, videoPosition, videoEdit, colorGrade, blurBand]);

  const drawBoxes = useCallback((ctx: CanvasRenderingContext2D, canvasW: number, canvasH: number) => {
    watermarks.forEach(w => {
      ctx.save();
      
      const wx = (w.x / 100) * canvasW;
      const wy = (w.y / 100) * canvasH;
      const ww = (w.width / 100) * canvasW;
      const wh = (w.height / 100) * canvasH;

      if (w.filled) {
        ctx.fillStyle = 'rgba(255, 255, 255, 0.8)';
        ctx.fillRect(wx, wy, ww, wh);
      } else {
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.8)';
        ctx.lineWidth = 4;
        ctx.strokeRect(wx, wy, ww, wh);
      }
      
      // Label
      ctx.fillStyle = '#FF6B6B';
      ctx.font = 'bold 14px Montserrat';
      ctx.fillText('Remover', wx, wy > 20 ? wy - 6 : wy + 16);
      
      ctx.restore();
    });
  }, [watermarks]);

  const drawFrame = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = 'high';
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    if (selectedFrame) {
      const img = new Image();
      img.src = selectedFrame.dataUrl;
      const render = () => {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
        // Dim the background a bit to highlight the masks
        ctx.fillStyle = 'rgba(0,0,0,0.3)';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        drawBoxes(ctx, canvas.width, canvas.height);
      };
      if (img.complete) render();
      else img.onload = render;
    } else {
      ctx.fillStyle = '#0a0a12';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      drawBoxes(ctx, canvas.width, canvas.height);
    }
  }, [selectedFrame, drawBoxes]);

  useEffect(() => {
    drawFrame();
  }, [drawFrame, watermarks]);

  const addBox = () => {
    addWatermark({
      id: genId(),
      x: 10,
      y: 10,
      width: 20,
      height: 10,
      filled: true,
    });
  };

  const activeBox = watermarks[watermarks.length - 1];

  return (
    <div className="panel-content">
      <h2 style={{ fontFamily: 'Montserrat', fontWeight: 900, fontSize: 20, marginBottom: 6 }}>
        🧹 Remoção de Marca d'água
      </h2>
      <p style={{ color: 'var(--text-muted)', marginBottom: 16, fontSize: 13 }}>
        Defina as áreas para aplicar o filtro de remoção (removelogo).
      </p>

      {/* Preview Canvas */}
      <div style={{ marginBottom: 20, display: 'flex', justifyContent: 'center' }}>
        <div style={{
          position: 'relative',
          background: '#000',
          borderRadius: 'var(--radius-lg)',
          overflow: 'hidden',
          border: '1px solid var(--border)',
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          maxWidth: '100%',
        }}>
          <canvas
            ref={canvasRef}
            width={videoInfo ? videoInfo.width : 1920}
            height={videoInfo ? videoInfo.height : 1080}
            style={{
              display: 'block',
              maxWidth: '100%',
              maxHeight: '360px',
              objectFit: 'contain',
            }}
          />
        </div>
      </div>

      {/* Add buttons */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 20 }}>
        <button className="btn btn-primary btn-sm" onClick={addBox}>
          ➕ Adicionar Área
        </button>
        <button 
          className="btn btn-secondary btn-sm" 
          onClick={exportMask}
          disabled={watermarks.length === 0}
        >
          ⬇️ Baixar mask.png
        </button>
      </div>

      {watermarks.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '32px 16px', color: 'var(--text-muted)', background: 'var(--bg-card)', borderRadius: 'var(--radius)', border: '1px solid var(--border)' }}>
          <div style={{ fontSize: 32, marginBottom: 8 }}>🧹</div>
          <div style={{ fontSize: 13 }}>Nenhuma área de remoção definida</div>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div style={{ display: 'flex', gap: 8, overflowX: 'auto', paddingBottom: 8 }}>
            {watermarks.map((w) => (
              <div 
                key={w.id} 
                className={`overlay-chip ${w === activeBox ? 'active' : ''}`}
                style={{
                  padding: '6px 12px',
                  background: w === activeBox ? 'var(--primary)' : 'var(--bg-card)',
                  borderRadius: 20,
                  fontSize: 12,
                  whiteSpace: 'nowrap',
                  cursor: 'pointer',
                  border: '1px solid var(--border)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6
                }}
              >
                <span>📦 Box</span>
                <button 
                  onClick={(e) => { e.stopPropagation(); removeWatermark(w.id); }}
                  style={{ background: 'none', border: 'none', color: 'inherit', cursor: 'pointer', fontSize: 14, padding: 0 }}
                >
                  ×
                </button>
              </div>
            ))}
          </div>

          {activeBox && (
            <div className="card" style={{ padding: 16, background: 'rgba(255,255,255,0.02)' }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--primary)', marginBottom: 12, textTransform: 'uppercase', letterSpacing: 1 }}>
                Configurações da Área
              </div>

              <div className="form-group" style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
                <div className="form-label" style={{ marginBottom: 0 }}>Preenchimento Total</div>
                <label className="switch">
                  <input
                    type="checkbox"
                    checked={activeBox.filled}
                    onChange={(e) => updateWatermark(activeBox.id, { filled: e.target.checked })}
                  />
                  <span className="slider"></span>
                </label>
              </div>

              <div className="grid-2" style={{ marginTop: 12 }}>
                <div className="form-group">
                  <div className="form-label">Posição X ({activeBox.x}%)</div>
                  <input type="range" min={0} max={100} value={activeBox.x} onChange={(e) => updateWatermark(activeBox.id, { x: Number(e.target.value) })} />
                </div>
                <div className="form-group">
                  <div className="form-label">Posição Y ({activeBox.y}%)</div>
                  <input type="range" min={0} max={100} value={activeBox.y} onChange={(e) => updateWatermark(activeBox.id, { y: Number(e.target.value) })} />
                </div>
              </div>

              <div className="grid-2">
                <div className="form-group">
                  <div className="form-label">Largura ({activeBox.width}%)</div>
                  <input type="range" min={1} max={100} value={activeBox.width} onChange={(e) => updateWatermark(activeBox.id, { width: Number(e.target.value) })} />
                </div>
                <div className="form-group">
                  <div className="form-label">Altura ({activeBox.height}%)</div>
                  <input type="range" min={1} max={100} value={activeBox.height} onChange={(e) => updateWatermark(activeBox.id, { height: Number(e.target.value) })} />
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
