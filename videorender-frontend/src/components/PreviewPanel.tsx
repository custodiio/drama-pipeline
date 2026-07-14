import { useEffect, useRef, useState } from 'react';
import { useProjectStore, getOutputDimensions } from '../store/projectStore';
import { formatDuration } from '../utils/frameExtractor';

export function PreviewPanel() {
  const {
    extractedFrames,
    selectedFrameId,
    setSelectedFrame,
    blurBand,
    cropZoom,
    staticCrop,
    videoPosition,
    videoEdit,
    colorGrade,
    outputFormat,
    background,
    videoInfo,
    overlays,
  } = useProjectStore();

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const fullCanvasRef = useRef<HTMLCanvasElement>(null);
  const [showFullPreview, setShowFullPreview] = useState(false);
  const [applyEditsToGrid, setApplyEditsToGrid] = useState(false);

  const selectedFrame = extractedFrames.find((f) => f.id === selectedFrameId);

  // Shared render function for both small and full canvases
  const renderToCanvas = (canvas: HTMLCanvasElement | null) => {
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const [outW, outH] = getOutputDimensions(outputFormat);
    canvas.width = outW;
    canvas.height = outH;
    
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = 'high';

    ctx.fillStyle = '#050508';
    ctx.fillRect(0, 0, outW, outH);

    if (!selectedFrame) {
      ctx.fillStyle = 'rgba(255,255,255,0.05)';
      ctx.font = '11px Inter';
      ctx.textAlign = 'center';
      ctx.fillText('Sem frame selecionado', outW / 2, outH / 2);
      return;
    }

    const img = new Image();
    img.src = selectedFrame.dataUrl;
    img.onload = () => {
      ctx.clearRect(0, 0, outW, outH);

      // Background
      if (background.type === 'blur') {
        // Draw blurred bg
        ctx.filter = `blur(${background.blurIntensity}px)`;
        ctx.drawImage(img, -20, -20, outW + 40, outH + 40);
        ctx.filter = 'none';
      } else if (background.type === 'solid') {
        ctx.fillStyle = background.solidColor;
        ctx.fillRect(0, 0, outW, outH);
      } else if (background.type === 'gradient') {
        const grad = ctx.createLinearGradient(0, 0, outW, outH);
        grad.addColorStop(0, background.gradient[0]);
        grad.addColorStop(1, background.gradient[1]);
        ctx.fillStyle = grad;
        ctx.fillRect(0, 0, outW, outH);
      }

      // Crop calculation
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
        if (cropZoom.animatedZoom !== false && videoInfo && videoInfo.duration > 0) {
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
      const outAspect = outW / outH;
      let dw = outW;
      let dh = outH;
      let dx = 0;
      let dy = 0;

      if (cropAspect > outAspect) {
        dw = outW;
        dh = dw / cropAspect;
        dx = 0;
        dy = (outH - dh) / 2;
      } else {
        dh = outH;
        dw = dh * cropAspect;
        dx = (outW - dw) / 2;
        dy = 0;
      }

      // Video translation & scaling inside canvas
      if (videoPosition?.enabled) {
        const tx = (videoPosition.x / 100) * outW;
        const ty = (videoPosition.y / 100) * outH;
        dw = dw * videoPosition.scale;
        dh = dh * videoPosition.scale;
        dx = (outW - dw) / 2 + tx;
        dy = (outH - dh) / 2 + ty;
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
        const bandH = (blurBand.height / 100) * outH;
        const bandY = (blurBand.positionY / 100) * outH - bandH / 2;
        const featherPx = bandH * (blurBand.feather / 100) / 2;
        
        // Downscale to make blur safe and fast on all browsers
        const scale = 4;
        const off = document.createElement('canvas');
        off.width = Math.ceil(outW / scale);
        off.height = Math.ceil(outH / scale);
        const octx = off.getContext('2d')!;
        octx.imageSmoothingEnabled = true;
        octx.imageSmoothingQuality = 'high';
        
        octx.filter = `blur(${Math.max(1, blurBand.blurIntensity / scale)}px)`;
        octx.drawImage(canvas, 0, 0, outW, outH, 0, 0, off.width, off.height);
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
        blurredFull.width = outW;
        blurredFull.height = outH;
        const bfctx = blurredFull.getContext('2d')!;
        bfctx.imageSmoothingEnabled = true;
        bfctx.imageSmoothingQuality = 'high';
        bfctx.drawImage(off, 0, 0, off.width, off.height, 0, 0, outW, outH);

        // Mask for the band
        const mask = document.createElement('canvas');
        mask.width = outW;
        mask.height = outH;
        const mctx = mask.getContext('2d')!;
        
        const grad = mctx.createLinearGradient(0, bandY - featherPx, 0, bandY + bandH + featherPx);
        grad.addColorStop(0, 'rgba(0,0,0,0)');
        grad.addColorStop(Math.max(0, Math.min(1, featherPx / (bandH + featherPx * 2))), 'rgba(0,0,0,1)');
        grad.addColorStop(Math.max(0, Math.min(1, 1 - featherPx / (bandH + featherPx * 2))), 'rgba(0,0,0,1)');
        grad.addColorStop(1, 'rgba(0,0,0,0)');
        
        mctx.fillStyle = grad;
        mctx.fillRect(0, bandY - featherPx, outW, bandH + featherPx * 2);

        // Apply mask to full size blurred canvas
        bfctx.globalCompositeOperation = 'destination-in';
        bfctx.drawImage(mask, 0, 0);

        // Draw back to main canvas
        ctx.drawImage(blurredFull, 0, 0);
      }

      // Draw blur band guide lines
      if (blurBand.enabled) {
        const bandH2 = (blurBand.height / 100) * outH;
        const bandY2 = (blurBand.positionY / 100) * outH - bandH2 / 2;
        ctx.save();
        ctx.setLineDash([8, 4]);
        ctx.strokeStyle = 'rgba(6, 182, 212, 0.6)';
        ctx.lineWidth = 2;
        ctx.strokeRect(0, bandY2, outW, bandH2);
        ctx.fillStyle = 'rgba(6, 182, 212, 0.08)';
        ctx.fillRect(0, bandY2, outW, bandH2);
        // Label
        ctx.font = `${Math.round(outH / 60)}px Inter`;
        ctx.fillStyle = 'rgba(6, 182, 212, 0.7)';
        ctx.textAlign = 'left';
        ctx.fillText('Blur Band', 10, bandY2 - 6);
        ctx.restore();
      }

      // Vignette
      if (colorGrade.vignette > 0) {
        const vGrad = ctx.createRadialGradient(outW / 2, outH / 2, outW * 0.3, outW / 2, outH / 2, outW * 0.8);
        vGrad.addColorStop(0, 'rgba(0,0,0,0)');
        vGrad.addColorStop(1, `rgba(0,0,0,${colorGrade.vignette})`);
        ctx.fillStyle = vGrad;
        ctx.fillRect(0, 0, outW, outH);
      }

      // Draw Overlays
      overlays.forEach(o => {
        ctx.save();
        ctx.globalAlpha = o.opacity;
        
        const ox = (o.x / 100) * outW;
        const oy = (o.y / 100) * outH;
        const ow = (o.width / 100) * outW;
        const oh = (o.height / 100) * outH;

        if (o.type === 'image') {
          const oimg = new Image();
          oimg.src = o.content;
          if (oimg.complete) {
            ctx.drawImage(oimg, ox, oy, ow, oh);
          } else {
            oimg.onload = () => ctx.drawImage(oimg, ox, oy, ow, oh);
          }
        } else {
          const fontSize = Math.round((o.fontSize || 32) * (outH / 1080));
          ctx.font = `${o.type === 'watermark' ? 'bold ' : ''}${fontSize}px ${o.fontFamily || 'Montserrat'}`;
          ctx.fillStyle = o.fontColor || '#FFFFFF';
          ctx.textAlign = 'left';
          ctx.textBaseline = 'top';
          ctx.fillText(o.content, ox, oy);
        }
        ctx.restore();
      });
    };
  };

  // Render to small canvas
  useEffect(() => {
    renderToCanvas(canvasRef.current);
  }, [selectedFrame, blurBand, cropZoom, staticCrop, videoPosition, videoEdit, colorGrade, background, outputFormat, overlays]);

  // Render to full canvas when modal is open
  useEffect(() => {
    if (showFullPreview) {
      renderToCanvas(fullCanvasRef.current);
    }
  }, [showFullPreview, selectedFrame, blurBand, cropZoom, staticCrop, videoPosition, videoEdit, colorGrade, background, outputFormat, overlays]);

  const handleFullscreen = () => {
    setShowFullPreview(true);
  };

  return (
    <div className="app-panel">
      {/* Preview */}
      <div className="panel-section">
        <div className="panel-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span>Preview Visual</span>
          <button className="btn btn-sm" onClick={handleFullscreen} style={{ padding: '2px 8px', fontSize: 10 }}>
            ⛶ Tela Cheia
          </button>
        </div>
        <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 10 }}>
          <div style={{
            position: 'relative',
            borderRadius: 'var(--radius)',
            overflow: 'hidden',
            border: '1px solid var(--border)',
            boxShadow: 'var(--shadow-float)',
          }}>
            <canvas
              ref={canvasRef}
              style={{
                display: 'block',
                maxWidth: '100%',
                maxHeight: 300,
              }}
            />
          </div>
        </div>
        <div style={{ display: 'flex', justifyContent: 'center', gap: 8 }}>
          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
            {outputFormat} · {`${getOutputDimensions(outputFormat)[0]}×${getOutputDimensions(outputFormat)[1]}`}
          </span>
        </div>
      </div>

      {/* Frame selector */}
      {extractedFrames.length > 0 && (() => {
        let filterStr = '';
        if (colorGrade.brightness !== 0 || colorGrade.contrast !== 0 || colorGrade.saturation !== 0) {
          filterStr = `brightness(${1 + colorGrade.brightness / 100}) contrast(${1 + colorGrade.contrast / 100}) saturate(${1 + colorGrade.saturation / 100})`;
        }
        
        let transformStr = '';
        if (videoEdit?.hFlip) transformStr += ' scaleX(-1)';
        if (videoEdit?.vFlip) transformStr += ' scaleY(-1)';
        if (videoEdit?.rotate) {
          transformStr += ` rotate(${videoEdit.rotate}deg)`;
        }

        return (
          <div className="panel-section">
            <div className="panel-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span>Frames ({extractedFrames.length})</span>
              <button 
                className={`btn btn-sm ${applyEditsToGrid ? 'btn-primary' : 'btn-secondary'}`} 
                onClick={() => setApplyEditsToGrid(!applyEditsToGrid)}
                style={{ padding: '2px 8px', fontSize: 10, height: 20 }}
              >
                {applyEditsToGrid ? '✓ Efeitos' : 'Sem Efeitos'}
              </button>
            </div>
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(2, 1fr)',
              gap: 6,
            }}>
              {extractedFrames.map((frame) => {
                let imgStyle: React.CSSProperties = {
                  width: '100%',
                  height: '100%',
                  objectFit: 'cover',
                  display: 'block',
                  transition: 'transform 0.2s, filter 0.2s',
                };
                if (applyEditsToGrid) {
                  imgStyle.filter = filterStr;
                  imgStyle.transform = transformStr;
                  if (staticCrop?.enabled) {
                    const scaleFactor = 100 / Math.max(10, staticCrop.width);
                    imgStyle.transform = `${transformStr} scale(${scaleFactor.toFixed(2)})`;
                    imgStyle.transformOrigin = 'center center';
                    // object-position is supported on img tags to shift origin
                    imgStyle.objectPosition = `${staticCrop.x + staticCrop.width / 2}% ${staticCrop.y + staticCrop.height / 2}%`;
                  }
                }

                return (
                  <div
                    key={frame.id}
                    className={`frame-card ${selectedFrameId === frame.id ? 'selected' : ''}`}
                    style={{ aspectRatio: '16/9', overflow: 'hidden' }}
                    onClick={() => setSelectedFrame(frame.id)}
                  >
                    <img 
                      src={frame.dataUrl} 
                      alt={`Frame ${frame.id}`} 
                      loading="lazy" 
                      style={imgStyle}
                    />
                    <div className="frame-time">{formatDuration(frame.timeSeconds)}</div>
                    <div className="frame-check">✓</div>
                  </div>
                );
              })}
            </div>
          </div>
        );
      })()}

      {/* Video info */}
      {videoInfo && (
        <div className="panel-section">
          <div className="panel-title">Info do Vídeo</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {[
              { label: 'Arquivo', value: videoInfo.fileName },
              { label: 'Resolução', value: `${videoInfo.width}×${videoInfo.height}` },
              { label: 'Duração', value: formatDuration(videoInfo.duration) },
              { label: 'Aspecto', value: videoInfo.aspect },
            ].map(({ label, value }) => (
              <div key={label} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
                <span style={{ color: 'var(--text-muted)' }}>{label}</span>
                <span style={{ color: 'var(--text-primary)', fontWeight: 600, maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', textAlign: 'right', fontFamily: label === 'Arquivo' ? 'inherit' : 'JetBrains Mono' }}>
                  {value}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Active configs summary */}
      <div className="panel-section">
        <div className="panel-title">Configurações Ativas</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {[
            { label: 'Zoom/Recorte', active: cropZoom.enabled, value: `${cropZoom.zoomStart}× → ${cropZoom.zoomEnd}×` },
            { label: 'Blur Band', active: blurBand.enabled, value: `${blurBand.position} ${blurBand.height}%` },
            { label: 'Color Grade', active: colorGrade.preset !== 'none', value: colorGrade.preset },
          ].map(({ label, active, value }) => (
            <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
              <span style={{
                width: 6, height: 6, borderRadius: '50%', flexShrink: 0,
                background: active ? 'var(--success)' : 'var(--text-muted)',
              }} />
              <span style={{ color: 'var(--text-muted)', flex: 1 }}>{label}</span>
              <span style={{ color: active ? 'var(--text-primary)' : 'var(--text-muted)', fontWeight: 600, fontSize: 11 }}>
                {active ? value : 'off'}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Fullscreen Modal */}
      {showFullPreview && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 9999,
            background: 'rgba(0,0,0,0.92)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            cursor: 'pointer',
            backdropFilter: 'blur(8px)',
          }}
          onClick={() => setShowFullPreview(false)}
        >
          <div style={{ position: 'relative', maxWidth: '90vw', maxHeight: '90vh' }}>
            <canvas
              ref={fullCanvasRef}
              style={{
                display: 'block',
                maxWidth: '90vw',
                maxHeight: '90vh',
                borderRadius: 12,
                boxShadow: '0 0 60px rgba(124, 58, 237, 0.3)',
              }}
            />
            <div style={{
              position: 'absolute', top: -36, right: 0,
              color: 'var(--text-muted)', fontSize: 12,
              fontFamily: 'JetBrains Mono',
            }}>
              {`${getOutputDimensions(outputFormat)[0]}×${getOutputDimensions(outputFormat)[1]}`} · Clique para fechar
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
