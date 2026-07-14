import { useEffect, useRef, useState, useCallback } from 'react';
import { useProjectStore, getOutputDimensions } from '../store/projectStore';
import type { SubtitleStyle } from '../store/projectStore';
import type { SrtEntry } from '../types';
import { secondsToTimestamp, regroupSrtEntries } from '../utils/srtParser';

function Toggle({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="toggle">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span className="toggle-slider" />
    </label>
  );
}

const FONTS = [
  'Montserrat', 'Inter', 'Roboto', 'Arial', 'Impact',
  'Open Sans', 'Oswald', 'Raleway', 'Bebas Neue', 'Nunito',
  'Poppins', 'Lato', 'Rubik', 'Comic Sans MS', 'Courier New',
  'Fredoka One', 'Bangers', 'Pacifico', 'Righteous', 'Carter One',
  'Titan One', 'Luckiest Guy'
];

const ALIGNMENTS = [
  { value: 7, label: '↖' }, { value: 8, label: '↑' }, { value: 9, label: '↗' },
  { value: 4, label: '←' }, { value: 5, label: '·' }, { value: 6, label: '→' },
  { value: 1, label: '↙' }, { value: 2, label: '↓' }, { value: 3, label: '↘' },
];

const SUBTITLE_PRESETS = [
  { id: 'anime_dub', label: 'Anime Dub', values: { font: 'Montserrat', size: 58, color: '#FFFFFF', outlineColor: '#000000', outlineWidth: 3, bold: true, glow: false, bgBox: false, positionY: 88 } },
  { id: 'drama', label: 'Drama', values: { font: 'Open Sans', size: 46, color: '#FFEE99', outlineColor: '#000000', outlineWidth: 2, bold: false, glow: false, bgBox: true, bgBoxColor: '#000000', bgBoxOpacity: 0.65, positionY: 90 } },
  { id: 'neon', label: 'Neon', values: { font: 'Bebas Neue', size: 64, color: '#00FFF0', outlineColor: '#003333', outlineWidth: 1, bold: false, glow: true, glowColor: '#00FFF0', glowBlur: 18, positionY: 85 } },
  { id: 'minimal', label: 'Minimal', values: { font: 'Inter', size: 44, color: '#FFFFFF', outlineColor: 'transparent', outlineWidth: 0, bold: false, glow: false, bgBox: false, positionY: 92 } },
  { id: 'fire', label: 'Fire', values: { font: 'Impact', size: 62, color: '#FF6B00', outlineColor: '#FF0000', outlineWidth: 2.5, bold: false, glow: true, glowColor: '#FF4400', glowBlur: 14, positionY: 85 } },
];

