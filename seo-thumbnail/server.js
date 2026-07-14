require("dotenv").config();
const express = require("express");
const cors = require("cors");
const multer = require("multer");
const path = require("path");
const fs = require("fs");
const { v4: uuidv4 } = require("uuid");
const ffmpeg = require("fluent-ffmpeg");
const OpenAI = require("openai");
const { GoogleGenerativeAI } = require("@google/generative-ai");
const { exec } = require("child_process");

const app = express();
const PORT = process.env.PORT || 3333;

// ─── Clientes de IA ───────────────────────────────────────────────────────────
// DeepSeek V3 — melhor custo-benefício para geração de texto
const deepseek = new OpenAI({
  apiKey: process.env.DEEPSEEK_API_KEY,
  baseURL: "https://api.deepseek.com",
});

// OpenAI GPT-4.1 — vision de frames
const openai = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });

// Google Gemini 2.0 Flash — vision de frames (barato e capaz)
const genAI = new GoogleGenerativeAI(process.env.GOOGLE_API_KEY);
const geminiFlash = genAI.getGenerativeModel({
  model: "gemini-3.1-pro-preview",
});
// Google Imagen 3 — geração da thumbnail final
const imagen3 = genAI.getGenerativeModel({
  model: "gemini-3-pro-image-preview",
});

// ─── Diretórios ───────────────────────────────────────────────────────────────
["uploads", "output", "output/specs", "public/extracted"].forEach((d) => {
  if (!fs.existsSync(d)) fs.mkdirSync(d, { recursive: true });
});

// ─── Middleware ───────────────────────────────────────────────────────────────
app.use(cors());
app.use(express.json({ limit: "100mb" }));
app.use(express.static("public"));
app.use("/extracted", express.static("public/extracted"));

const storage = multer.diskStorage({
  destination: (req, file, cb) => cb(null, "uploads/"),
  filename: (req, file, cb) =>
    cb(null, `${uuidv4()}${path.extname(file.originalname)}`),
});
const upload = multer({ storage, limits: { fileSize: 500 * 1024 * 1024 } });

