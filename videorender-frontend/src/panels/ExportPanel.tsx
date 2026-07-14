import { useState } from 'react';
import { useProjectStore } from '../store/projectStore';
import { useExportActions } from '../hooks/useExportActions';

export function ExportPanel() {
  const { videoInfo, outputFormat, srtEntries, subtitleStyle, colorGrade, blurBand, cropZoom, watermarks } = useProjectStore();
  const { exportJSON, exportASS, exportMask, getFFmpegScript } = useExportActions();
  const [copied, setCopied] = useState(false);
  const [showScript, setShowScript] = useState(false);

  const ffmpegScript = getFFmpegScript();

  const handleCopy = () => {
    navigator.clipboard.writeText(ffmpegScript);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const hasVideo = !!videoInfo;
  const hasSrt = srtEntries.length > 0;

  return (
    <div className="panel-content">
      <h2 style={{ fontFamily: 'Montserrat', fontWeight: 900, fontSize: 20, marginBottom: 6 }}>
        📦 Exportar Projeto
      </h2>
      <p style={{ color: 'var(--text-muted)', marginBottom: 20, fontSize: 13 }}>
        Exporte as configurações para processar no Kaggle com FFmpeg.
      </p>

      {/* Summary */}
      <div className="card" style={{ marginBottom: 16, padding: '12px 14px' }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 8 }}>Resumo do Projeto</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
            <span style={{ color: 'var(--text-muted)' }}>Vídeo</span>
            <span style={{ color: hasVideo ? 'var(--success)' : 'var(--danger)', fontWeight: 600 }}>
              {hasVideo ? `✓ ${videoInfo!.fileName}` : '✗ Não carregado'}
            </span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
            <span style={{ color: 'var(--text-muted)' }}>Legendas</span>
            <span style={{ color: hasSrt ? 'var(--success)' : 'var(--danger)', fontWeight: 600 }}>
              {hasSrt ? `✓ ${srtEntries.length} entradas` : '✗ Não carregadas'}
            </span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
            <span style={{ color: 'var(--text-muted)' }}>Formato</span>
            <span style={{ fontWeight: 600 }}>{outputFormat}</span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
            <span style={{ color: 'var(--text-muted)' }}>Zoom Ativo</span>
            <span style={{ fontWeight: 600, color: cropZoom.enabled ? 'var(--success)' : 'var(--text-muted)' }}>
              {cropZoom.enabled ? `✓ ${cropZoom.zoomStart}× → ${cropZoom.zoomEnd}×` : '—'}
            </span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
            <span style={{ color: 'var(--text-muted)' }}>Blur Band</span>
            <span style={{ fontWeight: 600, color: blurBand.enabled ? 'var(--success)' : 'var(--text-muted)' }}>
              {blurBand.enabled ? `✓ ${blurBand.position} ${blurBand.height}%` : '—'}
            </span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
            <span style={{ color: 'var(--text-muted)' }}>Color Grade</span>
            <span style={{ fontWeight: 600, color: 'var(--accent-light)' }}>
              {colorGrade.preset !== 'none' ? colorGrade.preset : 'custom'}
            </span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
            <span style={{ color: 'var(--text-muted)' }}>Remover Marca</span>
            <span style={{ fontWeight: 600, color: watermarks.length > 0 ? 'var(--success)' : 'var(--text-muted)' }}>
              {watermarks.length > 0 ? `✓ ${watermarks.length} caixas` : '—'}
            </span>
          </div>
        </div>
      </div>

      {/* Export blocks */}
      <div className="export-block">
        <div className="export-block-header">
          <span className="export-block-icon">📋</span>
          <div>
            <div className="export-block-title">Projeto JSON</div>
            <div className="export-block-desc">Todas as configurações do projeto</div>
          </div>
        </div>
        <div className="export-block-body">
          <p style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 10 }}>
            Salve e recarregue o projeto a qualquer momento. O Kaggle lê este JSON para saber como processar.
          </p>
          <button className="btn btn-primary" style={{ width: '100%' }} onClick={exportJSON}>
            ⬇️ Baixar JSON
          </button>
        </div>
      </div>

      <div className="export-block">
        <div className="export-block-header">
          <span className="export-block-icon">📝</span>
          <div>
            <div className="export-block-title">Legendas .ASS</div>
            <div className="export-block-desc">Arquivo de legenda queimável via FFmpeg</div>
          </div>
        </div>
        <div className="export-block-body">
          <p style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 10 }}>
            Gera o arquivo <code>.ass</code> com todos os estilos configurados (fonte, glow, posição, fade, etc).
          </p>
          <button
            className={`btn ${hasSrt ? 'btn-primary' : 'btn-secondary'}`}
            style={{ width: '100%' }}
            onClick={exportASS}
            disabled={!hasSrt}
          >
            ⬇️ Baixar .ASS
          </button>
          {!hasSrt && <p style={{ fontSize: 11, color: 'var(--danger)', marginTop: 6 }}>⚠ Carregue um SRT primeiro</p>}
        </div>
      </div>

      <div className="export-block">
        <div className="export-block-header">
          <span className="export-block-icon">🧹</span>
          <div>
            <div className="export-block-title">Máscara .PNG</div>
            <div className="export-block-desc">Imagem para o filtro removelogo do FFMPEG</div>
          </div>
        </div>
        <div className="export-block-body">
          <p style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 10 }}>
            Gera o arquivo de imagem na exata resolução do vídeo original para remover a marca d'água.
          </p>
          <button
            className={`btn ${watermarks.length > 0 ? 'btn-primary' : 'btn-secondary'}`}
            style={{ width: '100%' }}
            onClick={exportMask}
            disabled={watermarks.length === 0}
          >
            ⬇️ Baixar mask.png
          </button>
          {watermarks.length === 0 && <p style={{ fontSize: 11, color: 'var(--danger)', marginTop: 6 }}>⚠ Adicione áreas no painel</p>}
        </div>
      </div>

      <div className="export-block">
        <div className="export-block-header">
          <span className="export-block-icon">⚡</span>
          <div>
            <div className="export-block-title">Script FFmpeg</div>
            <div className="export-block-desc">Comando para usar no Kaggle</div>
          </div>
        </div>
        <div className="export-block-body">
          <button
            className="btn btn-secondary btn-sm"
            style={{ marginBottom: 8 }}
            onClick={() => setShowScript(!showScript)}
          >
            {showScript ? 'Ocultar' : 'Ver'} Script
          </button>
          {showScript && (
            <>
              <div className="code-block">{ffmpegScript}</div>
              <button
                className="btn btn-ghost btn-sm"
                style={{ marginTop: 6 }}
                onClick={handleCopy}
              >
                {copied ? '✓ Copiado!' : '📋 Copiar'}
              </button>
            </>
          )}
        </div>
      </div>

      {/* Kaggle note */}
      <div className="card" style={{ background: 'rgba(6,182,212,0.08)', borderColor: 'rgba(6,182,212,0.2)', padding: '12px 14px', marginTop: 16 }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--accent2)', marginBottom: 6 }}>📓 Workflow Kaggle</div>
        <ol style={{ fontSize: 12, color: 'var(--text-muted)', paddingLeft: 16, lineHeight: 1.8 }}>
          <li>Upload do vídeo + JSON + .ASS no dataset</li>
          <li>Notebook lê o JSON e monta os filtros FFmpeg</li>
          <li>FFmpeg aplica: recorte, cor, blur band, legendas</li>
          <li>Output.mp4 disponível para download</li>
        </ol>
      </div>
    </div>
  );
}

