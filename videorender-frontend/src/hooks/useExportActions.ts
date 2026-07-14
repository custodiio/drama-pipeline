import { useCallback, useState } from 'react';
import { useProjectStore, getOutputDimensions } from '../store/projectStore';
import { extractFrames } from '../utils/frameExtractor';
import { parseSrt } from '../utils/srtParser';
import { exportToAss, generateFFmpegScript } from '../utils/assExporter';

export function useExportActions() {
  const store = useProjectStore();

  const exportJSON = () => {
    const data = store.exportProject();
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'videorender-project.json';
    a.click();
    URL.revokeObjectURL(url);
  };

  const exportASS = () => {
    const info = store.videoInfo;
    const [w, h] = getOutputDimensions(store.outputFormat);
    const ass = exportToAss(store.srtEntries, store.subtitleStyle, w, h);
    const blob = new Blob([ass], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'legendas.ass';
    a.click();
    URL.revokeObjectURL(url);
  };

  const exportMask = () => {
    const info = store.videoInfo;
    if (!info) {
      alert("Nenhum vídeo carregado para determinar a resolução da máscara.");
      return;
    }
    
    // Create an offline canvas with the original video resolution
    const canvas = document.createElement('canvas');
    canvas.width = info.width;
    canvas.height = info.height;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // Fill with black (0)
    ctx.fillStyle = '#000000';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    // Draw solid white boxes (255) for removelogo
    ctx.fillStyle = '#FFFFFF';
    ctx.strokeStyle = '#FFFFFF';
    ctx.lineWidth = Math.max(2, Math.floor(canvas.height * 0.005));

    store.watermarks.forEach(w => {
      const wx = (w.x / 100) * canvas.width;
      const wy = (w.y / 100) * canvas.height;
      const ww = (w.width / 100) * canvas.width;
      const wh = (w.height / 100) * canvas.height;

      if (w.filled) {
        ctx.fillRect(wx, wy, ww, wh);
      } else {
        ctx.strokeRect(wx, wy, ww, wh);
      }
    });

    // Download as PNG
    canvas.toBlob((blob) => {
      if (!blob) return;
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'mask.png';
      a.click();
      URL.revokeObjectURL(url);
    }, 'image/png');
  };

  const getFFmpegScript = () => {
    return generateFFmpegScript({
      videoFile: store.videoInfo?.fileName ?? 'input.mp4',
      outputFormat: store.outputFormat,
      colorGrade: store.colorGrade,
      blurBand: store.blurBand,
      cropZoom: store.cropZoom,
      subtitleStyle: store.subtitleStyle,
      assFile: 'legendas.ass',
      outputFile: 'output.mp4',
    });
  };

  return { exportJSON, exportASS, exportMask, getFFmpegScript };
}