// ─── Helpers ──────────────────────────────────────────────────────────────────
function limparJson(raw) {
  let clean = raw.replace(/<think>[\s\S]*?<\/think>/gi, "");
  
  // Tenta extrair apenas o conteúdo entre a primeira { e a última }
  const firstCurly = clean.indexOf("{");
  const lastCurly = clean.lastIndexOf("}");
  
  if (firstCurly !== -1 && lastCurly !== -1 && lastCurly >= firstCurly) {
    clean = clean.substring(firstCurly, lastCurly + 1);
  }
  
  return clean
    .replace(/^```json\s*/m, "")
    .replace(/^```\s*/m, "")
    .replace(/\s*```$/m, "")
    .trim();
}

// Retry com backoff exponencial para chamadas DeepSeek/IA com Parse Automático
async function callWithRetry(fn, parseFn, maxRetries = 3) {
  const delays = [2000, 5000, 10000];
  for (let i = 0; i < maxRetries; i++) {
    try {
      const result = await fn();
      if (!result || (typeof result === "string" && !result.trim())) {
        throw new Error("Resposta vazia da IA");
      }
      
      const parsed = parseFn ? parseFn(result) : result;
      return parsed;
    } catch (err) {
      console.warn(`[SEO] Tentativa ${i + 1}/${maxRetries} falhou: ${err.message}`);
      const isLast = i === maxRetries - 1;
      if (isLast) throw err;
      await new Promise((resolve) => setTimeout(resolve, delays[i]));
    }
  }
}

// ─── Store de Sessões SEO ─────────────────────────────────────────────────────
// { token: { project_id, chat_id, roteiro, identificacao, analise, frames_cache, created_at } }
const seoSessions = {};

// Pré-cache de extração de frames por sessão
// { token: { [template_idx]: { [papel_id]: frames[] } } }
const framesCache = {};

function extrairFrames(
  videoPath,
  start,
  end,
  sessaoId,
  papelId,
  numFrames = 6,
  duracaoMaxima = 999999,
) {
  return new Promise(async (resolve) => {
    // Forçar conversão para número, caso a IA retorne string como "10s" ou "10.5"
    const startNum = parseFloat(String(start).replace(/[^\d.]/g, '')) || 0;
    const endNum = parseFloat(String(end).replace(/[^\d.]/g, '')) || 0;

    // Garantir que não vamos tentar buscar além do fim do vídeo
    const s = Math.min(startNum, Math.max(0, duracaoMaxima - 2));
    const e = Math.min(endNum, Math.max(0.5, duracaoMaxima - 0.5));

    const duracao = Math.max(e - s, 0.5);
    const intervalo = duracao / (numFrames + 1);
    const timestamps = Array.from(
      { length: numFrames },
      (_, i) => parseFloat((s + intervalo * (i + i)).toFixed(2)), // Fix: spread the interval
    );

    // Recalcular certinho pra evitar timestamps duplicados
    const tsList = [];
    for (let i = 1; i <= numFrames; i++) {
      tsList.push(parseFloat((s + intervalo * i).toFixed(2)));
    }

    const dir = `public/extracted/${sessaoId}/${papelId}`;
    fs.mkdirSync(dir, { recursive: true });

    const extraidos = [];

    if (!tsList.length) return resolve([]);

    // Processar sequencialmente para evitar sobrecarga (15 ffmpegs simultâneos derruba o processo)
    for (let idx = 0; idx < tsList.length; idx++) {
      const ts = tsList[idx];
      const filename = `frame_${String(idx + 1).padStart(2, "0")}_t${ts.toFixed(1)}s.jpg`;
      const outputPath = path.join(dir, filename);
      const urlPath = `/extracted/${sessaoId}/${papelId}/${filename}`;

      await new Promise((res) => {
        ffmpeg(videoPath)
          .seekInput(ts)
          .frames(1)
          .size("1280x720")
          .output(outputPath)
          .on("end", () => {
            extraidos.push({
              idx: idx + 1,
              timestamp: ts,
              url: urlPath,
              path: outputPath,
            });
            res();
          })
          .on("error", (err) => {
            console.error(`❌ Ffmpeg erro ao extrair t=${ts}:`, err.message);
            res(); // Continua pro próximo mesmo se der erro num frame
          })
          .run();
      });
    }

    resolve(extraidos.sort((a, b) => a.idx - b.idx));
  });
}

// ═══════════════════════════════════════════════════════════════════════════════
// ROTA 1 — Guia de Postagem  (DeepSeek V3)
// ═══════════════════════════════════════════════════════════════════════════════
app.post("/api/generate-guide", async (req, res) => {
  try {
    const { roteiro, identificacao } = req.body;
    if (!roteiro || !identificacao)
      return res
        .status(400)
        .json({ error: "roteiro e identificacao são obrigatórios" });

    const narrativa = roteiro
      .filter((s) => s.tipo === "NARRACAO" && s.translated_text)
      .map((s) => s.translated_text)
      .join(" ");

    const prompt = `Você é expert em SEO para YouTube de anime recap em pt-BR, focado em viralização máxima.

ANIME: ${identificacao.title} (${identificacao.title_jp})
PROTAGONISTA: ${identificacao.protagonist}
PERSONAGENS: ${identificacao.characters.join(", ")}
SINOPSE: ${identificacao.synopsis}
NARRAÇÃO: ${narrativa}

Retorne SOMENTE JSON válido, sem markdown, sem explicações:
{
  "titulo_principal": "título hook MÁXIMO — drama, curiosidade, spoiler velado. Ex: ELE ESTAVA MORTO... MAS VOLTOU COM TUDO | Wistoria EP X",
  "titulos_alternativos": ["alt 1", "alt 2", "alt 3"],
  "descricao": "600-900 palavras em pt-BR ultra-otimizado para SEO. Hook no 1º parágrafo, narrativa dramática, CTA forte, timestamps e emojis estratégicos 🔥⚔️😱",
  "hashtags_youtube": ["#Wistoria", "#AnimeRecap"],
  "tags_youtube": "wistoria, wand and sword, anime recap, wistoria react, ...",
  "capitulos": [{"tempo": "0:00", "titulo": "🔥 Intro"}, {"tempo": "0:45", "titulo": "..."}],
  "cards_sugeridos": [{"tempo": "1:30", "texto": "Veja o episódio anterior!"}],
  "momento_gancho_thumbnail": "descrição do momento mais explosivo com timestamp",
  "call_to_action_video": "CTA para dizer no vídeo",
  "call_to_action_descricao": "CTA para a descrição",
  "categoria": "Entretenimento",
  "audiencia_alvo": "fãs de anime 15-28 anos que acompanham a season atual",
  "melhor_horario_postagem": "Sexta 18h ou Sábado 14h (horário de Brasília)",
  "analise_emocional": "3 linhas sobre os picos emocionais",
  "score_viral": 87
}`;

    const completion = await deepseek.chat.completions.create({
      model: "deepseek-v4-pro",
      messages: [{ role: "user", content: prompt }],
      temperature: 0.8,
      max_tokens: 8192,
    });

    const msg = completion.choices[0].message;
    const content = msg?.content || msg?.reasoning_content || "";
    if (!content.trim())
      throw new Error("A API retornou um conteúdo vazio mesmo após aguardar.");

    const guia = JSON.parse(limparJson(content));
    res.json({ success: true, guia });
  } catch (err) {
    console.error("❌ generate-guide:", err.message);
    res.status(500).json({ error: err.message });
  }
});

// ═══════════════════════════════════════════════════════════════════════════════
// ROTA 2 — Análise do Roteiro + Templates  (DeepSeek V3)
// ═══════════════════════════════════════════════════════════════════════════════
app.post("/api/analyze-script", async (req, res) => {
  try {
    const { roteiro, identificacao } = req.body;

    const narrativa = roteiro
      .filter((s) => s.translated_text && s.translated_text.trim())
      .map(
        (s) =>
          `[${s.start.toFixed(1)}s-${s.end.toFixed(1)}s] ${s.translated_text}`,
      )
      .join("\n");

    const prompt = `Você é diretor criativo de thumbnails virais de YouTube para anime.
Analise o roteiro e escolha os TOP 3 templates de capa, identificando janelas de frames a extrair.

ANIME: ${identificacao.title} | PROTAGONISTA: ${identificacao.protagonist}
PERSONAGENS: ${identificacao.characters.join(", ")}

REGRAS OBRIGATÓRIAS PARA EXTRAÇÃO DE CENA:
- Para cada "papel_id" necessário, você DEVE fornecer exatamente 2 janelas de tempo DISTINTAS.
- Exemplo: Se o personagem é o Herói, ache a cena X dele no começo (ex: 1s-5s) e a cena Y dele no final (ex: 120s-130s).
- Isso garante que se um frame estiver ruim na primeira cena, teremos a segunda cena como backup.

ROTEIRO (timestamps em segundos):
${narrativa}

TEMPLATES DISPONÍVEIS:
- HEROI_REACAO: herói em pose épica + personagem reagindo chocado + texto de impacto
- TENSAO_DUAL: dois personagens em confronto lado a lado (A vs B)
- OVER_POWERED: personagem com poder máximo + texto "MODO DEUS" / "NV +999"
- STRIP_REACOES: 3 expressões faciais diferentes lado a lado
- VIRADA_NARRATIVA: frame do twist + rosto surpreso + texto dramático

Retorne SOMENTE JSON válido:
{
  "templates_recomendados": [
    {
      "template": "HEROI_REACAO",
      "score": 95,
      "justificativa": "2 linhas explicando por que este template é ideal para este episódio",
      "texto_capa": "ELE CONSEGUIU!",
      "subtexto": "O sem magia que venceu o impossível",
      "paleta": "dark_gold",
      "frames_necessarios": [
        {
          "papel_id": "hero",
          "papel_descricao": "Herói em momento de triunfo ou determinação",
          "personagem": "Will Serfort",
          "janelas_tempo": [
            {"inicio": 4.0, "fim": 9.0},
            {"inicio": 120.0, "fim": 130.0}
          ],
          "emocao_buscada": "determinação épica, olhar intenso",
          "dica_frame": "buscar expressão com olhar determinado, enquadramento próximo do rosto"
        },
        {
          "papel_id": "reaction",
          "papel_descricao": "Personagem reagindo com choque",
          "personagem": "Edward / Plateia",
          "janelas_tempo": [
            {"inicio": 45.0, "fim": 50.0},
            {"inicio": 165.0, "fim": 178.0}
          ],
          "emocao_buscada": "choque, boca aberta, olhos arregalados",
          "dica_frame": "expressão exagerada de surpresa"
        }
      ]
    }
  ],
  "pico_narrativo": {
    "timestamp_inicio": 164.0,
    "timestamp_fim": 178.0,
    "descricao": "Anúncio épico do diretor que Will pode entrar na torre",
    "emocao": "virada total"
  },
  "emocao_dominante": "superação épica",
  "resumo_para_thumbnail": "2-3 linhas do arco emocional do episódio"
}`;

    const completion = await deepseek.chat.completions.create({
      model: "deepseek-v4-pro",
      messages: [{ role: "user", content: prompt }],
      temperature: 0.7,
      max_tokens: 8192,
    });

    const msg = completion.choices[0].message;
    const content = msg?.content || msg?.reasoning_content || "";
    if (!content.trim())
      throw new Error("A API retornou um conteúdo vazio mesmo após aguardar.");

    const analise = JSON.parse(limparJson(content));
    res.json({ success: true, analise });
  } catch (err) {
    console.error("❌ analyze-script:", err.message);
    res.status(500).json({ error: err.message });
  }
});

// ═══════════════════════════════════════════════════════════════════════════════
// ROTA 3 — Extração de Frames do Vídeo (ffmpeg)
// ═══════════════════════════════════════════════════════════════════════════════
app.post("/api/extract-frames", upload.single("video"), async (req, res) => {
  try {
    if (!req.file) return res.status(400).json({ error: "Vídeo obrigatório." });

    const { frames_config } = req.body;
    if (!frames_config)
      return res.status(400).json({ error: "frames_config é obrigatório." });

    const config = JSON.parse(frames_config);
    const sessaoId = uuidv4();
    const videoPath = req.file.path;

    // Descobrir a duração real do vídeo para evitar buscar frames que não existem
    let duracaoTotal = 999999;
    await new Promise((resolveProbe) => {
      ffmpeg.ffprobe(videoPath, (err, metadata) => {
        if (!err && metadata && metadata.format && metadata.format.duration) {
          duracaoTotal = metadata.format.duration;
        }
        resolveProbe();
      });
    });

    console.log(
      `🎬 Extraindo frames — sessão ${sessaoId} — Vídeo de ${duracaoTotal}s`,
    );

    const resultados = [];
    for (const papel of config) {
      console.log(
        `  → [${papel.papel_id}] Extraindo de ${(papel.janelas_tempo || []).length} janelas de tempo`,
      );

      let allFrames = [];
      const janelas = papel.janelas_tempo || [];

      // Retrocompatibilidade caso o json venha com timestamp antigo
      if (janelas.length === 0 && papel.timestamp_inicio) {
        janelas.push({
          inicio: papel.timestamp_inicio,
          fim: papel.timestamp_fim,
        });
      }

      // Se há múltiplas janelas, queremos extrair 15 frames EXATOS de CADA janela.
      // Ou seja, se a IA indicou 2 janelas, o usuário vai ter 30 frames para escolher!
      const framesPorJanela = 15;

      for (const janela of janelas) {
        const frms = await extrairFrames(
          videoPath,
          janela.inicio,
          janela.fim,
          sessaoId,
          papel.papel_id,
          framesPorJanela,
          duracaoTotal,
        );
        allFrames = allFrames.concat(frms);
      }

      // Ordenar cronologicamente e reajustar IDs
      allFrames.sort((a, b) => a.timestamp - b.timestamp);
      allFrames.forEach((f, idx) => (f.idx = idx + 1));

      resultados.push({
        ...papel,
        frames_extraidos: allFrames,
        total: allFrames.length,
      });
    }

    res.json({
      success: true,
      sessao_id: sessaoId,
      video_path: videoPath,
      resultados,
    });
  } catch (err) {
    console.error("❌ extract-frames:", err.message);
    res.status(500).json({ error: err.message });
  }
});

// ═══════════════════════════════════════════════════════════════════════════════
// ROTA 4 — Análise Vision de Frame  (Gemini 2.0 Flash — barato e capaz)
// ═══════════════════════════════════════════════════════════════════════════════
app.post("/api/analyze-frame", async (req, res) => {
  try {
    const { frame_path, papel_id, papel_descricao, template, emocao_buscada } =
      req.body;
    if (!frame_path)
      return res.status(400).json({ error: "frame_path é obrigatório." });

    const resolvedPath = frame_path.startsWith("/")
      ? `public${frame_path}`
      : frame_path;
    if (!fs.existsSync(resolvedPath))
      return res
        .status(404)
        .json({ error: `Frame não encontrado: ${resolvedPath}` });

    const imageData = fs.readFileSync(resolvedPath).toString("base64");

    const prompt = `Você é especialista em composição visual de thumbnails virais de YouTube para anime.
Analise este frame e avalie seu potencial para o papel "${papel_id}" no template "${template}".
Papel: ${papel_descricao} | Emoção buscada: ${emocao_buscada || "qualquer"}

Retorne SOMENTE JSON válido:
{
  "aprovado": true,
  "score_visual": 8,
  "score_emocao": 9,
  "score_geral": 85,
  "personagens_detectados": [{"nome": "Will Serfort", "posicao": "centro", "emocao": "determinação", "expressao": "olhar intenso"}],
  "composicao": {"cores_dominantes": ["#1a2b3c", "#f5c518"], "iluminacao": "dramática", "enquadramento": "plano médio"},
  "crop_recomendado": {"x_pct": 5, "y_pct": 0, "w_pct": 90, "h_pct": 100, "justificativa": "Remove bordas escuras"},
  "ajustes": {"brilho": 1.1, "contraste": 1.25, "saturacao": 1.3, "nitidez": 1.1},
  "pontos_fortes": ["expressão intensa", "iluminação dramática"],
  "pontos_fracos": ["leve desfoque"],
  "recomendacao": "Excelente frame — expressão de triunfo bem definida"
}`;

    const analise = await callWithRetry(
      async () => {
        const result = await geminiFlash.generateContent([
          { inlineData: { data: imageData, mimeType: "image/jpeg" } },
          prompt,
        ]);
        return result.response.text();
      },
      (rawText) => {
        const cleaned = limparJson(rawText);
        return JSON.parse(cleaned);
      },
      3
    );
    res.json({ success: true, frame_path, analise });
  } catch (err) {
    console.error("❌ analyze-frame:", err.message);
    res.status(500).json({ error: err.message });
  }
});

// ═══════════════════════════════════════════════════════════════════════════════
// ROTA 5 — Gerar Spec JSON da Thumbnail  (DeepSeek V3)
// ═══════════════════════════════════════════════════════════════════════════════
app.post("/api/generate-thumbnail-spec", async (req, res) => {
  try {
    const { template, frames_selecionados, analise_roteiro, identificacao } =
      req.body;

    const textoPrincipal =
      analise_roteiro?.templates_recomendados?.[0]?.texto_capa ||
      "TEXTO PRINCIPAL";
    const subtexto =
      analise_roteiro?.templates_recomendados?.[0]?.subtexto || "";

    const prompt = `Você é diretor de arte de thumbnails virais de YouTube para anime.
Gere o SPEC JSON de composição para renderização com Python/Pillow.

TEMPLATE: ${template} | ANIME: ${identificacao?.title || "Anime"}
TEXTO CAPA: "${textoPrincipal}" | SUBTEXTO: "${subtexto}"
FRAMES ANALISADOS: ${JSON.stringify(frames_selecionados, null, 2)}
CONTEXTO: ${analise_roteiro?.resumo_para_thumbnail || ""}

Regras por template:
- HEROI_REACAO: hero_frame ocupa 65% esquerda, reaction_frame 35% direita sobreposto
- TENSAO_DUAL: dois frames lado a lado separados por linha de tensão central
- OVER_POWERED: frame central com efeitos de aura e energia irradiando
- STRIP_REACOES: 3 frames em coluna vertical à direita, texto à esquerda
- VIRADA_NARRATIVA: frame grande com texto dramático sobreposto e seta ou relâmpago

Instruções de Inteligência e Adaptação dos Frames:
- Contorne falhas nos frames: se o frame selecionado não tiver o personagem exato, adapte o foco para o elemento principal da cena.
- Remoção de distrações: instrua a IA a remover personagens secundários ou expressões calmas que distoem da dramaticidade.
- Recortes em vez de "quadradões": prefira indicar recortes focados apenas na silhueta/corpo do personagem principal, removendo fundos inúteis.
- Emoções, Poses e Ajustes: instrua a modificação de reações e poses se o frame for apático. Indique a adição de pequenos detalhes nas bordas se o frame estiver levemente cortado.

Retorne SOMENTE JSON válido. Você deve ser extremamente criativo e adicionar camadas extras de 'vetor' (como relâmpagos, setas) e 'efeito_facial' (sorriso sinistro, sombras, olhos brilhantes) dependendo do contexto.
Use esta estrutura base como inspiração para o quão detalhado você deve ser:

{
  "spec_version": "2.0",
  "template": "${template}",
  "canvas": {"width": 1280, "height": 720},
  "camadas": [
    {"id": "bg", "tipo": "gradiente", "ordem": 1, "cores": ["#0a0a1a", "#1a0a2e"], "direcao": "diagonal"},
    {"id": "hero_frame", "tipo": "imagem_frame", "ordem": 2, "papel_id": "hero",
      "posicao_canvas": {"x": 0, "y": 0, "w": 830, "h": 720},
      "crop": {"x_pct": 5, "y_pct": 0, "w_pct": 85, "h_pct": 100, "justificativa": "foco no rosto"},
      "ajustes": {"brilho": 1.1, "contraste": 1.25, "saturacao": 1.3},
      "efeito_borda": "fade_right",
      "nota_edicao": "Instruções de edição e clima."},
    {"id": "efeito_drama", "tipo": "efeito_facial", "ordem": 3,
      "descricao": "Adicionar sorriso sinistro e sombras",
      "parametros": {"adicionar_sorriso": true, "intensidade_sorriso": 0.85, "adicionar_sombras_olhos": true},
      "regiao_alvo_aproximada": "rosto central"},
    {"id": "relampago", "tipo": "vetor", "ordem": 4,
      "posicao_canvas": {"x": 680, "y": 150, "w": 300, "h": 400},
      "path": "M 700 200 L 750 300 L 730 320 L 800 450",
      "estilo": {"preenchimento": "none", "traco": "#FFD700", "largura_traco": 5, "brilho": {"cor": "#FFD700", "intensidade": 0.9, "raio": 15}},
      "transform": {"rotacao": -5, "escala": 1}},
    {"id": "texto_principal", "tipo": "texto", "ordem": 5,
      "conteudo": "${textoPrincipal !== "TEXTO PRINCIPAL" ? textoPrincipal : "Crie um texto chamativo"}",
      "posicao_canvas": {"x": 820, "y": 60, "w": 430, "h": 160},
      "fonte": {"familia": "Impact", "tamanho": 78, "peso": "black"},
      "cor_texto": "#FFD700",
      "outline": {"cor": "#000000", "espessura": 5},
      "sombra": {"cor": "#000000", "x": 4, "y": 4, "blur": 10}},
    {"id": "subtexto", "tipo": "texto", "ordem": 6,
      "conteudo": "${subtexto !== "" ? subtexto : "Crie um subtitulo"}",
      "posicao_canvas": {"x": 820, "y": 230, "w": 430, "h": 90},
      "fonte": {"familia": "Arial Black", "tamanho": 26, "peso": "bold"},
      "cor_texto": "#FFFFFF",
      "outline": {"cor": "#000000", "espessura": 3}}
  ],
  "efeitos_globais": {"vignette": 0.35, "color_grade": "dramatic_dark"},
  "paleta": {"nome": "dark_gold", "primaria": "#FFD700", "secundaria": "#FF6B35", "fundo": "#0a0a1a"},
  "export": {"formato": "PNG", "qualidade": 95, "resolucao": "1280x720"},
  "metadata": {"anime": "${identificacao?.title || ""}", "template": "${template}", "gerado_em": "${new Date().toISOString()}"}
}`;

    const spec = await callWithRetry(
      async () => {
        const completion = await deepseek.chat.completions.create({
          model: "deepseek-v4-pro",
          messages: [{ role: "user", content: prompt }],
          temperature: 0.5,
          max_tokens: 8192,
          response_format: { type: "json_object" }
        });
        const msg = completion.choices[0].message;
        return msg?.content || msg?.reasoning_content || "";
      },
      (rawText) => {
        const cleaned = limparJson(rawText);
        return JSON.parse(cleaned);
      },
      3
    );

    const specFile = `output/specs/spec_${Date.now()}.json`;
    fs.writeFileSync(specFile, JSON.stringify(spec, null, 2));

    res.json({ success: true, spec, spec_file: specFile });
  } catch (err) {
    console.error("❌ generate-thumbnail-spec:", err.message);
    res.status(500).json({ error: err.message });
  }
});

// ═══════════════════════════════════════════════════════════════════════════════
// ROTA 6 — Gerar Thumbnail Final (IA Gemini / Imagen 3)
// ═══════════════════════════════════════════════════════════════════════════════
app.post("/api/generate-thumbnail", async (req, res) => {
  try {
    const { token, spec, frames_selecionados } = req.body;
    if (!spec) return res.status(400).json({ error: "spec é obrigatório." });

    // Lendo os frames como Base64 para enviar pra IA
    const imageParts = [];
    if (frames_selecionados && frames_selecionados.length > 0) {
      for (const f of frames_selecionados) {
        const p = f.path;
        if (p && fs.existsSync(p)) {
          const b64 = fs.readFileSync(p).toString("base64");
          imageParts.push({
            inlineData: { data: b64, mimeType: "image/jpeg" },
          });
        }
      }
    }

    const promptText = `
Você é um diretor de arte. Gere a arte final da thumbnail do YouTube baseada nos frames fornecidos e neste SPEC JSON de composição:
${JSON.stringify(spec, null, 2)}

**ANÁLISE PRÉVIA DOS FRAMES (USE ISSO PARA SABER O QUE CORRIGIR):**
${JSON.stringify(
  frames_selecionados.map((f) => ({
    papel: f.papel_id,
    analise_vision: f.analise, // ou o objeto que contiver os dados no seu frontend
  })),
  null,
  2,
)}

Instruções:
- Utilize os frames fornecidos como base criativa, mas seja muito inteligente na adaptação.
- Contorne falhas nos frames: se o frame não mostrar a imagem perfeita, adapte e use o elemento mais em foco.
- Isole os elementos: não use recortes "quadradões". Faça um recorte inteligente, focando apenas no personagem.
- Remova distrações: se houver personagens de fundo, calmos ou indesejados que distoem da cena dramática, remova-os completamente.
- Adicione detalhes: se o personagem do frame estiver com alguma parte cortada nas bordas, adicione pequenos detalhes para preencher o que falta.
- Emoções e Poses: você tem total liberdade para mudar poses, criar novas reações faciais e alterar emoções para deixá-las dramáticas e impactantes, caso o frame base seja apático.
- Aplique o texto, cores, fontes e estilo exatos definidos no JSON.
- A imagem deve ter qualidade ultra-dramática, estilo anime, proporção 16:9.
- Sem marcas d'água.
`;

    // Tentativa com gemini-3-pro-image-preview
    const imgModel = genAI.getGenerativeModel({
      model: "gemini-3-pro-image-preview",
    });

    const ensureOutputDir = () => {
      if (!fs.existsSync("output")) fs.mkdirSync("output", { recursive: true });
    };
    ensureOutputDir();

    // Como é modelo imagem-preview, vamos tentar via generateContent
    // ou se falhar, gerar via openAI fallback
    let saved = [];
    try {
      const result = await imgModel.generateContent([
        promptText,
        ...imageParts,
      ]);
      const responsePart =
        result?.response?.candidates?.[0]?.content?.parts?.[0];

      if (responsePart && responsePart.inlineData) {
        const filename = `thumbnail_ai_${Date.now()}.png`;
        const filepath = `output/${filename}`;
        const base64Data = responsePart.inlineData.data;
        fs.writeFileSync(filepath, Buffer.from(base64Data, "base64"));
        saved.push({ url: `/output-img/${filename}`, path: filepath });
      } else {
        throw new Error(
          "SDK não retornou bytes binários na resposta do generateContent",
        );
      }
    } catch (imgErr) {
      console.warn("⚠️ Fallback DALL-E 3 ativado:", imgErr.message);

      const response = await openai.images.generate({
        model: "dall-e-3",
        prompt: promptText.substring(0, 950), // limite do dalle
        n: 1,
        size: "1792x1024",
        quality: "hd",
      });
      const imageUrl = response.data[0].url;
      const imgRes = await fetch(imageUrl);
      const buffer = Buffer.from(await imgRes.arrayBuffer());
      const filename = `thumbnail_dalle_${Date.now()}.png`;
      const filepath = `output/${filename}`;
      fs.writeFileSync(filepath, buffer);
      saved.push({ url: `/output-img/${filename}`, path: filepath });
    }

    // Enviar para o Telegram se houver token e chat_id
    if (token) {
      const session = seoSessions[token];
      if (session && session.telegram_token && session.chat_id && saved.length > 0) {
        try {
          const finalImagePath = saved[0].path;
          const formData = new FormData();
          const fileBuffer = fs.readFileSync(finalImagePath);
          const fileBlob = new Blob([fileBuffer], { type: 'image/png' });
          formData.append('chat_id', session.chat_id);
          formData.append('photo', fileBlob, 'thumbnail.png');
          
          let caption = "✅ *Thumbnail Finalizada!*\n\n";
          if (session.guia && session.guia.descricao) {
             caption += `📝 *Descrição SEO:*\n${session.guia.descricao}\n\n`;
          }
          if (session.guia && session.guia.hashtags_youtube) {
             caption += session.guia.hashtags_youtube.join(" ");
          }
          formData.append('caption', caption);
          formData.append('parse_mode', 'Markdown');

          await fetch(`https://api.telegram.org/bot${session.telegram_token}/sendPhoto`, {
            method: 'POST',
            body: formData
          });
        } catch (tgErr) {
          console.error("❌ Erro ao enviar thumbnail para o Telegram:", tgErr.message);
        }
      }
    }

    return res.json({
      success: true,
      images: saved,
    });
  } catch (err) {
    console.error("❌ generate-thumbnail:", err.message);
    res.status(500).json({ error: err.message });
  }
});

