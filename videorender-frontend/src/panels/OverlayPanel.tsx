import { useRef, useEffect, useCallback, useState } from 'react';
import { useProjectStore, getOutputDimensions } from '../store/projectStore';

function genId() {
  return Math.random().toString(36).slice(2);
}

export function OverlayPanel() {
  const { 
    overlays, addOverlay, updateOverlay, removeOverlay,
    extractedFrames, selectedFrameId, outputFormat,
    blurBand, cropZoom, staticCrop, videoPosition, videoEdit, colorGrade, background, videoInfo
  } = useProjectStore();
  
  const imgInputRef = useRef<HTMLInputElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  const [galleryOpen, setGalleryOpen] = useState(false);
  const [galleryItems, setGalleryItems] = useState<{id: string, name: string, image_data: string}[]>([]);
  const [activeOverlayId, setActiveOverlayId] = useState<string | null>(null);

  const selectedFrame = extractedFrames.find(f => f.id === selectedFrameId);

  // Sync activeOverlayId with overlays array
  useEffect(() => {
    if (overlays.length > 0) {
      if (!activeOverlayId || !overlays.some(o => o.id === activeOverlayId)) {
        setActiveOverlayId(overlays[overlays.length - 1].id);
      }
    } else {
      setActiveOverlayId(null);
    }
  }, [overlays, activeOverlayId]);

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

  const drawOverlays = useCallback((ctx: CanvasRenderingContext2D, canvasW: number, canvasH: number) => {
    overlays.forEach(o => {
      ctx.save();
      ctx.globalAlpha = o.opacity;
      
      const ox = (o.x / 100) * canvasW;
      const oy = (o.y / 100) * canvasH;
      const ow = (o.width / 100) * canvasW;
      const oh = (o.height / 100) * canvasH;

      if (o.type === 'image') {
        const img = new Image();
        img.src = o.content;
        if (img.complete) {
          ctx.drawImage(img, ox, oy, ow, oh);
        }
      } else {
        const fontSize = Math.round((o.fontSize || 32) * (canvasH / 1080));
        
        // Draw background box if bgColor is set
        if (o.bgColor) {
          ctx.font = `${o.fontStyle || ''} ${o.fontWeight || o.type === 'watermark' ? 'bold' : 'normal'} ${fontSize}px ${o.fontFamily || 'Montserrat'}`;
          const metrics = ctx.measureText(o.content);
          const bgOpacity = o.bgOpacity !== undefined ? o.bgOpacity : 0.5;
          ctx.fillStyle = o.bgColor;
          ctx.globalAlpha = o.opacity * bgOpacity;
          const padding = fontSize * 0.2;
          
          // Draw rect
          ctx.fillRect(ox - padding, oy - padding, metrics.width + padding * 2, fontSize + padding * 2);
          ctx.globalAlpha = o.opacity;
        }

        ctx.font = `${o.fontStyle || ''} ${o.fontWeight || o.type === 'watermark' ? 'bold' : 'normal'} ${fontSize}px ${o.fontFamily || 'Montserrat'}`;
        ctx.fillStyle = o.fontColor || '#FFFFFF';
        
        // Add shadow if set
        if (o.shadowColor) {
          ctx.shadowColor = o.shadowColor;
          ctx.shadowBlur = o.shadowBlur || 0;
          ctx.shadowOffsetX = o.shadowX || 2;
          ctx.shadowOffsetY = o.shadowY || 2;
        }

        ctx.textAlign = 'left';
        ctx.textBaseline = 'top';
        ctx.fillText(o.content, ox, oy);
        
        // Reset shadow
        ctx.shadowColor = 'transparent';
      }
      ctx.restore();
    });
  }, [overlays]);

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
        drawVideoBackground(ctx, canvas, img);
        drawOverlays(ctx, canvas.width, canvas.height);
      };
      if (img.complete) render();
      else img.onload = render;
    } else {
      ctx.fillStyle = '#0a0a12';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      drawOverlays(ctx, canvas.width, canvas.height);
    }
  }, [selectedFrame, drawOverlays, drawVideoBackground]);

  useEffect(() => {
    drawFrame();
  }, [drawFrame, overlays]);

  const addText = () => {
    addOverlay({
      id: genId(),
      type: 'text',
      content: 'Seu texto aqui',
      x: 10,
      y: 10,
      width: 50,
      height: 10,
      opacity: 1,
      timeIn: 0,
      timeOut: 999,
      fontSize: 48,
      fontColor: '#FFFFFF',
      fontFamily: 'Montserrat',
      fontWeight: 'bold',
      fontStyle: 'normal',
      shadowColor: '#000000',
      shadowBlur: 4,
      shadowX: 2,
      shadowY: 2,
      bgColor: '',
      bgOpacity: 0.5,
      zIndex: overlays.length,
    });
  };

  const addWatermark = () => {
    addOverlay({
      id: genId(),
      type: 'watermark',
      content: '© Canal',
      x: 80,
      y: 90,
      width: 15,
      height: 5,
      opacity: 0.6,
      timeIn: 0,
      timeOut: 999,
      fontSize: 24,
      fontColor: '#FFFFFF',
      fontFamily: 'Inter',
      zIndex: overlays.length,
    });
  };

  const handleImageFile = async (file: File) => {
    const url = await new Promise<string>((resolve) => {
      const reader = new FileReader();
      reader.onload = (e) => resolve(e.target!.result as string);
      reader.readAsDataURL(file);
    });

    const name = prompt("Deseja salvar essa Logo na Galeria Permanente? Digite o nome (ou cancele para usar apenas neste projeto):");
    if (name) {
      try {
        await fetch('/api/overlays', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name, image_data: url })
        });
      } catch (err) {
        console.error('Failed to save overlay to DB', err);
      }
    }

    addOverlay({
      id: genId(),
      type: 'image',
      content: url,
      x: 10,
      y: 10,
      width: 25,
      height: 15,
      opacity: 1,
      timeIn: 0,
      timeOut: 999,
      zIndex: overlays.length,
    });
  };

  const loadGallery = async () => {
    try {
      const res = await fetch('/api/overlays');
      if (res.ok) {
        const data = await res.json();
        setGalleryItems(data);
      }
    } catch (err) {
      console.error(err);
    }
  };

  const openGallery = () => {
    setGalleryOpen(true);
    loadGallery();
  };

  const addFromGallery = (url: string) => {
    addOverlay({
      id: genId(),
      type: 'image',
      content: url,
      x: 10,
      y: 10,
      width: 25,
      height: 15,
      opacity: 1,
      timeIn: 0,
      timeOut: 999,
      zIndex: overlays.length,
    });
    setGalleryOpen(false);
  };

  const deleteFromGallery = async (id: string) => {
    if(!confirm("Certeza que deseja deletar da galeria?")) return;
    try {
      await fetch(`/api/overlays?id=${id}`, { method: 'DELETE' });
      loadGallery();
    } catch (err) {
      console.error(err);
    }
  };

  const activeOverlay = overlays.find(o => o.id === activeOverlayId) || overlays[overlays.length - 1];

  const duplicateOverlay = () => {
    if (!activeOverlay) return;
    const newId = genId();
    addOverlay({
      ...activeOverlay,
      id: newId,
      x: Math.min(90, activeOverlay.x + 5),
      y: Math.min(90, activeOverlay.y + 5),
      zIndex: overlays.length,
    });
    setActiveOverlayId(newId);
  };

  return (
    <div className="panel-content">
      <h2 style={{ fontFamily: 'Montserrat', fontWeight: 900, fontSize: 20, marginBottom: 6 }}>
        🖼️ Overlays & Marcas
      </h2>
      <p style={{ color: 'var(--text-muted)', marginBottom: 16, fontSize: 13 }}>
        Adicione logotipos, marcas d'água ou textos informativos ao vídeo.
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
            width={getOutputDimensions(outputFormat)[0]}
            height={getOutputDimensions(outputFormat)[1]}
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
      <div style={{ display: 'flex', gap: 10, marginBottom: 20, flexWrap: 'wrap' }}>
        <button className="btn btn-primary btn-sm" onClick={() => imgInputRef.current?.click()}>
          🖼️ Nova Logo
        </button>
        <button className="btn btn-primary btn-sm" onClick={openGallery} style={{ background: 'var(--success)' }}>
          📚 Abrir Galeria
        </button>
        <button className="btn btn-secondary btn-sm" onClick={addText}>
          📝 Texto
        </button>
        <button className="btn btn-secondary btn-sm" onClick={addWatermark}>
          ©️ Watermark
        </button>
        <input
          ref={imgInputRef}
          type="file"
          accept="image/*"
          style={{ display: 'none' }}
          onChange={(e) => e.target.files?.[0] && handleImageFile(e.target.files[0])}
        />
      </div>

      {overlays.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '32px 16px', color: 'var(--text-muted)', background: 'var(--bg-card)', borderRadius: 'var(--radius)', border: '1px solid var(--border)' }}>
          <div style={{ fontSize: 32, marginBottom: 8 }}>🖼️</div>
          <div style={{ fontSize: 13 }}>Nenhum elemento adicionado</div>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {/* List of layers */}
          <div style={{ display: 'flex', gap: 8, overflowX: 'auto', paddingBottom: 8 }}>
            {overlays.map((o) => (
              <div 
                key={o.id} 
                className={`overlay-chip ${o.id === activeOverlay?.id ? 'active' : ''}`}
                onClick={() => {
                  setActiveOverlayId(o.id);
                }}
                style={{
                  padding: '6px 12px',
                  background: o.id === activeOverlay?.id ? 'var(--primary)' : 'var(--bg-card)',
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
                <span>{o.type === 'image' ? '🖼️' : o.type === 'watermark' ? '©️' : '📝'}</span>
                <button 
                  onClick={(e) => { e.stopPropagation(); removeOverlay(o.id); }}
                  style={{ background: 'none', border: 'none', color: 'inherit', cursor: 'pointer', fontSize: 14, padding: 0 }}
                >
                  ×
                </button>
              </div>
            ))}
          </div>

          {activeOverlay && (
            <div className="card" style={{ padding: 16, background: 'rgba(255,255,255,0.02)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--primary)', textTransform: 'uppercase', letterSpacing: 1 }}>
                  Configurações do Elemento
                </div>
                <button
                  className="btn btn-sm btn-secondary"
                  onClick={duplicateOverlay}
                  style={{ padding: '2px 8px', fontSize: 11, background: 'rgba(255,255,255,0.05)', display: 'flex', alignItems: 'center', gap: 4 }}
                >
                  📋 Duplicar
                </button>
              </div>
              
              {activeOverlay.type !== 'image' && (
                <div className="form-group">
                  <div className="form-label">Conteúdo</div>
                  <input
                    className="form-control"
                    type="text"
                    value={activeOverlay.content}
                    onChange={(e) => updateOverlay(activeOverlay.id, { content: e.target.value })}
                  />
                </div>
              )}

              <div className="grid-2">
                <div className="form-group">
                  <div className="form-label">Posição X ({activeOverlay.x}%)</div>
                  <input type="range" min={0} max={100} value={activeOverlay.x} onChange={(e) => updateOverlay(activeOverlay.id, { x: Number(e.target.value) })} />
                </div>
                <div className="form-group">
                  <div className="form-label">Posição Y ({activeOverlay.y}%)</div>
                  <input type="range" min={0} max={100} value={activeOverlay.y} onChange={(e) => updateOverlay(activeOverlay.id, { y: Number(e.target.value) })} />
                </div>
              </div>

              <div className="grid-2">
                <div className="form-group">
                  <div className="form-label">Largura ({activeOverlay.width}%)</div>
                  <input type="range" min={1} max={100} value={activeOverlay.width} onChange={(e) => updateOverlay(activeOverlay.id, { width: Number(e.target.value) })} />
                </div>
                {activeOverlay.type === 'image' ? (
                  <div className="form-group">
                    <div className="form-label">Altura ({activeOverlay.height}%)</div>
                    <input type="range" min={1} max={100} value={activeOverlay.height} onChange={(e) => updateOverlay(activeOverlay.id, { height: Number(e.target.value) })} />
                  </div>
                ) : (
                  <div className="form-group">
                    <div className="form-label">Tamanho Fonte ({activeOverlay.fontSize})</div>
                    <input type="range" min={10} max={200} value={activeOverlay.fontSize} onChange={(e) => updateOverlay(activeOverlay.id, { fontSize: Number(e.target.value) })} />
                  </div>
                )}
              </div>

              <div className="form-group">
                <div className="form-label">Opacidade ({Math.round(activeOverlay.opacity * 100)}%)</div>
                <input type="range" min={0} max={1} step={0.01} value={activeOverlay.opacity} onChange={(e) => updateOverlay(activeOverlay.id, { opacity: Number(e.target.value) })} />
              </div>

              {activeOverlay.type !== 'image' && (
                <>
                  <div className="grid-2">
                    <div className="form-group">
                      <div className="form-label">Família da Fonte</div>
                      <select className="form-control" value={activeOverlay.fontFamily || 'Montserrat'} onChange={(e) => updateOverlay(activeOverlay.id, { fontFamily: e.target.value })}>
                        <option value="Montserrat">Montserrat</option>
                        <option value="Inter">Inter</option>
                        <option value="Roboto">Roboto</option>
                        <option value="Arial">Arial</option>
                        <option value="Bebas Neue">Bebas Neue</option>
                        <option value="Oswald">Oswald</option>
                        <option value="Titan One">Titan One</option>
                        <option value="Luckiest Guy">Luckiest Guy</option>
                        <option value="Fredoka One">Fredoka One</option>
                        <option value="Bangers">Bangers</option>
                      </select>
                    </div>
                    <div className="form-group">
                      <div className="form-label">Cor do Texto</div>
                      <input type="color" className="form-control" value={activeOverlay.fontColor || '#ffffff'} onChange={(e) => updateOverlay(activeOverlay.id, { fontColor: e.target.value })} style={{ padding: 2, height: 36 }} />
                    </div>
                  </div>
                  
                  <div className="grid-2">
                    <div className="form-group">
                      <div className="form-label">Peso (Negrito)</div>
                      <select className="form-control" value={activeOverlay.fontWeight || 'normal'} onChange={(e) => updateOverlay(activeOverlay.id, { fontWeight: e.target.value })}>
                        <option value="normal">Normal</option>
                        <option value="bold">Negrito (Bold)</option>
                        <option value="900">Black (900)</option>
                      </select>
                    </div>
                    <div className="form-group">
                      <div className="form-label">Estilo (Itálico)</div>
                      <select className="form-control" value={activeOverlay.fontStyle || 'normal'} onChange={(e) => updateOverlay(activeOverlay.id, { fontStyle: e.target.value })}>
                        <option value="normal">Normal</option>
                        <option value="italic">Itálico</option>
                      </select>
                    </div>
                  </div>

                  <div className="grid-2">
                    <div className="form-group">
                      <div className="form-label">Cor da Sombra</div>
                      <div style={{ display: 'flex', gap: 8 }}>
                        <input type="color" className="form-control" value={activeOverlay.shadowColor || '#000000'} onChange={(e) => updateOverlay(activeOverlay.id, { shadowColor: e.target.value })} style={{ padding: 2, height: 36, flex: 1 }} />
                        <button className="btn btn-secondary btn-sm" onClick={() => updateOverlay(activeOverlay.id, { shadowColor: '' })}>X</button>
                      </div>
                    </div>
                    <div className="form-group">
                      <div className="form-label">Cor de Fundo (Box)</div>
                      <div style={{ display: 'flex', gap: 8 }}>
                        <input type="color" className="form-control" value={activeOverlay.bgColor || '#000000'} onChange={(e) => updateOverlay(activeOverlay.id, { bgColor: e.target.value })} style={{ padding: 2, height: 36, flex: 1 }} />
                        <button className="btn btn-secondary btn-sm" onClick={() => updateOverlay(activeOverlay.id, { bgColor: '' })}>X</button>
                      </div>
                    </div>
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      )}

      {/* Gallery Modal */}
      {galleryOpen && (
        <div className="modal-backdrop" onClick={() => setGalleryOpen(false)}>
          <div className="modal-content" style={{ width: 600 }} onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h3>📚 Galeria de Logos no Banco de Dados</h3>
              <button className="close-btn" onClick={() => setGalleryOpen(false)}>×</button>
            </div>
            <div className="modal-body" style={{ display: 'flex', gap: 16, flexWrap: 'wrap', maxHeight: 400, overflowY: 'auto' }}>
              {galleryItems.length === 0 ? (
                <div style={{ padding: 20, color: 'var(--text-muted)' }}>Nenhuma logo salva no banco de dados ainda. Faça o upload de uma Nova Logo para salvá-la!</div>
              ) : (
                galleryItems.map(item => (
                  <div key={item.id} style={{ 
                    width: 150, 
                    background: 'var(--bg-card)', 
                    border: '1px solid var(--border)', 
                    borderRadius: 8, 
                    overflow: 'hidden',
                    display: 'flex',
                    flexDirection: 'column'
                  }}>
                    <div style={{ height: 100, background: '#000', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                      <img src={item.image_data} alt={item.name} style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'contain' }} />
                    </div>
                    <div style={{ padding: 8, fontSize: 12, textAlign: 'center', fontWeight: 'bold' }}>
                      {item.name}
                    </div>
                    <div style={{ display: 'flex' }}>
                      <button className="btn btn-primary btn-sm" style={{ flex: 1, borderRadius: 0, padding: 4 }} onClick={() => addFromGallery(item.image_data)}>Usar</button>
                      <button className="btn btn-danger btn-sm" style={{ borderRadius: 0, padding: 4 }} onClick={() => deleteFromGallery(item.id)}>🗑️</button>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

