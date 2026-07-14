import { useState, useEffect } from 'react';
import { useProjectStore } from '../store/projectStore';

interface DbPreset {
  id: string;
  name: string;
  preset_data: Record<string, any>;
  created_at: string;
  updated_at: string;
}

export function PresetsModal({ onClose }: { onClose: () => void }) {
  const [presets, setPresets] = useState<DbPreset[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [newPresetName, setNewPresetName] = useState('');
  const [includeConfig, setIncludeConfig] = useState({
    format: true,
    filter: true,
    subtitle: true,
    crop: true,
    staticCrop: true,
    position: true,
    edit: true,
    background: true,
    watermark: false,
    overlay: true,
  });

  // Carrega presets do banco ao abrir o modal
  useEffect(() => {
    loadPresets();
  }, []);

  const loadPresets = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch('/api/presets');
      if (!res.ok) throw new Error(`Erro ${res.status}`);
      const data: DbPreset[] = await res.json();
      setPresets(data);
    } catch (e: any) {
      setError('Falha ao carregar presets: ' + (e.message ?? 'Erro desconhecido'));
    } finally {
      setLoading(false);
    }
  };

  const handleSavePreset = async () => {
    if (!newPresetName.trim()) return;
    setSaving(true);
    setError(null);

    const store = useProjectStore.getState();
    const presetData: any = {};

    if (includeConfig.format) presetData.outputFormat = store.outputFormat;
    if (includeConfig.filter) {
      presetData.colorGrade = store.colorGrade;
      presetData.blurBand = store.blurBand;
    }
    if (includeConfig.subtitle) presetData.subtitleStyle = store.subtitleStyle;
    if (includeConfig.crop) presetData.cropZoom = store.cropZoom;
    if (includeConfig.staticCrop) presetData.staticCrop = store.staticCrop;
    if (includeConfig.position) presetData.videoPosition = store.videoPosition;
    if (includeConfig.edit) presetData.videoEdit = store.videoEdit;
    if (includeConfig.background) presetData.background = store.background;
    if (includeConfig.watermark) presetData.watermarks = store.watermarks;
    if (includeConfig.overlay) presetData.overlays = store.overlays;

    try {
      const res = await fetch('/api/presets', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: newPresetName.trim(), preset_data: presetData }),
      });
      if (!res.ok) throw new Error(`Erro ${res.status}`);
      setNewPresetName('');
      await loadPresets(); // Recarrega lista atualizada
    } catch (e: any) {
      setError('Falha ao salvar preset: ' + (e.message ?? 'Erro desconhecido'));
    } finally {
      setSaving(false);
    }
  };

  const handleLoadPreset = (preset: DbPreset) => {
    useProjectStore.getState().loadPreset(preset.preset_data);
    onClose();
  };

  const handleDeletePreset = async (preset: DbPreset) => {
    if (!window.confirm(`Apagar a pré-definição "${preset.name}"?`)) return;
    setError(null);
    try {
      const res = await fetch(`/api/presets?id=${preset.id}`, { method: 'DELETE' });
      if (!res.ok) throw new Error(`Erro ${res.status}`);
      await loadPresets();
    } catch (e: any) {
      setError('Falha ao apagar preset: ' + (e.message ?? 'Erro desconhecido'));
    }
  };

  return (
    <div style={{
      position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
      background: 'rgba(0,0,0,0.7)', zIndex: 10000,
      display: 'flex', alignItems: 'center', justifyContent: 'center'
    }}>
      <div className="card" style={{ width: 460, padding: 24, position: 'relative', maxHeight: '90vh', display: 'flex', flexDirection: 'column' }}>
        <button
          onClick={onClose}
          className="btn btn-ghost"
          style={{ position: 'absolute', top: 16, right: 16, padding: '4px 8px' }}
        >
          ✕
        </button>
        <h2 style={{ fontSize: 18, marginBottom: 4 }}>💾 Pré-Definições (Presets)</h2>
        <p style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 16 }}>
          ☁️ Salvos no banco de dados — disponíveis em qualquer dispositivo
        </p>

        {error && (
          <div style={{
            background: 'rgba(220,38,38,0.15)', border: '1px solid rgba(220,38,38,0.4)',
            borderRadius: 6, padding: '8px 12px', marginBottom: 12, fontSize: 12, color: '#fca5a5'
          }}>
            ⚠️ {error}
          </div>
        )}

        {/* Salvar preset atual */}
        <div style={{ marginBottom: 20 }}>
          <h3 style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 10 }}>Salvar Configuração Atual</h3>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
            {[
              { key: 'format', label: 'Formato' },
              { key: 'filter', label: 'Cor & Blur' },
              { key: 'subtitle', label: 'Legendas' },
              { key: 'crop', label: 'Zoom Dinâmico' },
              { key: 'staticCrop', label: 'Crop Estático' },
              { key: 'position', label: 'Posição do Vídeo' },
              { key: 'edit', label: 'Corte de Vídeo' },
              { key: 'background', label: 'Fundo' },
              { key: 'watermark', label: 'Máscaras' },
              { key: 'overlay', label: 'Overlays' },
            ].map(({ key, label }) => (
              <label key={key} style={{ fontSize: 12, display: 'flex', alignItems: 'center', gap: 4 }}>
                <input
                  type="checkbox"
                  checked={includeConfig[key as keyof typeof includeConfig]}
                  onChange={e => setIncludeConfig(s => ({ ...s, [key]: e.target.checked }))}
                />
                {label}
              </label>
            ))}
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <input
              type="text"
              className="input-field"
              placeholder="Nome do preset..."
              value={newPresetName}
              onChange={e => setNewPresetName(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleSavePreset()}
              style={{ flex: 1 }}
              disabled={saving}
            />
            <button
              className="btn btn-primary"
              onClick={handleSavePreset}
              disabled={!newPresetName.trim() || saving}
            >
              {saving ? '⏳' : 'Salvar'}
            </button>
          </div>
        </div>

        {/* Lista de presets do banco */}
        <h3 style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 10 }}>
          Presets Salvos
          {!loading && <span style={{ fontWeight: 400, marginLeft: 6 }}>({presets.length})</span>}
        </h3>

        <div style={{ overflowY: 'auto', flex: 1, minHeight: 60 }}>
          {loading ? (
            <div style={{ color: 'var(--text-muted)', fontSize: 12, textAlign: 'center', padding: '24px 0' }}>
              ⏳ Carregando presets...
            </div>
          ) : presets.length === 0 ? (
            <div style={{ color: 'var(--text-muted)', fontSize: 12, textAlign: 'center', padding: '24px 0' }}>
              Nenhum preset salvo ainda. Crie o primeiro acima!
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {presets.map(preset => (
                <div key={preset.id} style={{
                  display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                  background: 'rgba(255,255,255,0.05)', padding: '10px 12px', borderRadius: 8,
                  border: '1px solid var(--border)',
                }}>
                  <div>
                    <div style={{ fontSize: 14, fontWeight: 500 }}>{preset.name}</div>
                    <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>
                      Atualizado: {new Date(preset.updated_at).toLocaleDateString('pt-BR')}
                    </div>
                  </div>
                  <div style={{ display: 'flex', gap: 6 }}>
                    <button
                      className="btn btn-primary btn-sm"
                      onClick={() => handleLoadPreset(preset)}
                    >
                      Carregar
                    </button>
                    <button
                      className="btn btn-secondary btn-sm"
                      style={{ color: 'var(--danger)' }}
                      onClick={() => handleDeletePreset(preset)}
                    >
                      ✕
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
