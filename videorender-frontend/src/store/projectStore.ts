import { create } from 'zustand';
import type { ExtractedFrame, VideoInfo, SrtEntry } from '../types';

export type { ExtractedFrame, VideoInfo, SrtEntry };
export type OutputFormat = '9:16' | '16:9' | '1:1' | '4:5';

export function getOutputDimensions(format: OutputFormat): [number, number] {
  if (format === '9:16') return [1080, 1920];
  if (format === '1:1') return [1080, 1080];
  if (format === '4:5') return [1080, 1350];
  return [1920, 1080];
}
export type BackgroundType = 'blur' | 'solid' | 'gradient' | 'image';
export type BlurBandPosition = 'top' | 'bottom' | 'both';

export interface SubtitleStyle {
  font: string;
  size: number;
  color: string;
  outlineColor: string;
  outlineWidth: number;
  shadowColor: string;
  shadowOffset: number;
  glow: boolean;
  glowColor: string;
  glowBlur: number;
  glowIntensity: number;
  bold: boolean;
  italic: boolean;
  allCaps: boolean;
  positionX: number;
  positionY: number;
  wordsPerBlock: number;
  linesPerBlock: number;
  alignment: number;
  bgBox: boolean;
  bgBoxColor: string;
  bgBoxOpacity: number;
  bgBoxRadius: number;
  fadeIn: number;
  fadeOut: number;
  fadeInLimitPct: number;
  fadeOutLimitPct: number;
  preset: string;
  animation: 'none' | 'fade' | 'slide-up' | 'bounce' | 'zoom-in';
}

export interface BlurBandConfig {
  enabled: boolean;
  position: BlurBandPosition;
  positionY: number;
  height: number;
  blurIntensity: number;
  feather: number;
  color: string;
  opacity: number;
  colorOverlayEnabled: boolean;
}

export interface CropZoomConfig {
  enabled: boolean;
  animatedZoom: boolean;
  zoomStart: number;
  zoomEnd: number;
  focusX: number;
  focusY: number;
  animDuration: number;
  startTime: number;
  removeBottomSubtitlesPct: number;
}

export interface StaticCropConfig {
  enabled: boolean;
  aspectRatio: 'original' | '9:16' | '16:9' | '3:4' | '1:1' | 'custom';
  x: number;      // 0 to 100 percentage
  y: number;      // 0 to 100 percentage
  width: number;  // 0 to 100 percentage
  height: number; // 0 to 100 percentage
  sizePct: number; // Crop size percentage (10-100)
  posX: number;    // Crop X position percentage (0-100)
  posY: number;    // Crop Y position percentage (0-100)
  marginL: number; // Custom crop: Left margin (0-50)
  marginR: number; // Custom crop: Right margin (0-50)
  marginT: number; // Custom crop: Top margin (0-50)
  marginB: number; // Custom crop: Bottom margin (0-50)
}

export interface VideoPositionConfig {
  enabled: boolean;
  x: number;     // translation X percentage (-100 to 100)
  y: number;     // translation Y percentage (-100 to 100)
  scale: number; // scale factor (0.5 to 2.5)
}

export interface VideoEditConfig {
  speed: number;       // speed factor (0.5 to 2.0)
  hFlip: boolean;      // horizontal flip
  vFlip: boolean;      // vertical flip
  rotate: 0 | 90 | 180 | 270;
  volume: number;      // volume (0 to 200)
  audioFadeIn: number;  // seconds
  audioFadeOut: number; // seconds
}


export interface ColorGradeConfig {
  preset: string;
  brightness: number;
  contrast: number;
  saturation: number;
  sharpness: number;
  temperature: number;
  vignette: number;
  gamma: number;
}

export interface OverlayItem {
  id: string;
  type: 'image' | 'text' | 'watermark';
  content: string;
  x: number;
  y: number;
  width: number;
  height: number;
  opacity: number;
  timeIn: number;
  timeOut: number;
  fontSize?: number;
  fontColor?: string;
  fontFamily?: string;
  fontWeight?: string;
  fontStyle?: string;
  shadowColor?: string;
  shadowBlur?: number;
  shadowX?: number;
  shadowY?: number;
  bgColor?: string;
  bgOpacity?: number;
  bgRadius?: number;
  zIndex: number;
}

export interface WatermarkBox {
  id: string;
  x: number; // Percentage (0-100)
  y: number; // Percentage (0-100)
  width: number; // Percentage (0-100)
  height: number; // Percentage (0-100)
  filled: boolean;
}

export interface ProjectState {
  videoFile: File | null;
  videoObjectUrl: string | null;
  videoInfo: VideoInfo | null;
  extractedFrames: ExtractedFrame[];
  selectedFrameId: string | null;

  srtFile: File | null;
  srtEntries: SrtEntry[];
  srtPreviewStartTime: number;

  outputFormat: OutputFormat;
  background: {
    type: BackgroundType;
    blurIntensity: number;
    solidColor: string;
    gradient: [string, string];
    imageUrl: string;
  };

