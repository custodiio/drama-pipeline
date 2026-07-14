// Shared types used across store and utils - no circular dependencies

export interface ExtractedFrame {
  id: string;
  timeSeconds: number;
  dataUrl: string;
}

export interface VideoInfo {
  fileName: string;
  width: number;
  height: number;
  duration: number;
  fps: number;
  aspect: string;
}

export interface SrtEntry {
  id: number;
  startTime: number;
  endTime: number;
  text: string;
  words?: { word: string; start: number; end: number }[];
}