// Draw subtitle text on canvas
function drawSubtitles(
  ctx: CanvasRenderingContext2D,
  entries: SrtEntry[],
  currentTime: number,
  style: SubtitleStyle,
  canvasW: number,
  canvasH: number,
  opacity = 1
) {
  const active = entries.filter(
    (e) => e.startTime <= currentTime && e.endTime >= currentTime
  );
  if (active.length === 0) return;

  const x = (style.positionX / 100) * canvasW;
  const y = (style.positionY / 100) * canvasH;
  const fontSize = Math.round((style.size / 1920) * canvasH);

  ctx.save();
  ctx.globalAlpha = opacity;
  ctx.font = `${style.bold ? 'bold ' : ''}${style.italic ? 'italic ' : ''}${fontSize}px ${style.font}, sans-serif`;

  const alignment = style.alignment || 2;

  // Horizontal alignment
  let textAlign: CanvasTextAlign = 'center';
  if ([1, 4, 7].includes(alignment)) {
    textAlign = 'left';
  } else if ([3, 6, 9].includes(alignment)) {
    textAlign = 'right';
  } else {
    textAlign = 'center';
  }
  ctx.textAlign = textAlign;

  // Vertical baseline
  let textBaseline: CanvasTextBaseline = 'bottom';
  if ([7, 8, 9].includes(alignment)) {
    textBaseline = 'top';
  } else if ([4, 5, 6].includes(alignment)) {
    textBaseline = 'middle';
  } else {
    textBaseline = 'bottom';
  }
  ctx.textBaseline = textBaseline;

  const lineH = fontSize * 1.25;
  let startY = 0;
  if ([7, 8, 9].includes(alignment)) {
    startY = y;
  } else if ([4, 5, 6].includes(alignment)) {
    startY = y - (active.length * lineH) / 2;
  } else {
    startY = y - active.length * lineH;
  }

  active.forEach((entry, i) => {
    const text = style.allCaps ? entry.text.toUpperCase() : entry.text;
    
    let ly = 0;
    if ([7, 8, 9].includes(alignment)) {
      ly = startY + i * lineH;
    } else if ([4, 5, 6].includes(alignment)) {
      ly = startY + (i + 0.5) * lineH;
    } else {
      ly = startY + (i + 1) * lineH;
    }

    // Background box
    if (style.bgBox) {
      const metrics = ctx.measureText(text);
      const pad = 12;
      ctx.globalAlpha = opacity * style.bgBoxOpacity;
      ctx.fillStyle = style.bgBoxColor;
      ctx.beginPath();
      const bx = x - metrics.width / 2 - pad;
      const by = ly - fontSize - 4;
      const bw = metrics.width + pad * 2;
      const bh = fontSize + 12;
      const r = style.bgBoxRadius;
      ctx.moveTo(bx + r, by);
      ctx.lineTo(bx + bw - r, by);
      ctx.quadraticCurveTo(bx + bw, by, bx + bw, by + r);
      ctx.lineTo(bx + bw, by + bh - r);
      ctx.quadraticCurveTo(bx + bw, by + bh, bx + bw - r, by + bh);
      ctx.lineTo(bx + r, by + bh);
      ctx.quadraticCurveTo(bx, by + bh, bx, by + bh - r);
      ctx.lineTo(bx, by + r);
      ctx.quadraticCurveTo(bx, by, bx + r, by);
      ctx.closePath();
      ctx.fill();
      ctx.globalAlpha = opacity;
    }

    const drawTextWithGlow = (t: string, tx: number, wordAlpha: number, animY: number, animScale: number) => {
      ctx.save();
      ctx.globalAlpha = wordAlpha;
      
      if (animScale !== 1) {
        ctx.translate(tx, animY);
        ctx.scale(animScale, animScale);
        ctx.translate(-tx, -animY);
      }

      // Glow and Outline
      const hasOutline = style.outlineWidth > 0;
      if (hasOutline || style.glow) {
        ctx.lineJoin = 'round';
        ctx.miterLimit = 2;
        
        const intensity = style.glow ? Math.min(style.glowIntensity || 1, 10) : 1;
        for (let j = 0; j < intensity; j++) {
          if (style.glow) {
            ctx.shadowColor = style.glowColor;
            ctx.shadowBlur = style.glowBlur;
          } else {
            ctx.shadowBlur = 0;
          }
          
          if (hasOutline) {
            ctx.strokeStyle = style.outlineColor;
            ctx.lineWidth = style.outlineWidth * 2;
            ctx.strokeText(t, tx, animY);
          } else if (style.glow) {
            ctx.fillStyle = style.glowColor;
            ctx.fillText(t, tx, animY);
          }
        }
      }

      // Fill
      ctx.shadowBlur = 0;
      ctx.fillStyle = style.color;
      ctx.fillText(t, tx, animY);
      ctx.restore();
    };

    if (entry.words && entry.words.length > 0) {
      const totalWidth = ctx.measureText(text).width;
      let currentX = x - totalWidth / 2;
      if ([1, 4, 7].includes(alignment)) {
        currentX = x;
      } else if ([3, 6, 9].includes(alignment)) {
        currentX = x - totalWidth;
      } else {
        currentX = x - totalWidth / 2;
      }
      ctx.textAlign = 'left';
      
      entry.words.forEach((w, idx) => {
         const wText = style.allCaps ? w.word.toUpperCase() : w.word;
         const wordWidth = ctx.measureText(wText).width;
         const spaceWidth = idx < entry.words.length - 1 ? ctx.measureText(' ').width : 0;
         
         const durationMsBlock = (entry.endTime - entry.startTime) * 1000;
         const maxFadeIn = durationMsBlock * ((style.fadeInLimitPct ?? 100) / 100);
         const maxFadeOut = durationMsBlock * ((style.fadeOutLimitPct ?? 100) / 100);
         const effectiveFadeIn = Math.min(style.fadeIn, maxFadeIn);
         const effectiveFadeOut = Math.min(style.fadeOut, maxFadeOut);

         const t_w = Math.max(10, effectiveFadeIn / 2); // Each word takes half the total fade time
         const delay = entry.words.length > 1 ? idx * ((effectiveFadeIn - t_w) / (entry.words.length - 1)) : 0;
         
         const elapsedBlock = (currentTime - entry.startTime) * 1000;
         
         let wordAlpha = 0;
         let animY = ly;
         let animScale = 1;

         // Entrance cascade
         if (elapsedBlock > delay) {
            const p = Math.min(1, (elapsedBlock - delay) / t_w);
            wordAlpha = p; // Soft fade in

            if (style.animation === 'slide-up') {
               animY += (1 - p) * 20;
            } else if (style.animation === 'bounce') {
               animScale = p < 1 ? 0.8 + Math.sin(p * Math.PI) * 0.4 : 1;
            } else if (style.animation === 'zoom-in') {
               animScale = 0.5 + p * 0.5;
            }
         }

         // Block fade out
         const timeUntilEnd = (entry.endTime - currentTime) * 1000;
         if (timeUntilEnd < effectiveFadeOut && timeUntilEnd >= 0 && effectiveFadeOut > 0) {
            const fadeOutP = timeUntilEnd / effectiveFadeOut;
            wordAlpha *= fadeOutP;
         } else if (timeUntilEnd < 0) {
            wordAlpha = 0;
         }
         
         drawTextWithGlow(wText, currentX, wordAlpha, animY, animScale);
         currentX += wordWidth + spaceWidth;
      });
      ctx.textAlign = 'center'; // reset
    } else {
      drawTextWithGlow(text, x, 1, ly, 1);
    }
  });

  ctx.restore();
}

