import { useProjectStore } from '../store/projectStore';

const NAV_ITEMS = [
  { id: 'upload', icon: '📤', label: 'Upload & Frames' },
  { id: 'format', icon: '📐', label: 'Formato & Fundo' },
  { id: 'cropzoom', icon: '✂️', label: 'Recorte & Zoom' },
  { id: 'blurband', icon: '🌫️', label: 'Faixa de Blur' },
  { id: 'colorgrade', icon: '🎨', label: 'Cor & Nitidez' },
  { id: 'subtitles', icon: '📝', label: 'Legendas' },
  { id: 'overlays', icon: '🖼️', label: 'Overlays' },
  { id: 'watermark', icon: '🧹', label: 'Remover Marca' },
  { id: 'export', icon: '📦', label: 'Exportar' },
];

export function Sidebar() {
  const activePanel = useProjectStore((s) => s.activePanel);
  const setActivePanel = useProjectStore((s) => s.setActivePanel);
  const srtEntries = useProjectStore((s) => s.srtEntries);
  const videoInfo = useProjectStore((s) => s.videoInfo);
  const overlays = useProjectStore((s) => s.overlays);
  const watermarks = useProjectStore((s) => s.watermarks);

  const badges: Record<string, string | number> = {};
  if (srtEntries.length > 0) badges['subtitles'] = srtEntries.length;
  if (overlays.length > 0) badges['overlays'] = overlays.length;
  if (watermarks.length > 0) badges['watermark'] = watermarks.length;
  if (videoInfo) badges['upload'] = '✓';

  return (
    <aside className="app-sidebar">
      <div className="sidebar-section">
        <div className="sidebar-section-label">Módulos</div>
        {NAV_ITEMS.map((item) => (
          <div
            key={item.id}
            className={`nav-item ${activePanel === item.id ? 'active' : ''}`}
            onClick={() => setActivePanel(item.id)}
          >
            <span className="nav-icon">{item.icon}</span>
            <span>{item.label}</span>
            {badges[item.id] !== undefined && (
              <span className="nav-badge">{badges[item.id]}</span>
            )}
          </div>
        ))}
      </div>
    </aside>
  );
}
