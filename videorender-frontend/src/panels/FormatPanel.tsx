import { useProjectStore } from '../store/projectStore';
import type { OutputFormat, BackgroundType } from '../store/projectStore';

const FORMATS: { value: OutputFormat; label: string; ratio: string; icon: string }[] = [
  { value: '9:16', label: 'Vertical', ratio: '9:16', icon: '📱' },
  { value: '16:9', label: 'Horizontal', ratio: '16:9', icon: '🖥️' },
  { value: '1:1', label: 'Quadrado', ratio: '1:1', icon: '⬛' },
  { value: '4:5', label: 'Instagram', ratio: '4:5', icon: '📸' },
];

const BG_TYPES: { value: BackgroundType; label: string; icon: string }[] = [
  { value: 'blur', label: 'Blur do Vídeo', icon: '🌫️' },
  { value: 'solid', label: 'Cor Sólida', icon: '🎨' },
  { value: 'gradient', label: 'Gradiente', icon: '🌈' },
  { value: 'image', label: 'Imagem', icon: '🖼️' },
];

export function FormatPanel() {
  const { outputFormat, background, videoInfo, setOutputFormat, setBackground } = useProjectStore();

  const videoAspect = videoInfo?.aspect ?? '16:9';
  const needsBg = outputFormat !== `${videoAspect}`;

  return (
    <div className="panel-content">
      <h2 style={{ fontFamily: 'Montserrat', fontWeight: 900, fontSize: 20, marginBottom: 6 }}>
        📐 Formato & Fundo
      </h2>
      <p style={{ color: 'var(--text-muted)', marginBottom: 20, fontSize: 13 }}>
        Define o formato de saída e como preencher o espaço se os aspectos não coincidirem.
      </p>

      {videoInfo && (
        <div className="info-chips" style={{ marginBottom: 16 }}>
          <span className="info-chip">Original: <strong>{videoInfo.aspect}</strong></span>
          <span className="info-chip">{videoInfo.width}×{videoInfo.height}</span>
        </div>
      )}

      {/* Format selector */}
      <div className="form-group">
        <div className="form-label">Formato de Saída</div>
        <div className="grid-2">
          {FORMATS.map((f) => (
            <div
              key={f.value}
              onClick={() => setOutputFormat(f.value)}
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                gap: 6,
                padding: '14px 10px',
                borderRadius: 'var(--radius)',
                border: `2px solid ${outputFormat === f.value ? 'var(--accent)' : 'var(--border)'}`,
                background: outputFormat === f.value ? 'var(--accent-dim)' : 'var(--bg-card)',
                cursor: 'pointer',
                transition: 'var(--transition)',
              }}
            >
              <span style={{ fontSize: 22 }}>{f.icon}</span>
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: outputFormat === f.value ? 'var(--accent-light)' : 'var(--text-primary)' }}>
                  {f.label}
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{f.ratio}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Output resolution info */}
      <div className="card" style={{ marginBottom: 16, padding: '10px 14px' }}>
        <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>Resolução de saída</div>
        <div style={{ fontFamily: 'JetBrains Mono', fontSize: 14, fontWeight: 600, color: 'var(--accent-light)' }}>
          {outputFormat === '9:16' ? '1080 × 1920' : outputFormat === '16:9' ? '1920 × 1080' : outputFormat === '1:1' ? '1080 × 1080' : '1080 × 1350'}
        </div>
      </div>

      <div className="divider" />

      {/* Background */}
      <div className="form-group">
        <div className="form-label" style={{ marginBottom: 10 }}>
          Tipo de Fundo
          {!needsBg && <span style={{ fontSize: 11, color: 'var(--success)', fontWeight: 600 }}>✓ Mesmo aspecto</span>}
        </div>
        <div className="segmented" style={{ marginBottom: 14 }}>
          {BG_TYPES.map((t) => (
            <button
              key={t.value}
              className={background.type === t.value ? 'active' : ''}
              onClick={() => setBackground({ type: t.value })}
            >
              {t.icon} {t.label}
            </button>
          ))}
        </div>

        {background.type === 'blur' && (
          <div className="form-group">
            <div className="form-label">
              <span>Intensidade do Blur</span>
              <span className="form-label-value">{background.blurIntensity}px</span>
            </div>
            <input
              type="range" min={5} max={60} step={1}
              value={background.blurIntensity}
              onChange={(e) => setBackground({ blurIntensity: Number(e.target.value) })}
            />
          </div>
        )}

        {background.type === 'solid' && (
          <div className="form-group">
            <div className="form-label">Cor do Fundo</div>
            <div className="color-row">
              <input
                type="text"
                value={background.solidColor}
                onChange={(e) => setBackground({ solidColor: e.target.value })}
                placeholder="#0a0a0a"
              />
              <input
                type="color"
                value={background.solidColor}
                onChange={(e) => setBackground({ solidColor: e.target.value })}
              />
            </div>
          </div>
        )}

        {background.type === 'gradient' && (
          <div className="grid-2">
            <div className="form-group">
              <div className="form-label">Cor 1</div>
              <div className="color-row">
                <input type="text" value={background.gradient[0]} onChange={(e) => setBackground({ gradient: [e.target.value, background.gradient[1]] })} />
                <input type="color" value={background.gradient[0]} onChange={(e) => setBackground({ gradient: [e.target.value, background.gradient[1]] })} />
              </div>
            </div>
            <div className="form-group">
              <div className="form-label">Cor 2</div>
              <div className="color-row">
                <input type="text" value={background.gradient[1]} onChange={(e) => setBackground({ gradient: [background.gradient[0], e.target.value] })} />
                <input type="color" value={background.gradient[1]} onChange={(e) => setBackground({ gradient: [background.gradient[0], e.target.value] })} />
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

