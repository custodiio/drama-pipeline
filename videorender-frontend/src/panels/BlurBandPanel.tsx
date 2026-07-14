import { useProjectStore } from '../store/projectStore';
import type { BlurBandPosition } from '../store/projectStore';

function Toggle({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="toggle">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span className="toggle-slider" />
    </label>
  );
}

export function BlurBandPanel() {
  const { blurBand, setBlurBand } = useProjectStore();

  return (
    <div className="panel-content">
      <h2 style={{ fontFamily: 'Montserrat', fontWeight: 900, fontSize: 20, marginBottom: 6 }}>
        🌫️ Faixa de Blur
      </h2>
      <p style={{ color: 'var(--text-muted)', marginBottom: 16, fontSize: 13 }}>
        Para vídeos verticais com legendas no centro. Adiciona faixa de blur com esmaecimento para cobrir legendas sem cortar o quadro.
      </p>

      <div className="toggle-row" style={{ marginBottom: 16 }}>
        <span className="toggle-label">Ativar Faixa de Blur</span>
        <Toggle checked={blurBand.enabled} onChange={(v) => setBlurBand({ enabled: v })} />
      </div>

      <div style={{ opacity: blurBand.enabled ? 1 : 0.4, pointerEvents: blurBand.enabled ? 'auto' : 'none', transition: 'opacity 0.2s' }}>

        {/* Position */}
        <div className="form-group">
          <div className="form-label">
            <span>Posição Vertical (Y)</span>
            <span className="form-label-value">{blurBand.positionY}%</span>
          </div>
          <input
            type="range" min={0} max={100} step={1}
            value={blurBand.positionY}
            onChange={(e) => setBlurBand({ positionY: Number(e.target.value) })}
          />
        </div>

        {/* Height */}
        <div className="form-group">
          <div className="form-label">
            <span>Altura da Faixa</span>
            <span className="form-label-value">{blurBand.height}%</span>
          </div>
          <input
            type="range" min={5} max={60} step={1}
            value={blurBand.height}
            onChange={(e) => setBlurBand({ height: Number(e.target.value) })}
          />
        </div>

        {/* Blur intensity */}
        <div className="form-group">
          <div className="form-label">
            <span>Intensidade do Blur</span>
            <span className="form-label-value">{blurBand.blurIntensity}px</span>
          </div>
          <input
            type="range" min={5} max={80} step={1}
            value={blurBand.blurIntensity}
            onChange={(e) => setBlurBand({ blurIntensity: Number(e.target.value) })}
          />
        </div>

        {/* Feather */}
        <div className="form-group">
          <div className="form-label">
            <span>Esmaecimento (Feather)</span>
            <span className="form-label-value">{blurBand.feather}%</span>
          </div>
          <input
            type="range" min={10} max={100} step={5}
            value={blurBand.feather}
            onChange={(e) => setBlurBand({ feather: Number(e.target.value) })}
          />
        </div>

        {/* Color Overlay Toggle */}
        <div className="toggle-row" style={{ marginBottom: 16 }}>
          <span className="toggle-label">Ativar Faixa de Cor</span>
          <Toggle
            checked={blurBand.colorOverlayEnabled}
            onChange={(v) => setBlurBand({ colorOverlayEnabled: v })}
          />
        </div>

        {/* Color & Opacity (only when overlay is enabled) */}
        {blurBand.colorOverlayEnabled && (
          <div className="grid-2" style={{ marginBottom: 16 }}>
            <div className="form-group">
              <div className="form-label">Cor da Faixa</div>
              <div className="color-row">
                <input
                  type="text"
                  value={blurBand.color}
                  onChange={(e) => setBlurBand({ color: e.target.value })}
                />
                <input
                  type="color"
                  value={blurBand.color}
                  onChange={(e) => setBlurBand({ color: e.target.value })}
                />
              </div>
            </div>
            <div className="form-group">
              <div className="form-label">
                <span>Opacidade</span>
                <span className="form-label-value">{Math.round(blurBand.opacity * 100)}%</span>
              </div>
              <input
                type="range" min={0} max={1} step={0.05}
                value={blurBand.opacity}
                onChange={(e) => setBlurBand({ opacity: Number(e.target.value) })}
              />
            </div>
          </div>
        )}

        {/* Visual preview */}
        <div
          style={{
            width: '100%',
            aspectRatio: '9/16',
            maxHeight: 300,
            background: 'linear-gradient(135deg, #1a1a2e, #16213e)',
            borderRadius: 'var(--radius)',
            border: '1px solid var(--border)',
            position: 'relative',
            overflow: 'hidden',
            margin: '0 auto',
            display: 'block',
          }}
        >
          {/* Simulated video content */}
          <div style={{
            position: 'absolute',
            inset: 0,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 24,
            opacity: 0.3,
          }}>🎬</div>

          {/* Blur band overlay - custom position */}
          <div style={{
            position: 'absolute',
            top: `${Math.max(0, blurBand.positionY - blurBand.height / 2)}%`,
            left: 0,
            right: 0,
            height: `${blurBand.height}%`,
            WebkitMaskImage: `linear-gradient(to bottom, transparent 0%, black ${blurBand.feather / 2}%, black ${100 - blurBand.feather / 2}%, transparent 100%)`,
            maskImage: `linear-gradient(to bottom, transparent 0%, black ${blurBand.feather / 2}%, black ${100 - blurBand.feather / 2}%, transparent 100%)`,
          }}>
            <div style={{
              position: 'absolute',
              inset: 0,
              background: (blurBand.colorOverlayEnabled && blurBand.opacity > 0) ? `${blurBand.color}${Math.round(blurBand.opacity * 255).toString(16).padStart(2, '0')}` : 'transparent',
              backdropFilter: `blur(${Math.max(1, blurBand.blurIntensity * (300 / 1920))}px)`,
              WebkitBackdropFilter: `blur(${Math.max(1, blurBand.blurIntensity * (300 / 1920))}px)`,
            }} />
          </div>

          {/* Label */}
          <div style={{
            position: 'absolute',
            bottom: 8,
            left: 0,
            right: 0,
            textAlign: 'center',
            fontSize: 10,
            color: 'rgba(255,255,255,0.5)',
          }}>
            Preview simulado (Visual Real de Blur)
          </div>
        </div>

        <div style={{ marginTop: 12, fontSize: 11, color: 'var(--text-muted)', background: 'rgba(255,255,255,0.05)', padding: '8px 12px', borderRadius: 4 }}>
          <strong>Nota:</strong> O preview visual mostra o desfoque real na área selecionada. O arquivo JSON exportará as coordenadas exatas da faixa, mas o script gerador do Kaggle será responsável por aplicar o filtro GBLUR nessa região pelo FFmpeg.
        </div>
      </div>
    </div>
  );
}