// Servir thumbnails geradas
app.use("/output-img", express.static("output"));

// ═══════════════════════════════════════════════════════════════════════════════
// ROTA 7 — Criar Sessão SEO (chamado pelo bot Python)
// ═══════════════════════════════════════════════════════════════════════════════
app.post("/api/create-seo-session", (req, res) => {
  const { project_id, chat_id, roteiro, identificacao, telegram_token, message_id, guia } = req.body;
  if (!project_id || !roteiro || !identificacao)
    return res
      .status(400)
      .json({ error: "project_id, roteiro e identificacao são obrigatórios" });

  const token = uuidv4();
  seoSessions[token] = {
    project_id,
    chat_id,
    roteiro,
    identificacao,
    telegram_token: telegram_token || null,
    message_id: message_id || null,
    guia: guia || null,
    analise: null,
    created_at: Date.now(),
  };
  console.log(`[SEO] Sessão criada: ${token} para projeto ${project_id}`);
  res.json({ success: true, token });
});

// ═══════════════════════════════════════════════════════════════════════════════
// ROTA 8 — Carregar Sessão SEO (chamado pelo frontend)
// ═══════════════════════════════════════════════════════════════════════════════
app.get("/api/session/:token", (req, res) => {
  const session = seoSessions[req.params.token];
  if (!session)
    return res.status(404).json({ error: "Sessão não encontrada ou expirada" });
  res.json({
    success: true,
    project_id: session.project_id,
    identificacao: session.identificacao,
    roteiro: session.roteiro,
    analise: session.analise,
    has_frames_cache: !!framesCache[req.params.token],
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// ROTA 9 — Gerar Guia SEO automático (chamado pelo bot após cel5)
// ═══════════════════════════════════════════════════════════════════════════════
app.post("/api/auto-guide", async (req, res) => {
  try {
    const { roteiro, identificacao } = req.body;
    if (!roteiro || !identificacao)
      return res
        .status(400)
        .json({ error: "roteiro e identificacao são obrigatórios" });

    const narrativa = roteiro
      .filter((s) => s.tipo === "NARRACAO" && s.translated_text)
      .map((s) => s.translated_text)
      .join(" ");

    const prompt = `Você é expert em SEO para YouTube de anime recap em pt-BR, focado em viralização máxima.

ANIME: ${identificacao.title} (${identificacao.title_jp || ""})
PROTAGONISTA: ${identificacao.protagonist}
PERSONAGENS: ${(identificacao.characters || []).join(", ")}
SINOPSE: ${identificacao.synopsis}
NARRAÇÃO: ${narrativa}

Retorne SOMENTE JSON válido, sem markdown, sem explicações:
{
  "titulo_principal": "título hook MÁXIMO — drama, curiosidade, spoiler velado",
  "titulos_alternativos": ["alt 1", "alt 2", "alt 3"],
  "descricao": "600-900 palavras em pt-BR ultra-otimizado para SEO. Hook no 1º parágrafo, narrativa dramática, CTA forte, timestamps e emojis estratégicos 🔥⚔️😱",
  "hashtags_youtube": ["#Anime", "#AnimeRecap"],
  "tags_youtube": "anime, anime recap, ...",
  "score_viral": 87
}`;

    const content = await callWithRetry(async () => {
      const completion = await deepseek.chat.completions.create({
        model: "deepseek-v4-pro",
        messages: [{ role: "user", content: prompt }],
        temperature: 0.8,
        max_tokens: 4096,
      });
      const msg = completion.choices[0].message;
      return msg?.content || msg?.reasoning_content || "";
    });

    const guia = JSON.parse(limparJson(content));

    // Salvar JSON para uso futuro
    const outPath = `output/guia_seo_${Date.now()}.json`;
    fs.writeFileSync(
      outPath,
      JSON.stringify(
        { guia, identificacao, gerado_em: new Date().toISOString() },
        null,
        2,
      ),
    );

    res.json({ success: true, guia, saved_path: outPath });
  } catch (err) {
    console.error("❌ auto-guide:", err.message);
    res.status(500).json({ error: err.message });
  }
});

// ═══════════════════════════════════════════════════════════════════════════════
// ROTA 10 — Pré-Análise + Pré-Extração de Frames (background, chamado pelo bot)
// ═══════════════════════════════════════════════════════════════════════════════
app.post("/api/pre-analyze", async (req, res) => {
  try {
    const { token, video_path } = req.body;
    const session = seoSessions[token];
    if (!session)
      return res.status(404).json({ error: "Sessão não encontrada" });
    if (!video_path || !fs.existsSync(video_path))
      return res
        .status(400)
        .json({ error: `Vídeo não encontrado: ${video_path}` });

    // Responde imediatamente — executa em background
    res.json({ success: true, message: "Pré-análise iniciada em background" });

    const updateTelegram = async (text) => {
      if (session.telegram_token && session.chat_id && session.message_id) {
        try {
          await fetch(`https://api.telegram.org/bot${session.telegram_token}/editMessageText`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              chat_id: session.chat_id,
              message_id: session.message_id,
              text: text,
              parse_mode: 'Markdown'
            })
          });
        } catch (e) {
          console.error('[SEO] Erro ao atualizar Telegram:', e.message);
        }
      }
    };

    // 1. Analisar roteiro para obter os 3 templates
    const narrativa = session.roteiro
      .filter((s) => s.translated_text && s.translated_text.trim())
      .map(
        (s) =>
          `[${s.start?.toFixed(1) || 0}s-${s.end?.toFixed(1) || 0}s] ${s.translated_text}`,
      )
      .join("\n");

    const prompt = `Você é diretor criativo de thumbnails virais de YouTube para anime.
ANIME: ${session.identificacao.title} | PROTAGONISTA: ${session.identificacao.protagonist}
PERSONAGENS: ${(session.identificacao.characters || []).join(", ")}

REGRAS: Para cada papel_id, forneça 2 janelas de tempo DISTINTAS.

ROTEIRO:
${narrativa}

TEMPLATES: HEROI_REACAO, TENSAO_DUAL, OVER_POWERED, STRIP_REACOES, VIRADA_NARRATIVA

Retorne SOMENTE JSON válido. O formato OBRIGATÓRIO do root element deve ser um objeto contendo a chave "templates_recomendados" com um array dos top 3 templates. Cada template deve ter "template", "descricao" e "frames_necessarios". Cada "frames_necessarios" deve ter "papel_id", "papel_descricao", "emocao_buscada", e "janelas_tempo" (com "start" e "end").`;

    let analise;
    try {
      analise = await callWithRetry(
        async () => {
          const completion = await deepseek.chat.completions.create({
            model: "deepseek-v4-pro",
            messages: [{ role: "user", content: prompt }],
            temperature: 0.7,
            max_tokens: 4096,
            response_format: { type: "json_object" }
          });
          const msg = completion.choices[0].message;
          return msg?.content || msg?.reasoning_content || "";
        },
        (rawContent) => {
          const cleaned = limparJson(rawContent);
          console.log(`[SEO] JSON limpo (primeiros 300 chars): ${cleaned.substring(0, 300)}`);
          return JSON.parse(cleaned);
        },
        3
      );
      session.analise = analise;
      console.log(
        `[SEO] Análise concluída para sessão ${token}: ${analise.templates_recomendados?.length} templates`,
      );
      await updateTelegram("⏳ *extraindo frames*");
    } catch (err) {
      console.error(`[SEO] Erro na análise: ${err.message}`);
      await updateTelegram("❌ Erro ao gerar thumbnails (análise falhou).");
      return;
    }

    // 2. Pré-extrair frames das 3 opções de template em paralelo
    let duracaoTotal = 999999;
    await new Promise((r) =>
      ffmpeg.ffprobe(video_path, (err, meta) => {
        if (!err && meta?.format?.duration) duracaoTotal = meta.format.duration;
        r();
      }),
    );

    framesCache[token] = {};
    const templates = analise.templates_recomendados || [];

    for (let ti = 0; ti < templates.length; ti++) {
      const tmpl = templates[ti];
      framesCache[token][ti] = {};
      for (const papel of tmpl.frames_necessarios || []) {
        let allFrames = [];
        for (const janela of papel.janelas_tempo || []) {
          // Normalizar: aceita tanto inicio/fim (pt-BR) quanto start/end (en)
          const jInicio = janela.inicio ?? janela.start ?? 0;
          const jFim = janela.fim ?? janela.end ?? 0;
          const frames = await extrairFrames(
            video_path,
            jInicio,
            jFim,
            `${token}_t${ti}`,
            papel.papel_id,
            15,
            duracaoTotal,
          );
          allFrames = allFrames.concat(frames);
        }
        allFrames.sort((a, b) => a.timestamp - b.timestamp);
        framesCache[token][ti][papel.papel_id] = allFrames;
      }
      console.log(`[SEO] Template ${ti} pré-extraído para sessão ${token}`);
    }
    console.log(`[SEO] Pré-extração completa para sessão ${token}`);
    await updateTelegram(`✅ *sua sessão esta pronta acesse:*\nhttp://localhost:3333/?token=${token}`);
  } catch (err) {
    console.error("❌ pre-analyze:", err.message);
    try {
      if (session.telegram_token && session.chat_id && session.message_id) {
        await fetch(`https://api.telegram.org/bot${session.telegram_token}/editMessageText`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ chat_id: session.chat_id, message_id: session.message_id, text: "❌ Erro na pré-extração." })
        });
      }
    } catch (e) {}
  }
});

// ═══════════════════════════════════════════════════════════════════════════════
// ROTA 11 — Obter frames pré-extraídos para um template específico
// ═══════════════════════════════════════════════════════════════════════════════
app.get("/api/session/:token/frames/:template_idx", (req, res) => {
  const { token, template_idx } = req.params;
  const cache = framesCache[token];
  if (!cache)
    return res.status(404).json({ error: "Frames ainda não prontos, aguarde" });
  const templateFrames = cache[parseInt(template_idx)];
  if (!templateFrames)
    return res.status(404).json({ error: "Template não encontrado no cache" });
  res.json({ success: true, frames: templateFrames });
});

// ─── Health ───────────────────────────────────────────────────────────────────
app.get("/api/health", (req, res) =>
  res.json({ ok: true, ts: new Date().toISOString() }),
);

app.listen(PORT, () =>
  console.log(`\n🚀 SEO AnimeRecap → http://localhost:${PORT}\n`),
);