  cropZoom: CropZoomConfig;
  staticCrop: StaticCropConfig;
  videoPosition: VideoPositionConfig;
  videoEdit: VideoEditConfig;
  blurBand: BlurBandConfig;
  colorGrade: ColorGradeConfig;
  subtitleStyle: SubtitleStyle;
  overlays: OverlayItem[];
  watermarks: WatermarkBox[];

  activePanel: string;
  isPlayingPreview: boolean;
  previewTime: number;

  setVideoFile: (file: File, url: string, info: VideoInfo) => void;
  setExtractedFrames: (frames: ExtractedFrame[]) => void;
  setSelectedFrame: (id: string) => void;
  setSrtFile: (file: File, entries: SrtEntry[]) => void;
  setSrtEntries: (entries: SrtEntry[]) => void;
  setSrtPreviewStartTime: (t: number) => void;
  setOutputFormat: (f: OutputFormat) => void;
  setBackground: (bg: Partial<ProjectState['background']>) => void;
  setCropZoom: (cfg: Partial<CropZoomConfig>) => void;
  setStaticCrop: (cfg: Partial<StaticCropConfig>) => void;
  setVideoPosition: (cfg: Partial<VideoPositionConfig>) => void;
  setVideoEdit: (cfg: Partial<VideoEditConfig>) => void;
  setBlurBand: (cfg: Partial<BlurBandConfig>) => void;
  setColorGrade: (cfg: Partial<ColorGradeConfig>) => void;
  setSubtitleStyle: (style: Partial<SubtitleStyle>) => void;
  addOverlay: (overlay: OverlayItem) => void;
  updateOverlay: (id: string, changes: Partial<OverlayItem>) => void;
  removeOverlay: (id: string) => void;
  addWatermark: (box: WatermarkBox) => void;
  updateWatermark: (id: string, changes: Partial<WatermarkBox>) => void;
  removeWatermark: (id: string) => void;
  setActivePanel: (panel: string) => void;
  setIsPlayingPreview: (v: boolean) => void;
  setPreviewTime: (t: number) => void;
  loadPreset: (preset: any) => void;
  exportProject: () => object;
}

const defaultSubtitleStyle: SubtitleStyle = {
  font: 'Montserrat',
  size: 52,
  color: '#FFFFFF',
  outlineColor: '#000000',
  outlineWidth: 2.5,
  shadowColor: '#000000',
  shadowOffset: 1,
  glow: false,
  glowColor: '#FF6B6B',
  glowBlur: 10,
  glowIntensity: 1,
  bold: true,
  italic: false,
  allCaps: false,
  positionX: 50,
  positionY: 85,
  wordsPerBlock: 4,
  linesPerBlock: 1,
  alignment: 2,
  bgBox: false,
  bgBoxColor: '#000000',
  bgBoxOpacity: 0.5,
  bgBoxRadius: 8,
  fadeIn: 100,
  fadeOut: 80,
  fadeInLimitPct: 20,
  fadeOutLimitPct: 15,
  preset: 'custom',
  animation: 'none',
};

const defaultColorGrade: ColorGradeConfig = {
  preset: 'none',
  brightness: 0,
  contrast: 5,
  saturation: 10,
  sharpness: 1.0,
  temperature: 0,
  vignette: 0,
  gamma: 1.0,
};

const defaultCropZoom: CropZoomConfig = {
  enabled: false,
  animatedZoom: true,
  zoomStart: 1.0,
  zoomEnd: 1.35,
  focusX: 0.5,
  focusY: 0.45,
  animDuration: 1.5,
  startTime: 0,
  removeBottomSubtitlesPct: 12,
};

const defaultBlurBand: BlurBandConfig = {
  enabled: false,
  position: 'bottom',
  positionY: 85,
  height: 20,
  blurIntensity: 20,
  feather: 40,
  color: '#000000',
  opacity: 0.6,
  colorOverlayEnabled: true,
};

const defaultStaticCrop: StaticCropConfig = {
  enabled: false,
  aspectRatio: 'original',
  x: 0,
  y: 0,
  width: 100,
  height: 100,
  sizePct: 100,
  posX: 50,
  posY: 50,
  marginL: 0,
  marginR: 0,
  marginT: 0,
  marginB: 0,
};

const defaultVideoPosition: VideoPositionConfig = {
  enabled: false,
  x: 0,
  y: 0,
  scale: 1.0,
};

const defaultVideoEdit: VideoEditConfig = {
  speed: 1.0,
  hFlip: false,
  vFlip: false,
  rotate: 0,
  volume: 100,
  audioFadeIn: 0,
  audioFadeOut: 0,
};

