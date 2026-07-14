import type { SrtEntry } from '../types';
import type { SubtitleStyle, ColorGradeConfig, BlurBandConfig, CropZoomConfig } from '../store/projectStore';


function colorToStyleHeader(hex: string, alpha = 0): string {
  const r = hex.slice(1, 3);
  const g = hex.slice(3, 5);
  const b = hex.slice(5, 7);
  const a = Math.round(alpha * 255).toString(16).toUpperCase().padStart(2, '0');
  return `&H${a}${b}${g}${r}`;
}

function colorToTag(hex: string): string {
  const r = hex.slice(1, 3);
  const g = hex.slice(3, 5);
  const b = hex.slice(5, 7);
  return `&H${b}${g}${r}&`;
}

function alphaToTag(opacity: number): string {
  const a = Math.round((1 - Math.min(1, Math.max(0, opacity))) * 255).toString(16).toUpperCase().padStart(2, '0');
  return `&H${a}&`;
}

function assTime(secs: number): string {
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = Math.floor(secs % 60);
  const cs = Math.round((secs % 1) * 100);
  return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}.${String(cs).padStart(2, '0')}`;
}

export function exportToAss(
  entries: SrtEntry[],
  style: SubtitleStyle,
  videoWidth = 1080,
  videoHeight = 1920
): string {
  const primaryStyle = colorToStyleHeader(style.color);
  const outlineStyle = colorToStyleHeader(style.outlineColor);
  const backStyle = style.bgBox ? colorToStyleHeader(style.bgBoxColor, 1 - style.bgBoxOpacity) : '&HFFFFFFFF';

  const bold = style.bold ? '-1' : '0';
  const italic = style.italic ? '-1' : '0';

  const marginV = Math.round(videoHeight * (1 - style.positionY / 100));
  const marginH = Math.round(videoWidth * (style.positionX / 100 - 0.5));

  // SubtitleEditor computes font size relative to a 1920 height canvas.
  // We must scale it to the actual videoHeight (PlayResY) so it matches the preview size perfectly.
  const assFontSize = Math.round((style.size / 1920) * videoHeight);

  const header = `[Script Info]