export function SubtitleEditor() {
  const {
    subtitleStyle, setSubtitleStyle,
    srtEntries, srtPreviewStartTime, setSrtPreviewStartTime, setSrtEntries,
    extractedFrames, selectedFrameId, outputFormat, overlays,
    blurBand, cropZoom, staticCrop, videoPosition, videoEdit, colorGrade, background, videoInfo
  } = useProjectStore();

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const animRef = useRef<number>(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [playTime, setPlayTime] = useState(0);
  const playStartRef = useRef(0);
  const playOffsetRef = useRef(0);
  const PREVIEW_DURATION = 12;

  const selectedFrame = extractedFrames.find((f) => f.id === selectedFrameId);

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

  // Draw frame onto canvas
  const drawFrame = useCallback((time: number) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const currentSrtTime = srtPreviewStartTime + time;

    // Draw background frame
    if (selectedFrame) {
      const img = new Image();
      img.src = selectedFrame.dataUrl;
      // Draw synchronously if already loaded (cached)
      if (img.complete) {
        drawVideoBackground(ctx, canvas, img);
        drawSubtitles(ctx, srtEntries, currentSrtTime, subtitleStyle, canvas.width, canvas.height);
      } else {
        ctx.fillStyle = '#0a0a12';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        img.onload = () => {
          ctx.clearRect(0, 0, canvas.width, canvas.height);
          drawVideoBackground(ctx, canvas, img);
          drawSubtitles(ctx, srtEntries, currentSrtTime, subtitleStyle, canvas.width, canvas.height);
        };
      }
    } else {
      ctx.fillStyle = '#0a0a12';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = 'rgba(255,255,255,0.1)';
      ctx.font = '16px Inter';
      ctx.textAlign = 'center';
      ctx.fillText('Selecione um frame no painel Upload', canvas.width / 2, canvas.height / 2);
      drawSubtitles(ctx, srtEntries, currentSrtTime, subtitleStyle, canvas.width, canvas.height);
    }
  }, [selectedFrame, srtEntries, srtPreviewStartTime, subtitleStyle, drawVideoBackground]);

  // Preload image and redraw on changes
  useEffect(() => {
    if (!selectedFrame || !canvasRef.current) return;
    const img = new Image();
    img.src = selectedFrame.dataUrl;
    img.onload = () => drawFrame(playTime);
  }, [selectedFrame, subtitleStyle, drawFrame, playTime]);

  // Playback loop
  useEffect(() => {
    if (!isPlaying) {
      cancelAnimationFrame(animRef.current);
      return;
    }

    playStartRef.current = performance.now();
    const img = selectedFrame ? Object.assign(new Image(), { src: selectedFrame.dataUrl }) : null;
    
    // Pre-load overlay images
    const overlayImages: Record<string, HTMLImageElement> = {};
    overlays.forEach(ov => {
      if (ov.type === 'image' || ov.type === 'watermark') {
        const oImg = new Image();
        oImg.src = ov.content;
        overlayImages[ov.id] = oImg;
      }
    });

    const loop = () => {
      const elapsed = (performance.now() - playStartRef.current) / 1000 + playOffsetRef.current;
      const t = Math.min(elapsed, PREVIEW_DURATION);
      setPlayTime(t);

      const canvas = canvasRef.current;
      if (canvas) {
        const ctx = canvas.getContext('2d')!;
        ctx.imageSmoothingEnabled = true;
        ctx.imageSmoothingQuality = 'high';
        ctx.clearRect(0, 0, canvas.width, canvas.height);

        if (img && img.complete) {
          drawVideoBackground(ctx, canvas, img);
        } else {
          ctx.fillStyle = '#0a0a12';
          ctx.fillRect(0, 0, canvas.width, canvas.height);
        }

        // Draw Overlays
        const currentTime = srtPreviewStartTime + t;
        overlays.forEach(ov => {
          // Time filter
          if (ov.timeIn !== 0 || ov.timeOut !== 0) {
            if (currentTime < ov.timeIn || currentTime > ov.timeOut) return;
          }
          
          ctx.save();
          ctx.globalAlpha = ov.opacity;
          const ox = (ov.x / 100) * canvas.width;
          const oy = (ov.y / 100) * canvas.height;
          const ow = (ov.width / 100) * canvas.width;
          const oh = (ov.height / 100) * canvas.height;

          if (ov.type === 'image' || ov.type === 'watermark') {
            const oImg = overlayImages[ov.id];
            if (oImg && oImg.complete) {
              ctx.drawImage(oImg, ox, oy, ow, oh);
            }
          } else if (ov.type === 'text') {
            ctx.fillStyle = ov.fontColor || '#ffffff';
            const fSize = (ov.fontSize || 32) * (canvas.height / 1080);
            ctx.font = `${fSize}px ${ov.fontFamily || 'Montserrat'}, sans-serif`;
            ctx.fillText(ov.content, ox, oy + fSize);
          }
          ctx.restore();
        });

        drawSubtitles(ctx, srtEntries, currentTime, subtitleStyle, canvas.width, canvas.height);
      }

      if (t < PREVIEW_DURATION) {
        animRef.current = requestAnimationFrame(loop);
      } else {
        setIsPlaying(false);
        playOffsetRef.current = 0;
        setPlayTime(0);
      }
    };

    animRef.current = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(animRef.current);
  }, [isPlaying, srtEntries, srtPreviewStartTime, subtitleStyle, selectedFrame, drawVideoBackground, overlays, drawFrame]);

  const handlePlay = () => {
    playOffsetRef.current = 0;
    setPlayTime(0);
    setIsPlaying(true);
  };

  const handleStop = () => {
    setIsPlaying(false);
    playOffsetRef.current = 0;
    setPlayTime(0);
    drawFrame(0);
  };

  const applyPreset = (preset: typeof SUBTITLE_PRESETS[0]) => {
    setSubtitleStyle({ ...preset.values as Partial<SubtitleStyle>, preset: preset.id });
  };

  const s = subtitleStyle;
  const set = (v: Partial<SubtitleStyle>) => setSubtitleStyle({ ...v, preset: 'custom' });

  const handleRegroup = () => {
    const newEntries = regroupSrtEntries(srtEntries, s.wordsPerBlock);
    setSrtEntries(newEntries);
  };

  return (
    <div className="panel-content">
      <h2 style={{ fontFamily: 'Montserrat', fontWeight: 900, fontSize: 20, marginBottom: 6 }}>
        📝 Editor de Legendas
      </h2>
      <p style={{ color: 'var(--text-muted)', marginBottom: 16, fontSize: 13 }}>
        Configure estilo, posição e efeitos. Use o preview para simular as legendas sobre o frame selecionado.
      </p>

      {/* Preview Canvas */}
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'center' }}>
        <div
          style={{
            position: 'relative',
            background: '#000',
            borderRadius: 'var(--radius-lg)',
            overflow: 'hidden',
            border: '1px solid var(--border)',
            display: 'flex',
            justifyContent: 'center',
            alignItems: 'center',
            maxWidth: '100%',
          }}
        >
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

          {/* Play controls overlay */}
          <div style={{
            position: 'absolute',
            bottom: 0,
            left: 0,
            right: 0,
            padding: '8px 12px',
            background: 'linear-gradient(transparent, rgba(0,0,0,0.8))',
            display: 'flex',
            alignItems: 'center',
            gap: 8,
          }}>
            <button
              className={`btn btn-sm ${isPlaying ? 'btn-danger' : 'btn-primary'}`}
              onClick={isPlaying ? handleStop : handlePlay}
            >
              {isPlaying ? '⏹ Stop' : '▶ Play Preview'}
            </button>
            {isPlaying && (
              <div style={{ flex: 1 }}>
                <div className="progress-bar">
                  <div className="progress-fill" style={{ width: `${(playTime / PREVIEW_DURATION) * 100}%` }} />
                </div>
              </div>
            )}
            <span style={{ fontSize: 11, color: 'rgba(255,255,255,0.5)', fontFamily: 'JetBrains Mono' }}>
              +{PREVIEW_DURATION}s
            </span>
          </div>
        </div>

        {/* SRT time selector */}
        {srtEntries.length > 0 && (
          <div style={{ marginTop: 10 }}>
            <div className="form-label">
              <span>Início do Preview no SRT</span>
              <span className="form-label-value">{secondsToTimestamp(srtPreviewStartTime, false)}</span>
            </div>
            <input
              type="range"
              min={0}
              max={srtEntries[srtEntries.length - 1]?.endTime ?? 0}
              step={0.1}
              value={srtPreviewStartTime}
              onChange={(e) => {
                setSrtPreviewStartTime(Number(e.target.value));
                setIsPlaying(false);
                setPlayTime(0);
              }}
            />
          </div>
        )}
      </div>

      {/* Presets */}
      <div className="form-group">
        <div className="form-label">Presets de Legenda</div>
        <div className="tag-row">
          {SUBTITLE_PRESETS.map((p) => (
            <span
              key={p.id}
              className={`tag ${s.preset === p.id ? 'active' : ''}`}
              onClick={() => applyPreset(p)}
            >
              {p.label}
            </span>
          ))}
        </div>
      </div>

      <div className="divider" />

      {/* Font */}
      <div className="grid-2">
        <div className="form-group">
          <div className="form-label">Fonte</div>
          <select value={s.font} onChange={(e) => set({ font: e.target.value })} style={{ fontFamily: s.font }}>
            {FONTS.map((f) => <option key={f} value={f} style={{ fontFamily: f }}>{f}</option>)}
          </select>
        </div>
        <div className="form-group">
          <div className="form-label">
            <span>Tamanho</span>
            <span className="form-label-value">{s.size}px</span>
          </div>
          <input type="range" min={20} max={120} step={2} value={s.size} onChange={(e) => set({ size: Number(e.target.value) })} />
        </div>
      </div>

      {/* Style toggles */}
      <div className="grid-3" style={{ marginBottom: 14 }}>
        {[
          { label: 'Bold', key: 'bold' as keyof SubtitleStyle },
          { label: 'Italic', key: 'italic' as keyof SubtitleStyle },
          { label: 'CAPS', key: 'allCaps' as keyof SubtitleStyle },
        ].map(({ label, key }) => (
          <div key={key} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4, padding: '8px', background: 'var(--bg-card)', borderRadius: 'var(--radius-sm)', border: `1px solid ${s[key] ? 'var(--accent)' : 'var(--border)'}`, cursor: 'pointer' }}
            onClick={() => setSubtitleStyle({ [key]: !s[key], preset: 'custom' })}>
            <span style={{ fontSize: 12, fontWeight: 700, color: s[key] ? 'var(--accent-light)' : 'var(--text-muted)' }}>{label}</span>
          </div>
        ))}
      </div>

      {/* Colors */}
      <div className="grid-2">
        <div className="form-group">
          <div className="form-label">Cor do Texto</div>
          <div className="color-row">
            <input type="text" value={s.color} onChange={(e) => set({ color: e.target.value })} />
            <input type="color" value={s.color} onChange={(e) => set({ color: e.target.value })} />
          </div>
        </div>
        <div className="form-group">
          <div className="form-label">Contorno</div>
          <div className="color-row">
            <input type="text" value={s.outlineColor} onChange={(e) => set({ outlineColor: e.target.value })} />
            <input type="color" value={s.outlineColor} onChange={(e) => set({ outlineColor: e.target.value })} />
          </div>
        </div>
      </div>

      <div className="form-group">
        <div className="form-label">
          <span>Espessura do Contorno</span>
          <span className="form-label-value">{s.outlineWidth}px</span>
        </div>
        <input type="range" min={0} max={8} step={0.5} value={s.outlineWidth} onChange={(e) => set({ outlineWidth: Number(e.target.value) })} />
      </div>

      {/* Animations */}
      <div className="form-group">
        <div className="form-label">Efeito de Animação</div>
        <div className="segmented">
          {[
            { id: 'none', label: 'Nenhum' },
            { id: 'fade', label: 'Fade' },
            { id: 'slide-up', label: 'Slide Up' },
            { id: 'bounce', label: 'Bounce' },
            { id: 'zoom-in', label: 'Zoom In' },
          ].map((a) => (
            <button
              key={a.id}
              className={s.animation === a.id ? 'active' : ''}
              onClick={() => set({ animation: a.id as any })}
            >
              {a.label}
            </button>
          ))}
        </div>
      </div>

      <div className="divider" />

      {/* Glow */}
      <div className="toggle-row" style={{ marginBottom: 10 }}>
        <span className="toggle-label">✨ Glow</span>
        <Toggle checked={s.glow} onChange={(v) => setSubtitleStyle({ glow: v })} />
      </div>
      {s.glow && (
        <div className="grid-2">
          <div className="form-group">
            <div className="form-label">Cor do Glow</div>
            <div className="color-row">
              <input type="text" value={s.glowColor} onChange={(e) => set({ glowColor: e.target.value })} />
              <input type="color" value={s.glowColor} onChange={(e) => set({ glowColor: e.target.value })} />
            </div>
          </div>
          <div className="form-group">
            <div className="form-label">
              <span>Blur do Glow</span>
              <span className="form-label-value">{s.glowBlur}px</span>
            </div>
            <input type="range" min={2} max={40} step={1} value={s.glowBlur} onChange={(e) => set({ glowBlur: Number(e.target.value) })} />
          </div>
          <div className="form-group">
            <div className="form-label">
              <span>Intensidade do Glow</span>
              <span className="form-label-value">{s.glowIntensity ?? 1}x</span>
            </div>
            <input type="range" min={1} max={10} step={1} value={s.glowIntensity ?? 1} onChange={(e) => set({ glowIntensity: Number(e.target.value) })} />
          </div>
        </div>
      )}

      {/* Bg Box */}
      <div className="toggle-row" style={{ marginBottom: 10 }}>
        <span className="toggle-label">◻ Caixa de Fundo</span>
        <Toggle checked={s.bgBox} onChange={(v) => setSubtitleStyle({ bgBox: v })} />
      </div>
      {s.bgBox && (
        <>
          <div className="grid-2">
            <div className="form-group">
              <div className="form-label">Cor da Caixa</div>
              <div className="color-row">
                <input type="text" value={s.bgBoxColor} onChange={(e) => set({ bgBoxColor: e.target.value })} />
                <input type="color" value={s.bgBoxColor} onChange={(e) => set({ bgBoxColor: e.target.value })} />
              </div>
            </div>
            <div className="form-group">
              <div className="form-label">
                <span>Opacidade</span>
                <span className="form-label-value">{Math.round(s.bgBoxOpacity * 100)}%</span>
              </div>
              <input type="range" min={0} max={1} step={0.05} value={s.bgBoxOpacity} onChange={(e) => set({ bgBoxOpacity: Number(e.target.value) })} />
            </div>
          </div>
          <div className="form-group">
            <div className="form-label">
              <span>Arredondamento</span>
              <span className="form-label-value">{s.bgBoxRadius}px</span>
            </div>
            <input type="range" min={0} max={40} step={2} value={s.bgBoxRadius} onChange={(e) => set({ bgBoxRadius: Number(e.target.value) })} />
          </div>
        </>
      )}

      <div className="divider" />

      {/* Position */}
      <div className="form-label" style={{ marginBottom: 8 }}>Posição & Alinhamento</div>
      <div className="grid-2">
        <div className="form-group">
          <div className="form-label">
            <span>Horizontal</span>
            <span className="form-label-value">{s.positionX}%</span>
          </div>
          <input type="range" min={0} max={100} step={1} value={s.positionX} onChange={(e) => set({ positionX: Number(e.target.value) })} />
        </div>
        <div className="form-group">
          <div className="form-label">
            <span>Vertical</span>
            <span className="form-label-value">{s.positionY}%</span>
          </div>
          <input type="range" min={0} max={100} step={1} value={s.positionY} onChange={(e) => set({ positionY: Number(e.target.value) })} />
        </div>
      </div>

      {/* ASS Alignment grid */}
      <div className="form-group">
        <div className="form-label">Alinhamento ASS</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 4, maxWidth: 120 }}>
          {ALIGNMENTS.map((a) => (
            <button
              key={a.value}
              onClick={() => set({ alignment: a.value })}
              style={{
                padding: '6px',
                border: `1px solid ${s.alignment === a.value ? 'var(--accent)' : 'var(--border)'}`,
                background: s.alignment === a.value ? 'var(--accent-dim)' : 'var(--bg-card)',
                borderRadius: 4,
                color: s.alignment === a.value ? 'var(--accent-light)' : 'var(--text-muted)',
                cursor: 'pointer',
                fontSize: 14,
                fontFamily: 'inherit',
              }}
            >
              {a.label}
            </button>
          ))}
        </div>
      </div>

      <div className="divider" />

      {/* Fade & words */}
      <div className="grid-2">
        <div className="form-group">
          <div className="form-label">
            <span>Fade In Máx</span>
            <span className="form-label-value">{s.fadeIn}ms</span>
          </div>
          <input type="range" min={0} max={500} step={10} value={s.fadeIn} onChange={(e) => set({ fadeIn: Number(e.target.value) })} />
        </div>
        <div className="form-group">
          <div className="form-label">
            <span>Limite Fade In (%)</span>
            <span className="form-label-value">{s.fadeInLimitPct ?? 20}%</span>
          </div>
          <input type="range" min={5} max={100} step={5} value={s.fadeInLimitPct ?? 20} onChange={(e) => set({ fadeInLimitPct: Number(e.target.value) })} />
        </div>
      </div>

      <div className="grid-2">
        <div className="form-group">
          <div className="form-label">
            <span>Fade Out Máx</span>
            <span className="form-label-value">{s.fadeOut}ms</span>
          </div>
          <input type="range" min={0} max={500} step={10} value={s.fadeOut} onChange={(e) => set({ fadeOut: Number(e.target.value) })} />
        </div>
        <div className="form-group">
          <div className="form-label">
            <span>Limite Fade Out (%)</span>
            <span className="form-label-value">{s.fadeOutLimitPct ?? 15}%</span>
          </div>
          <input type="range" min={5} max={100} step={5} value={s.fadeOutLimitPct ?? 15} onChange={(e) => set({ fadeOutLimitPct: Number(e.target.value) })} />
        </div>
      </div>

      <div className="grid-2">
        <div className="form-group">
          <div className="form-label" style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span>Palavras/bloco</span>
            <button className="btn btn-sm" onClick={handleRegroup} style={{ padding: '2px 8px', fontSize: 10 }}>
              ↻ Reagrupar
            </button>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <input style={{ flex: 1 }} type="range" min={1} max={10} step={1} value={s.wordsPerBlock} onChange={(e) => set({ wordsPerBlock: Number(e.target.value) })} />
            <span className="form-label-value" style={{ minWidth: 20, textAlign: 'right' }}>{s.wordsPerBlock}</span>
          </div>
        </div>
        <div className="form-group">
          <div className="form-label">
            <span>Linhas/bloco</span>
            <span className="form-label-value">{s.linesPerBlock}</span>
          </div>
          <input type="range" min={1} max={4} step={1} value={s.linesPerBlock} onChange={(e) => set({ linesPerBlock: Number(e.target.value) })} />
        </div>
      </div>

      {/* SRT List */}
      {srtEntries.length > 0 && (
        <>
          <div className="divider" />
          <div className="form-label" style={{ marginBottom: 8 }}>
            Entradas SRT ({srtEntries.length})
          </div>
          <div className="srt-timeline">
            {srtEntries.slice(0, 50).map((entry) => {
              const isActive = entry.startTime >= srtPreviewStartTime && entry.startTime <= srtPreviewStartTime + 12;
              return (
                <div
                  key={entry.id}
                  className={`srt-entry ${isActive ? 'active' : ''}`}
                  onClick={() => { setSrtPreviewStartTime(entry.startTime); setIsPlaying(false); setPlayTime(0); }}
                >
                  <span className="srt-time">{secondsToTimestamp(entry.startTime, false).slice(3, 11)}</span>
                  <span className="srt-text">{entry.text}</span>
                </div>
              );
            })}
            {srtEntries.length > 50 && (
              <div style={{ padding: '6px 10px', color: 'var(--text-muted)', fontSize: 11 }}>
                + {srtEntries.length - 50} mais entradas...
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