export const useProjectStore = create<ProjectState>((set, get) => ({
  videoFile: null,
  videoObjectUrl: null,
  videoInfo: null,
  extractedFrames: [],
  selectedFrameId: null,

  srtFile: null,
  srtEntries: [],
  srtPreviewStartTime: 0,

  outputFormat: '9:16',
  background: {
    type: 'blur',
    blurIntensity: 25,
    solidColor: '#0a0a0a',
    gradient: ['#0f0c29', '#302b63'],
    imageUrl: '',
  },

  cropZoom: defaultCropZoom,
  staticCrop: defaultStaticCrop,
  videoPosition: defaultVideoPosition,
  videoEdit: defaultVideoEdit,
  blurBand: defaultBlurBand,
  colorGrade: defaultColorGrade,
  subtitleStyle: defaultSubtitleStyle,
  overlays: [],
  watermarks: [],

  activePanel: 'upload',
  isPlayingPreview: false,
  previewTime: 0,

  setVideoFile: (file, url, info) => set({ videoFile: file, videoObjectUrl: url, videoInfo: info }),
  setExtractedFrames: (frames) => set({ extractedFrames: frames }),
  setSelectedFrame: (id) => set({ selectedFrameId: id }),
  setSrtFile: (file, entries) => set({ srtFile: file, srtEntries: entries }),
  setSrtEntries: (entries) => set({ srtEntries: entries }),
  setSrtPreviewStartTime: (t) => set({ srtPreviewStartTime: t }),
  setOutputFormat: (f) => set({ outputFormat: f }),
  setBackground: (bg) => set((s) => ({ background: { ...s.background, ...bg } })),
  setCropZoom: (cfg) => set((s) => ({ cropZoom: { ...s.cropZoom, ...cfg } })),
  setStaticCrop: (cfg) => set((s) => ({ staticCrop: { ...s.staticCrop, ...cfg } })),
  setVideoPosition: (cfg) => set((s) => ({ videoPosition: { ...s.videoPosition, ...cfg } })),
  setVideoEdit: (cfg) => set((s) => ({ videoEdit: { ...s.videoEdit, ...cfg } })),
  setBlurBand: (cfg) => set((s) => ({ blurBand: { ...s.blurBand, ...cfg } })),
  setColorGrade: (cfg) => set((s) => ({ colorGrade: { ...s.colorGrade, ...cfg } })),
  setSubtitleStyle: (style) => set((s) => ({ subtitleStyle: { ...s.subtitleStyle, ...style } })),
  addOverlay: (overlay) => set((s) => ({ overlays: [...s.overlays, overlay] })),
  updateOverlay: (id, changes) =>
    set((s) => ({
      overlays: s.overlays.map((o) => (o.id === id ? { ...o, ...changes } : o)),
    })),
  removeOverlay: (id) => set((s) => ({ overlays: s.overlays.filter((o) => o.id !== id) })),
  addWatermark: (box) => set((s) => ({ watermarks: [...s.watermarks, box] })),
  updateWatermark: (id, changes) =>
    set((s) => ({
      watermarks: s.watermarks.map((w) => (w.id === id ? { ...w, ...changes } : w)),
    })),
  removeWatermark: (id) => set((s) => ({ watermarks: s.watermarks.filter((w) => w.id !== id) })),
  setActivePanel: (panel) => set({ activePanel: panel }),
  setIsPlayingPreview: (v) => set({ isPlayingPreview: v }),
  setPreviewTime: (t) => set({ previewTime: t }),
  loadPreset: (preset: any) => set((s) => ({
    outputFormat: preset.outputFormat ?? s.outputFormat,
    cropZoom: preset.cropZoom ? { ...s.cropZoom, ...preset.cropZoom } : s.cropZoom,
    staticCrop: preset.staticCrop ? { ...s.staticCrop, ...preset.staticCrop } : s.staticCrop,
    videoPosition: preset.videoPosition ? { ...s.videoPosition, ...preset.videoPosition } : s.videoPosition,
    videoEdit: preset.videoEdit ? { ...s.videoEdit, ...preset.videoEdit } : s.videoEdit,
    blurBand: preset.blurBand ? { ...s.blurBand, ...preset.blurBand } : s.blurBand,
    colorGrade: preset.colorGrade ? { ...s.colorGrade, ...preset.colorGrade } : s.colorGrade,
    subtitleStyle: preset.subtitleStyle ? { ...s.subtitleStyle, ...preset.subtitleStyle } : s.subtitleStyle,
    watermarks: preset.watermarks ?? s.watermarks,
    overlays: preset.overlays ?? s.overlays,
    background: preset.background ? { ...s.background, ...preset.background } : s.background,
  })),

  exportProject: () => {
    const s = get();
    return {
      version: '1.0',
      exportedAt: new Date().toISOString(),
      video: {
        source: s.videoFile?.name ?? '',
        info: s.videoInfo,
        outputFormat: s.outputFormat,
        background: s.background,
      },
      cropZoom: s.cropZoom,
      staticCrop: s.staticCrop,
      videoPosition: s.videoPosition,
      videoEdit: s.videoEdit,
      blurBand: s.blurBand,
      colorGrade: s.colorGrade,
      subtitles: {
        style: s.subtitleStyle,
        entries: s.srtEntries,
      },
      overlays: s.overlays,
      watermarks: s.watermarks,
    };
  },
}));