ScriptType: v4.00+
PlayResX: ${videoWidth}
PlayResY: ${videoHeight}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,${style.font},${assFontSize},${primaryStyle},${primaryStyle},${outlineStyle},${backStyle},${bold},${italic},0,0,100,100,0,0,1,${style.outlineWidth},${style.shadowOffset},5,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text`;

  const pTag = colorToTag(style.color);
  const oTag = colorToTag(style.outlineColor);
  const gTag = colorToTag(style.glowColor);
  
  // Adjusted glow tone: The Canvas mixes shadowBlur with intensity. 
  // For ASS, we apply transparency directly.
  const gAlpha = alphaToTag(style.glowIntensity / 10);

  // Temporary canvas to measure text widths accurately per word
  const canvas = document.createElement('canvas');
  const ctx = canvas.getContext('2d');
  if (ctx) {
    // Measure using the exact same scaled font size that will be drawn by the ASS player
    ctx.font = `${style.bold ? 'bold ' : ''}${style.italic ? 'italic ' : ''}${assFontSize}px "${style.font}", sans-serif`;
  }

  const assLines: string[] = [];

  entries.forEach((e) => {
    const fullText = style.allCaps ? e.text.toUpperCase() : e.text;
    const words = e.words || [];
    const baseY = Math.round(videoHeight - marginV);
    const centerX = Math.round(videoWidth / 2 + marginH);

    const durationMs = (e.endTime - e.startTime) * 1000;
    const maxFadeIn = durationMs * ((style.fadeInLimitPct ?? 100) / 100);
    const maxFadeOut = durationMs * ((style.fadeOutLimitPct ?? 100) / 100);
    const effFadeIn = Math.round(Math.min(style.fadeIn, maxFadeIn));
    const effFadeOut = Math.round(Math.min(style.fadeOut, maxFadeOut));

    const alignment = style.alignment || 2;

    if (words.length > 0 && ctx) {
      // Calculate total width of the line to position it properly
      const wordWidths = words.map(w => {
        const text = style.allCaps ? w.word.toUpperCase() : w.word;
        return ctx.measureText(text).width;
      });
      const spaceWidth = ctx.measureText(' ').width;
      
      const totalWidth = wordWidths.reduce((acc, val, i) => acc + val + (i < words.length - 1 ? spaceWidth : 0), 0);
      
      let currentX = centerX - totalWidth / 2;
      if ([1, 4, 7].includes(alignment)) {
        currentX = centerX;
      } else if ([3, 6, 9].includes(alignment)) {
        currentX = centerX - totalWidth;
      } else {
        currentX = centerX - totalWidth / 2;
      }

      let wordAnTag = '\\an2';
      if ([7, 8, 9].includes(alignment)) {
        wordAnTag = '\\an8';
      } else if ([4, 5, 6].includes(alignment)) {
        wordAnTag = '\\an5';
      } else {
        wordAnTag = '\\an2';
      }

      words.forEach((w, idx) => {
        const wText = style.allCaps ? w.word.toUpperCase() : w.word;
        const wWidth = wordWidths[idx];
        
        // The pivot for animations should be the center of the word
        const wordCenterX = Math.round(currentX + wWidth / 2);
        
        // Base positioning for this specific word
        const posTag = `\\pos(${wordCenterX},${baseY})`;
        
        const durationMsBlock = Math.round((e.endTime - e.startTime) * 1000);
        const t_w = Math.max(10, Math.round(effFadeIn / 2));
        const delay = words.length > 1 ? idx * ((effFadeIn - t_w) / (words.length - 1)) : 0;
        const startFade = Math.round(delay);
        const endFade = Math.round(delay + t_w);
        const fadeOutStart = durationMsBlock - effFadeOut;
        
        let alphaAnimMain = `\\alpha&HFF&\\t(${startFade},${endFade},\\alpha&H00&)`;
        let alphaAnimGlow = `\\1a&HFF&\\3a&HFF&\\t(${startFade},${endFade},\\1a${gAlpha}\\3a${gAlpha})`;
        
        let transformAnim = '';
        if (style.animation === 'slide-up') {
          transformAnim = `\\move(${wordCenterX},${baseY + 40},${wordCenterX},${baseY},${startFade},${endFade})`;
        } else if (style.animation === 'zoom-in') {
          transformAnim = `\\fscx50\\fscy50\\t(${startFade},${endFade},\\fscx100\\fscy100)`;
        } else if (style.animation === 'bounce') {
          const midFade = Math.round(startFade + t_w / 2);
          transformAnim = `\\fscx80\\fscy80\\t(${startFade},${midFade},\\fscx120\\fscy120)\\t(${midFade},${endFade},\\fscx100\\fscy100)`;
        }

        // Add overall fade out at the end of the block
        if (effFadeOut > 0) {
          alphaAnimMain += `\\t(${fadeOutStart},${durationMsBlock},\\alpha&HFF&)`;
          alphaAnimGlow += `\\t(${fadeOutStart},${durationMsBlock},\\1a&HFF&\\3a&HFF&)`;
        }

        // Layer 0: Glow
        if (style.glow) {
          const glowEffect = `\\1c${gTag}\\3c${gTag}\\bord${Math.max(style.outlineWidth, style.glowBlur)}\\blur${style.glowBlur}`;
          const glowLine = `Dialogue: 0,${assTime(e.startTime)},${assTime(e.endTime)},Default,,0,0,0,,{${posTag}${wordAnTag}${glowEffect}${alphaAnimGlow}${transformAnim}}${wText}`;
          assLines.push(glowLine);
        }

        // Layer 1: Main Text
        const mainEffect = `\\1c${pTag}\\3c${oTag}\\bord${style.outlineWidth}\\blur0`;
        const mainLine = `Dialogue: 1,${assTime(e.startTime)},${assTime(e.endTime)},Default,,0,0,0,,{${posTag}${wordAnTag}${mainEffect}${alphaAnimMain}${transformAnim}}${wText}`;
        assLines.push(mainLine);

        currentX += wWidth + spaceWidth;
      });
      
    } else {
      // Fallback for simple blocks without words
      const posTag = `\\pos(${centerX},${baseY})`;
      let anim = '';
      if (style.animation === 'slide-up') anim = `\\move(${centerX},${baseY + 40},${centerX},${baseY},0,${effFadeIn})`;
      else if (style.animation === 'zoom-in') anim = `\\fscx50\\fscy50\\t(0,${effFadeIn},\\fscx100\\fscy100)`;
      else if (style.animation === 'bounce') anim = `\\fscx80\\fscy80\\t(0,${effFadeIn / 2},\\fscx120\\fscy120)\\t(${effFadeIn / 2},${effFadeIn},\\fscx100\\fscy100)`;
      else if (style.animation === 'fade' || effFadeIn > 0) anim = `\\fad(${effFadeIn},${effFadeOut})`;
      
      const blockAnTag = `\\an${alignment}`;

      if (style.glow) {
        const glowEffect = `\\1c${gTag}\\3c${gTag}\\1a${gAlpha}\\3a${gAlpha}\\bord${Math.max(style.outlineWidth, style.glowBlur)}\\blur${style.glowBlur}`;
        assLines.push(`Dialogue: 0,${assTime(e.startTime)},${assTime(e.endTime)},Default,,0,0,0,,{${posTag}${blockAnTag}${glowEffect}${anim}}${fullText}`);
      }
      
      const mainEffect = `\\1c${pTag}\\3c${oTag}\\1a&H00&\\3a&H00&\\bord${style.outlineWidth}\\blur0`;
      assLines.push(`Dialogue: 1,${assTime(e.startTime)},${assTime(e.endTime)},Default,,0,0,0,,{${posTag}${blockAnTag}${mainEffect}${anim}}${fullText}`);
    }
  });

  return header + '\n' + assLines.join('\n');
}

export function generateFFmpegScript(config: {
  videoFile: string;
  outputFormat: string;
  colorGrade: ColorGradeConfig;
  blurBand: BlurBandConfig;
  cropZoom: CropZoomConfig;
  subtitleStyle: SubtitleStyle;
  assFile: string;
  outputFile: string;
  duration?: number;
}): string {
  const filters: string[] = [];

  // 1. Scale to output format first
  let outW = 1920;
  let outH = 1080;
  if (config.outputFormat === '9:16') {
    outW = 1080;
    outH = 1920;
  } else if (config.outputFormat === '1:1') {
    outW = 1080;
    outH = 1080;
  } else if (config.outputFormat === '4:5') {
    outW = 1080;
    outH = 1350;
  }

  // 2. Crop & Zoom (before scaling to avoid quality loss)
  const cz = config.cropZoom;
  const zs = cz.enabled ? cz.zoomStart : 1.0;
  
  if (zs >= 1.0) {
    filters.push(`scale=${outW}:${outH}:force_original_aspect_ratio=increase`);
    filters.push(`crop=${outW}:${outH}`);
    if (zs > 1.0) {
      const cw = Math.floor(outW / zs);
      const ch = Math.floor(outH / zs);
      const cx = Math.floor((outW - cw) * cz.focusX);
      const cy = Math.floor((outH - ch) * cz.focusY);
      filters.push(`crop=${cw}:${ch}:${cx}:${cy}`);
      filters.push(`scale=${outW}:${outH}`);
    }
  } else {
    // Zoom out
    filters.push(`scale=${outW}:${outH}:force_original_aspect_ratio=decrease`);
    const sm_w = Math.floor(outW * zs);
    const sm_h = Math.floor(outH * zs);
    const sm_w_even = sm_w - (sm_w % 2);
    const sm_h_even = sm_h - (sm_h % 2);
    filters.push(`scale=${sm_w_even}:${sm_h_even}`);
    
    // TODO: background color handling, defaulting to black here
    filters.push(`pad=${outW}:${outH}:(ow-iw)/2:(oh-ih)/2:color=black`);
  }

  // 3. Blur Band (real blur)
  if (config.blurBand.enabled) {
    const bb = config.blurBand;
    const bh = Math.round((bb.height / 100) * outH);
    const by = Math.round((bb.positionY / 100) * outH - bh / 2);
    
    // We use a complex filter approach for real blur in FFmpeg
    // [0:v]split[main][bg];[bg]boxblur=${bb.blurIntensity}:1[blurred];[main][blurred]overlay=y=${by}:enable='between(t,0,9999)'
    // But since this is a simple linear filter list, we can use 'avgblur' or similar if we use a mask.
    // For simplicity in a single vf string, we can use a more advanced filtergraph later.
    // Here we'll stick to a placeholder or a simple boxblur on the whole frame + overlay
    filters.push(`split[m][b];[b]boxblur=${bb.blurIntensity}:5[bl];[m][bl]overlay=y=${by}:enable='between(t,0,9999)'`);
  }

  // 4. Color grade
  const cg = config.colorGrade;
  if (cg.brightness !== 0 || cg.contrast !== 0 || cg.saturation !== 0) {
    const eq = `eq=brightness=${(cg.brightness / 100).toFixed(2)}:contrast=${1 + cg.contrast / 100}:saturation=${1 + cg.saturation / 100}:gamma=${cg.gamma}`;
    filters.push(eq);
  }
  if (cg.sharpness !== 1.0) {
    filters.push(`unsharp=5:5:${((cg.sharpness - 1) * 2).toFixed(1)}:5:5:0`);
  }

  // 5. Subtitles
  filters.push(`ass='${config.assFile}'`);

  const filterStr = filters.join(',');

  return `ffmpeg -i "${config.videoFile}" \\
  -vf "${filterStr}" \\
  -c:v libx264 -preset slow -crf 18 \\
  -c:a aac -b:a 192k \\
  "${config.outputFile}"`;
}
