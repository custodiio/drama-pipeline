import type { SrtEntry } from '../types';


function timeToSeconds(ts: string): number {
  // Format: HH:MM:SS,mmm or HH:MM:SS.mmm
  const clean = ts.replace(',', '.');
  const parts = clean.split(':');
  const h = parseFloat(parts[0]);
  const m = parseFloat(parts[1]);
  const s = parseFloat(parts[2]);
  return h * 3600 + m * 60 + s;
}

export function secondsToTimestamp(secs: number, useComma = true): string {
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = Math.floor(secs % 60);
  const ms = Math.round((secs % 1) * 1000);
  const sep = useComma ? ',' : '.';
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}${sep}${String(ms).padStart(3, '0')}`;
}

export function parseSrt(content: string): SrtEntry[] {
  const blocks = content.trim().split(/\n\s*\n/);
  const entries: SrtEntry[] = [];

  for (const block of blocks) {
    const lines = block.trim().split('\n');
    if (lines.length < 2) continue;

    const id = parseInt(lines[0].trim(), 10);
    const timeParts = lines[1].match(
      /(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})/
    );
    if (!timeParts) continue;

    const startTime = timeToSeconds(timeParts[1]);
    const endTime = timeToSeconds(timeParts[2]);
    const text = lines
      .slice(2)
      .join(' ')
      .replace(/<[^>]+>/g, '')
      .trim();

    if (text) {
      entries.push({ id, startTime, endTime, text });
    }
  }

  return entries;
}

export function getActiveSubtitles(entries: SrtEntry[], currentTime: number): SrtEntry[] {
  return entries.filter((e) => e.startTime <= currentTime && e.endTime >= currentTime);
}

export function getEntriesInRange(entries: SrtEntry[], startTime: number, duration = 10): SrtEntry[] {
  const endTime = startTime + duration;
  return entries.filter((e) => e.startTime < endTime && e.endTime > startTime);
}

export function regroupSrtEntries(entries: SrtEntry[], wordsPerBlock: number): SrtEntry[] {
  if (!entries || entries.length === 0) return [];

  // Primeiro, vamos "achatar" todas as entradas em uma lista de palavras com tempos
  const allWords: { word: string; start: number; end: number }[] = [];
  for (const entry of entries) {
    const words = entry.text.trim().split(/\s+/);
    if (words.length === 0 || !words[0]) continue;
    
    // Distribuir o tempo linearmente pelas palavras do bloco original
    const duration = entry.endTime - entry.startTime;
    const wordDuration = duration / words.length;
    
    for (let i = 0; i < words.length; i++) {
      allWords.push({
        word: words[i],
        start: entry.startTime + i * wordDuration,
        end: entry.startTime + (i + 1) * wordDuration,
      });
    }
  }

  const result: SrtEntry[] = [];
  let currentGroup: typeof allWords = [];
  let idCounter = 1;

  const pushCurrentGroup = () => {
    if (currentGroup.length === 0) return;
    result.push({
      id: idCounter++,
      startTime: currentGroup[0].start,
      endTime: currentGroup[currentGroup.length - 1].end,
      text: currentGroup.map(w => w.word).join(' '),
      words: [...currentGroup],
    });
    currentGroup = [];
  };

  for (let i = 0; i < allWords.length; i++) {
    const w = allWords[i];
    
    // Se o grupo atual estiver vazio, simplesmente adicione
    if (currentGroup.length === 0) {
      currentGroup.push(w);
      continue;
    }
    
    const lastWord = currentGroup[currentGroup.length - 1];
    const gap = w.start - lastWord.end;
    const hasPunctuation = /[.?!:;]$/.test(lastWord.word);
    
    // Fecha o bloco se:
    // 1. Gap > 1s (silêncio longo)
    // 2. A palavra anterior terminar em pontuação (. ? ! : ;)
    if (gap > 1.0 || hasPunctuation) {
      pushCurrentGroup();
      currentGroup.push(w);
      continue;
    }
    
    // Se adicionar esta palavra ultrapassar o limite, fecha o bloco
    if (currentGroup.length >= wordsPerBlock) {
      pushCurrentGroup();
    }
    
    currentGroup.push(w);
  }
  
  // Limpa o último grupo
  pushCurrentGroup();
  
  // Passo 2: Mesclar blocos com menos de 2 palavras (se sobrarem sozinhos) ao bloco anterior
  const finalResult: SrtEntry[] = [];
  for (let i = 0; i < result.length; i++) {
    const current = result[i];
    const wordCount = current.text.trim().split(/\s+/).length;
    
    if (wordCount < 2 && finalResult.length > 0) {
      const prev = finalResult[finalResult.length - 1];
      const gap = current.startTime - prev.endTime;
      
      if (gap <= 1.0) {
        prev.endTime = current.endTime;
        prev.text = prev.text + ' ' + current.text;
        if (prev.words && current.words) {
          prev.words = [...prev.words, ...current.words];
        }
        continue; // Pula a adição do atual
      }
    }
    finalResult.push(current);
  }
  
  // Re-ordenar IDs
  finalResult.forEach((entry, idx) => entry.id = idx + 1);

  return finalResult;
}
