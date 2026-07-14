import { useProjectStore } from '../store/projectStore';
import type { ColorGradeConfig } from '../store/projectStore';

const PRESETS: { id: string; label: string; emoji: string; values: Partial<ColorGradeConfig> }[] = [
  { id: 'none', label: 'Original', emoji: '🎬', values: { brightness: 0, contrast: 0, saturation: 0, sharpness: 1, temperature: 0, vignette: 0, gamma: 1 } },
  { id: 'anime', label: 'Anime', emoji: '✨', values: { brightness: 5, contrast: 10, saturation: 25, sharpness: 1.3, temperature: -5, vignette: 0.15, gamma: 1.05 } },
  { id: 'drama', label: 'Drama', emoji: '🎭', values: { brightness: -5, contrast: 15, saturation: -10, sharpness: 1.1, temperature: -15, vignette: 0.3, gamma: 0.95 } },
  { id: 'vivid', label: 'Vivid', emoji: '🌈', values: { brightness: 8, contrast: 15, saturation: 35, sharpness: 1.4, temperature: 10, vignette: 0.1, gamma: 1.0 } },
  { id: 'cinematic', label: 'Cinematic', emoji: '🎞️', values: { brightness: -8, contrast: 20, saturation: -15, sharpness: 1.2, temperature: -20, vignette: 0.4, gamma: 0.9 } },
  { id: 'warm', label: 'Quente', emoji: '🌅', values: { brightness: 5, contrast: 5, saturation: 10, sharpness: 1.0, temperature: 30, vignette: 0.2, gamma: 1.05 } },
  { id: 'dark', label: 'Dark', emoji: '🌑', values: { brightness: -15, contrast: 20, saturation: -20, sharpness: 1.2, temperature: -10, vignette: 0.5, gamma: 0.85 } },
  { id: 'sharp', label: 'Nítido', emoji: '🔍', values: { brightness: 0, contrast: 10, saturation: 5, sharpness: 2.0, temperature: 0, vignette: 0, gamma: 1.0 } },
];

function SliderRow({ label, value, min, max, step, unit, onChange }: {
  label: string; value: number; min: number; max: number; step: number;
  unit?: string; onChange: (v: number) => void;
}) {
  return (
    <div className="form-group">
      <div className="form-label">
        <span>{label}</span>
        <span className="form-label-value">{value > 0 ? '+' : ''}{value}{unit ?? ''}</span>
      </div>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} />
    </div>
  );
}

export function ColorGradePanel() {
  const { colorGrade, setColorGrade } = useProjectStore();

  const applyPreset = (preset: typeof PRESETS[0]) => {
    setColorGrade({ ...preset.values, preset: preset.id });
  };

  return (
    <div className="panel-content">
      <h2 style={{ fontFamily: 'Montserrat', fontWeight: 900, fontSize: 20, marginBottom: 6 }}>
        🎨 Cor & Nitidez
      </h2>
      <p style={{ color: 'var(--text-muted)', marginBottom: 16, fontSize: 13 }}>
        Ajuste a correção de cor, contraste e nitidez. Os valores são convertidos para filtros FFmpeg no export.
      </p>

      {/* Presets */}
      <div className="form-group">
        <div className="form-label">Presets</div>
        <div className="presets-grid" style={{ gridTemplateColumns: 'repeat(4, 1fr)' }}>
          {PRESETS.map((p) => (
            <div
              key={p.id}
              className={`preset-chip ${colorGrade.preset === p.id ? 'active' : ''}`}
              onClick={() => applyPreset(p)}
              title={p.label}
            >
              <div style={{ fontSize: 18, marginBottom: 2 }}>{p.emoji}</div>
              <div>{p.label}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="divider" />

      <SliderRow label="Brilho" value={colorGrade.brightness} min={-100} max={100} step={1} onChange={(v) => setColorGrade({ brightness: v, preset: 'custom' })} />
      <SliderRow label="Contraste" value={colorGrade.contrast} min={-100} max={100} step={1} onChange={(v) => setColorGrade({ contrast: v, preset: 'custom' })} />
      <SliderRow label="Saturação" value={colorGrade.saturation} min={-100} max={100} step={1} onChange={(v) => setColorGrade({ saturation: v, preset: 'custom' })} />
      <SliderRow label="Temperatura" value={colorGrade.temperature} min={-100} max={100} step={1} onChange={(v) => setColorGrade({ temperature: v, preset: 'custom' })} />
      <SliderRow label="Nitidez" value={colorGrade.sharpness} min={0} max={3} step={0.1} unit="×" onChange={(v) => setColorGrade({ sharpness: v, preset: 'custom' })} />
      <SliderRow label="Gamma" value={colorGrade.gamma} min={0.5} max={2.5} step={0.05} unit="×" onChange={(v) => setColorGrade({ gamma: v, preset: 'custom' })} />
      <SliderRow label="Vignette" value={colorGrade.vignette} min={0} max={1} step={0.05} onChange={(v) => setColorGrade({ vignette: v, preset: 'custom' })} />
    </div>
  );
}

