// ─── Estado Global ────────────────────────────────────────────────────────────
const State = {
  roteiro: null,
  identificacao: null,
  analiseRoteiro: null,
  templateSelecionado: null,
  templateSelecionadoIdx: null,
  sessaoExtracao: null,
  framesExtraidos: [],
  framesSelecionados: {},
  visionResultados: {},
  specFinal: null,
  seoToken: null,
  sessaoMode: false,
};

const API = window.location.origin + '/api';

// ─── Init ─────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  setupTabs();
  setupFileInputs();
  setupGuide();
  setupThumb();
  checkHealth();

  const params = new URLSearchParams(window.location.search);
  let token = params.get('token');
  if (token) {
    // Extrai apenas o UUID para evitar erros caso a URL tenha sido colada duplicada
    const uuidMatch = token.match(/[a-f0-9-]{36}/i);
    if (uuidMatch) {
      token = uuidMatch[0];
      State.seoToken = token;
      State.sessaoMode = true;
      
      // Limpa a URL visível no navegador
      window.history.replaceState({}, '', `/?token=${token}`);
      
      await carregarSessao(token);
    }
  }
});

// ─── Health ───────────────────────────────────────────────────────────────────
async function checkHealth() {
  const dot = document.querySelector('.status-dot');
  const txt = dot?.nextElementSibling;
  try {
    await fetch(`${API}/health`);
    dot?.classList.add('ok');
    if (txt) txt.textContent = 'Servidor online';
  } catch {
    dot?.classList.add('err');
    if (txt) txt.textContent = 'Servidor offline';
  }
}

// ─── Tabs ─────────────────────────────────────────────────────────────────────
function setupTabs() {
  document.querySelectorAll('.nav-item').forEach(btn => {
    btn.addEventListener('click', () => {
      const tab = btn.dataset.tab;
      document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById(`tab-${tab}`)?.classList.add('active');
      const titles = { guide: '📋 Guia de Postagem', thumb: '🖼️ Gerador de Capa' };
      document.getElementById('pageTitle').textContent = titles[tab] || '';
    });
  });
}

// ─── File Inputs ──────────────────────────────────────────────────────────────
function setupFileInputs() {
  document.getElementById('inputRoteiro').addEventListener('change', async e => {
    const file = e.target.files[0]; if (!file) return;
    try {
      State.roteiro = JSON.parse(await file.text());
      updateChips();
      toast('Roteiro carregado ✓', 'success');
    } catch { toast('Roteiro inválido', 'error'); }
  });

  document.getElementById('inputIdentificacao').addEventListener('change', async e => {
    const file = e.target.files[0]; if (!file) return;
    try {
      State.identificacao = JSON.parse(await file.text());
      updateChips();
      if (State.identificacao.title) {
        document.querySelector('.page-sub').textContent = State.identificacao.title;
      }
      toast('Identificação carregada ✓', 'success');
    } catch { toast('Identificação inválida', 'error'); }
  });
}

// ─── Carregar Sessão SEO (via token da URL) ─────────────────────────────────
function updateChips() {
  const loaded = (id, ok) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.classList.toggle('loaded', ok);
    el.querySelector('.chip-status').textContent = ok ? '✓ ok' : 'não carregado';
  };

  const rOk = !!State.roteiro;
  const iOk = !!State.identificacao;

  loaded('chipRoteiro', rOk);
  loaded('chipIdentificacao', iOk);
  loaded('chipRoteiroThumb', rOk);
  loaded('chipIdentificacaoThumb', iOk);

  const both = rOk && iOk;
  const btnG = document.getElementById('btnGerarGuia');
  const btnA = document.getElementById('btnAnalisarRoteiro');
  if (btnG) btnG.disabled = !both;
  if (btnA) btnA.disabled = !both;
}

async function carregarSessao(token) {
  try {
    showLoading('Carregando sessão...', 'Buscando dados do projeto no servidor');
    const r = await fetch(`${API}/session/${token}`);
    const data = await r.json();
    if (!data.success) throw new Error(data.error);

    State.roteiro = data.roteiro;
    State.identificacao = data.identificacao;

    // Atualizar UI
    updateChips();
    if (data.identificacao?.title) {
      document.querySelector('.page-sub').textContent = data.identificacao.title;
      document.getElementById('pageTitle').textContent = '🖼️ ' + data.identificacao.title + ' — Thumbnail';
    }

    // Se já tem análise pré-feita, pular para etapa 2
    if (data.analise?.templates_recomendados?.length) {
      State.analiseRoteiro = data.analise;
      // Mudar para aba de Thumbnail diretamente
      document.querySelector('[data-tab="thumb"]')?.click();
      renderTemplates(data.analise);
      goToStep(2);
      toast('🚀 Sessão carregada! Escolha um template.', 'success', 5000);
    } else {
      // Análise ainda não pronta, mostrar aba guide e aguardar
      document.querySelector('[data-tab="thumb"]')?.click();
      toast('⏳ Preparando análise... aguarde alguns segundos e recarregue.', 'info', 6000);
      // Tentar auto-reload a cada 5s até ter análise
      const poll = setInterval(async () => {
        const r2 = await fetch(`${API}/session/${token}`);
        const d2 = await r2.json();
        if (d2.analise?.templates_recomendados?.length) {
          clearInterval(poll);
          State.analiseRoteiro = d2.analise;
          renderTemplates(d2.analise);
          goToStep(2);
          toast('✅ Análise pronta! Escolha um template.', 'success');
        }
      }, 5000);
    }
  } catch (err) {
    toast(`Erro ao carregar sessão: ${err.message}`, 'error');
  } finally {
    hideLoading();
  }
}

// ─── Toast ────────────────────────────────────────────────────────────────────
function toast(msg, type = 'info', dur = 3500) {
  const c = document.getElementById('toastContainer');
  const t = document.createElement('div');
  t.className = `toast ${type}`;
  t.textContent = msg;
  c.appendChild(t);
  setTimeout(() => t.remove(), dur);
}

// ─── Loading ──────────────────────────────────────────────────────────────────
function showLoading(msg, sub = '') {
  document.getElementById('loadingOverlay').classList.remove('hidden');
  document.getElementById('loadingMsg').textContent = msg;
  document.getElementById('loadingSub').textContent = sub;
}
function hideLoading() {
  document.getElementById('loadingOverlay').classList.add('hidden');
}

// ═══════════════════════════════════════════════════════════════════════════════
// FUNÇÃO 1 — GUIA DE POSTAGEM
// ═══════════════════════════════════════════════════════════════════════════════
function setupGuide() {
  document.getElementById('btnGerarGuia').addEventListener('click', gerarGuia);

  document.querySelectorAll('.btn-copy').forEach(btn => {
    btn.addEventListener('click', () => {
      const targetId = btn.dataset.copy;
      const el = document.getElementById(targetId);
      if (!el) return;
      const text = el.innerText || el.textContent;
      navigator.clipboard.writeText(text).then(() => toast('Copiado!', 'success'));
    });
  });
}

async function gerarGuia() {
  if (!State.roteiro || !State.identificacao) return;
  showLoading('Gerando guia com DeepSeek V3...', 'Analisando roteiro e criando conteúdo viral');

  try {
    const r = await fetch(`${API}/generate-guide`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ roteiro: State.roteiro, identificacao: State.identificacao })
    });
    const data = await r.json();
    if (!data.success) throw new Error(data.error);
    renderGuia(data.guia);
    toast('Guia gerado com sucesso!', 'success');
  } catch (err) {
    toast(`Erro: ${err.message}`, 'error');
  } finally {
    hideLoading();
  }
}

function renderGuia(g) {
  document.getElementById('guideResult').classList.remove('hidden');

  // Título principal
  document.getElementById('tituloPrincipal').textContent = g.titulo_principal || '';

  // Títulos alternativos
  const altEl = document.getElementById('titulosAlternativos');
  altEl.innerHTML = (g.titulos_alternativos || []).map((t, i) => `
    <div class="titulo-alt-item">
      <span>${t}</span>
      <button class="btn-copy" onclick="navigator.clipboard.writeText(this.parentElement.querySelector('span').textContent).then(()=>toast('Copiado!','success'))">Copiar</button>
    </div>`).join('');

  // Score viral
  const score = g.score_viral || 0;
  document.getElementById('scoreNumber').textContent = score;
  const offset = 283 - (283 * score / 100);
  document.getElementById('ringFill').style.strokeDashoffset = offset;
  document.getElementById('scoreDetail').textContent =
    score >= 85 ? '🔥 Alta viralização esperada' :
    score >= 70 ? '✅ Bom potencial' : '⚠️ Potencial moderado';

  // Info
  document.getElementById('analiseEmocional').textContent = g.analise_emocional || '';
  document.getElementById('melhorHorario').textContent = g.melhor_horario_postagem || '';
  document.getElementById('audienciaAlvo').textContent = g.audiencia_alvo || '';

  // Descrição
  document.getElementById('descricaoYT').textContent = g.descricao || '';

  // Tags
  const tags = typeof g.tags_youtube === 'string'
    ? g.tags_youtube.split(',').map(t => t.trim()).filter(Boolean)
    : g.tags_youtube || [];
  document.getElementById('tagsYT').innerHTML = tags.map(t =>
    `<span class="tag-chip">${t}</span>`).join('');

  // Hashtags
  document.getElementById('hashtagsYT').innerHTML = (g.hashtags_youtube || []).map(h =>
    `<span class="hashtag-chip">${h}</span>`).join('');

  // Capítulos
  document.getElementById('capitulosList').innerHTML = (g.capitulos || []).map(c =>
    `<div class="chapter-item"><span class="chapter-time">${c.tempo}</span><span>${c.titulo}</span></div>`).join('');

  // Cards
  document.getElementById('cardsList').innerHTML = (g.cards_sugeridos || []).map(c =>
    `<div class="chapter-item"><span class="chapter-time">${c.tempo}</span><span>${c.texto}</span></div>`).join('');

  // CTAs
  document.getElementById('ctaVideo').textContent = g.call_to_action_video || '';
  document.getElementById('ctaDescricao').textContent = g.call_to_action_descricao || '';
}

// ═══════════════════════════════════════════════════════════════════════════════
// FUNÇÃO 2 — GERADOR DE CAPA (STEPPER)
// ═══════════════════════════════════════════════════════════════════════════════
function setupThumb() {
  document.getElementById('btnAnalisarRoteiro').addEventListener('click', analisarRoteiro);

  // Drag & drop vídeo
  const zone = document.getElementById('videoUploadZone');
  zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('dragover'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
  zone.addEventListener('drop', e => {
    e.preventDefault(); zone.classList.remove('dragover');
    const file = e.dataTransfer.files[0];
    if (file) setVideoFile(file);
  });

  document.getElementById('inputVideo').addEventListener('change', e => {
    const file = e.target.files[0];
    if (file) setVideoFile(file);
  });

  document.getElementById('btnClearVideo').addEventListener('click', () => {
    document.getElementById('inputVideo').value = '';
    document.getElementById('videoInfo').classList.add('hidden');
    document.getElementById('videoUploadZone').classList.remove('hidden');
    State._videoFile = null;
    document.getElementById('btnExtrairFrames').disabled = true;
  });

  document.getElementById('btnExtrairFrames')?.addEventListener('click', extrairFrames);
  document.getElementById('btnConfirmarFrames')?.addEventListener('click', analisarFramesSelecionados);
  document.getElementById('btnDownloadThumbnail')?.addEventListener('click', () => {
    const a = document.createElement('a');
    a.href = document.getElementById('renderedThumbnailImage').src;
    a.download = `youtube_thumbnail_${Date.now()}.png`;
    a.click();
  });
  document.getElementById('btnNovaIteracao')?.addEventListener('click', () => goToStep(3));
}

function setVideoFile(file) {
  State._videoFile = file;
  document.getElementById('videoUploadZone').classList.add('hidden');
  const info = document.getElementById('videoInfo');
  info.classList.remove('hidden');
  document.getElementById('videoName').textContent = file.name;
  document.getElementById('videoSize').textContent = `${(file.size / 1024 / 1024).toFixed(1)} MB`;
  document.getElementById('btnExtrairFrames').disabled = false;
}

// ─── Stepper ──────────────────────────────────────────────────────────────────
function goToStep(n) {
  for (let i = 1; i <= 4; i++) {
    const step = document.getElementById(`thumbStep${i}`);
    const ind = document.getElementById(`step${i}-indicator`);
    step?.classList.toggle('active', i === n);
    step?.classList.toggle('hidden', i !== n);
    if (ind) {
      ind.classList.toggle('active', i === n);
      ind.classList.toggle('done', i < n);
    }
  }
}

// ─── Etapa 1: Analisar Roteiro ────────────────────────────────────────────────
async function analisarRoteiro() {
  if (!State.roteiro || !State.identificacao) return;
  showLoading('Analisando roteiro...', 'DeepSeek V3 identificando momentos-chave e templates ideais');

  try {
    const r = await fetch(`${API}/analyze-script`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ roteiro: State.roteiro, identificacao: State.identificacao })
    });
    const data = await r.json();
    if (!data.success) throw new Error(data.error);
    State.analiseRoteiro = data.analise;
    renderTemplates(data.analise);
    goToStep(2);
    toast('Análise concluída!', 'success');
  } catch (err) {
    toast(`Erro: ${err.message}`, 'error');
  } finally {
    hideLoading();
  }
}

// ─── Etapa 2: Renderizar Templates ───────────────────────────────────────────
const TEMPLATE_COLORS = {
  HEROI_REACAO: '#7c6af7', TENSAO_DUAL: '#ef4444',
  OVER_POWERED: '#f97316', STRIP_REACOES: '#22c55e', VIRADA_NARRATIVA: '#f5c518'
};

function renderTemplates(analise) {
  // Suporte a ambos os formatos de resposta da IA
  const resumo = analise.resumo_para_thumbnail || analise.resumo || '';
  const emocao = analise.emocao_dominante || '';
  document.getElementById('resumoRoteiro').innerHTML =
    emocao
      ? `<strong>💫 Emoção dominante:</strong> ${emocao}<br/><strong>📖 Resumo:</strong> ${resumo}`
      : `<strong>📖 Análise:</strong> ${resumo || 'Templates prontos para seleção.'}`;

  const grid = document.getElementById('templatesGrid');
  grid.innerHTML = (analise.templates_recomendados || []).map((t, i) => {
    // Normalizar campos — IA pode retornar template_id OU template
    const templateId = t.template_id || t.template || 'CUSTOM';
    const cor = TEMPLATE_COLORS[templateId] || '#7c6af7';
    // Normalizar texto exibível
    const titulo  = t.titulo    || t.texto_capa  || templateId;
    const motivo  = t.motivo    || t.justificativa || t.descricao || '';
    const score   = t.score != null ? t.score : null;

    const framesHtml = (t.frames_necessarios || []).map(f => {
      const janelas = f.janelas_tempo && f.janelas_tempo.length
        ? f.janelas_tempo
        : [{ inicio: f.timestamp_inicio ?? 0, fim: f.timestamp_fim ?? 0 }];
      const tempos = janelas.map(j => {
        const ini = j.inicio ?? j.start ?? 0;
        const fim = j.fim ?? j.end ?? 0;
        return `[${ini}s–${fim}s]`;
      }).join(' | ');
      const emocao = f.emocao_buscada ? `<span style="color:var(--text-dim);font-size:11px;display:block;margin-top:2px">🎭 ${f.emocao_buscada}</span>` : '';
      return `<div class="frame-needed-chip">📍 <strong>${f.papel_id || f.personagem || '?'}</strong>: ${f.papel_descricao || f.descricao || f.personagem || ''} ${tempos}${emocao}</div>`;
    }).join('');

    const numFrames = (t.frames_necessarios || []).length;

    return `
      <div class="template-card" data-idx="${i}" onclick="selecionarTemplate(${i})">
        ${score != null ? `<span class="template-score">${score}/100</span>` : ''}
        <div class="template-badge" style="background:${cor}22;color:${cor};border:1px solid ${cor}44">${templateId.replace(/_/g, ' ')}</div>
        <div class="template-name">${titulo}</div>
        ${motivo ? `<div class="template-desc">${motivo}</div>` : ''}
        <div style="display:flex;gap:8px;margin:8px 0;flex-wrap:wrap">
          <span style="font-size:11px;padding:3px 8px;border-radius:12px;background:rgba(99,102,241,0.1);border:1px solid rgba(99,102,241,0.2);color:var(--primary)">🎬 ${numFrames} personagen${numFrames > 1 ? 's' : ''}</span>
          ${t.paleta ? `<span style="font-size:11px;padding:3px 8px;border-radius:12px;background:rgba(245,197,24,0.1);border:1px solid rgba(245,197,24,0.2);color:#f5c518">🎨 ${t.paleta}</span>` : ''}
        </div>
        <div class="template-frames-needed">${framesHtml}</div>
      </div>`;
  }).join('');
}

function selecionarTemplate(idx) {
  document.querySelectorAll('.template-card').forEach((c, i) => c.classList.toggle('selected', i === idx));
  State.templateSelecionado = State.analiseRoteiro.templates_recomendados[idx];
  State.templateSelecionadoIdx = idx;

  // Mostrar frames necessários na etapa 3
  renderFramesInfo(State.templateSelecionado.frames_necessarios);
  goToStep(3);

  // Se temos cache de frames para este template, carregar instantaneamente
  if (State.seoToken) {
    carregarFramesCached(idx);
  }

  const templateId = State.templateSelecionado.template_id || State.templateSelecionado.template || 'template';
  toast(`Template "${templateId.replace(/_/g, ' ')}" selecionado`, 'success');
}

async function carregarFramesCached(templateIdx) {
  try {
    showLoading('Carregando frames...', 'Buscando frames pré-extraídos');
    const r = await fetch(`${API}/session/${State.seoToken}/frames/${templateIdx}`);
    const data = await r.json();
    if (!data.success) throw new Error(data.error);

    // Converter formato do cache para o formato esperado pelo renderFramesExtraidos
    const resultados = State.templateSelecionado.frames_necessarios.map(papel => ({
      ...papel,
      frames_extraidos: data.frames[papel.papel_id] || [],
      total: (data.frames[papel.papel_id] || []).length,
    }));

    State.framesExtraidos = resultados;
    State.framesSelecionados = {};
    renderFramesExtraidos(resultados);
    document.getElementById('framesExtraidosContainer').classList.remove('hidden');
    toast(`⚡ ${resultados.reduce((a, r) => a + r.total, 0)} frames já prontos!`, 'success');
  } catch (err) {
    toast(`Frames não prontos ainda, extraindo agora...`, 'info');
  } finally {
    hideLoading();
  }
}

// ─── Etapa 3: Info dos Frames necessários ────────────────────────────────────
function renderFramesInfo(frames) {
  const container = document.getElementById('framesNecessariosInfo');
  container.innerHTML = `
    <h4 style="font-size:14px;color:var(--text2);margin-bottom:10px;">Frames que serão extraídos do vídeo:</h4>
    <div class="frames-info-grid">
      ${frames.map(f => {
        const tempos = (f.janelas_tempo || [{ inicio: f.timestamp_inicio ?? 0, fim: f.timestamp_fim ?? 0 }])
          .map(j => `${j.inicio}s → ${j.fim}s`).join(' / ');
        // Suporte aos dois formatos de campo
        const nome        = f.personagem || f.papel_id || '?';
        const descricao   = f.descricao  || f.emocao_buscada || '';
        return `
        <div class="frame-info-card">
          <div class="frame-info-papel">${f.papel_id.toUpperCase()}</div>
          <div class="frame-info-personagem">👤 ${nome}</div>
          <div class="frame-info-time">⏱ ${tempos}</div>
          ${descricao ? `<div class="frame-info-emocao">${descricao}</div>` : ''}
        </div>`;
      }).join('')}
    </div>`;
}

// ─── Etapa 3: Extrair Frames ──────────────────────────────────────────────────
async function extrairFrames() {
  if (!State._videoFile || !State.templateSelecionado) return;

  const frames = State.templateSelecionado.frames_necessarios;
  showLoading('Extraindo frames do vídeo...', `Processando ${frames.length} janelas de tempo com ffmpeg`);

  try {
    const fd = new FormData();
    fd.append('video', State._videoFile);
    fd.append('frames_config', JSON.stringify(frames));

    const r = await fetch(`${API}/extract-frames`, { method: 'POST', body: fd });
    const data = await r.json();
    if (!data.success) throw new Error(data.error);

    State.sessaoExtracao = data.sessao_id;
    State.framesExtraidos = data.resultados;
    State.framesSelecionados = {};

    renderFramesExtraidos(data.resultados);
    document.getElementById('framesExtraidosContainer').classList.remove('hidden');
    toast(`${data.resultados.reduce((a,r) => a + r.total, 0)} frames extraídos!`, 'success');
  } catch (err) {
    toast(`Erro: ${err.message}`, 'error');
  } finally {
    hideLoading();
  }
}

// ─── Renderizar Grid de Frames ────────────────────────────────────────────────
function renderFramesExtraidos(resultados) {
  const container = document.getElementById('framesPorPapel');
  container.innerHTML = resultados.map(papel => {
    const nome = papel.personagem || papel.papel_id || '?';
    const desc = papel.descricao || papel.papel_descricao || papel.emocao_buscada || '';
    const tempos = (papel.janelas_tempo || [{ inicio: papel.timestamp_inicio ?? 0, fim: papel.timestamp_fim ?? 0 }])
      .map(j => `${j.inicio}s – ${j.fim}s`).join(' / ');
      
    return `
    <div class="papel-section">
      <div class="papel-header">
        <span class="papel-badge">${papel.papel_id.toUpperCase()}</span>
        ${desc ? `<span class="papel-title">${desc}</span>` : ''}
        <span class="papel-time">⏱ ${tempos}</span>
        <span class="papel-desc">👤 ${nome}</span>
      </div>
      <div class="frames-grid" id="grid-${papel.papel_id}">
        ${(papel.frames_extraidos || []).map(f => `
          <div class="frame-card" data-papel="${papel.papel_id}" data-url="${f.url}" data-ts="${f.timestamp}"
               onclick="selecionarFrame('${papel.papel_id}', '${f.url}', ${f.timestamp}, this)">
            <img src="${f.url}" alt="t=${f.timestamp}s" loading="lazy" />
            <div class="frame-timestamp">${f.timestamp}s</div>
            <div class="frame-selected-badge">✓ Selecionado</div>
          </div>`).join('')}
      </div>
    </div>`;
  }).join('');

  atualizarSelecaoResumo();
}

function selecionarFrame(papelId, url, ts, el) {
  // Desmarcar outros do mesmo papel
  document.querySelectorAll(`.frame-card[data-papel="${papelId}"]`).forEach(c => c.classList.remove('selected'));
  el.classList.add('selected');
  State.framesSelecionados[papelId] = { url, timestamp: ts, path: url.replace('/extracted', 'public/extracted') };
  atualizarSelecaoResumo();
}

function atualizarSelecaoResumo() {
  const necessarios = State.templateSelecionado?.frames_necessarios || [];
  const resumo = document.getElementById('selecaoResumo');
  const btn = document.getElementById('btnConfirmarFrames');

  resumo.innerHTML = necessarios.map(f => {
    const sel = State.framesSelecionados[f.papel_id];
    return `<div class="selecao-item ${sel ? 'ok' : 'pending'}">
      ${sel ? '✓' : '○'} <strong>${f.papel_id}</strong> ${sel ? `(${sel.timestamp}s)` : '— aguardando'}
    </div>`;
  }).join('');

  const todos = necessarios.every(f => State.framesSelecionados[f.papel_id]);
  btn.disabled = !todos;

  const status = document.getElementById('selecaoStatus');
  const selecionados = necessarios.filter(f => State.framesSelecionados[f.papel_id]).length;
  status.textContent = todos
    ? `✅ Todos os ${necessarios.length} frames selecionados! Pronto para análise.`
    : `Selecione ${necessarios.length - selecionados} frame(s) ainda pendente(s).`;
}

// ─── Análise Vision dos Frames Selecionados ───────────────────────────────────
async function analisarFramesSelecionados() {
  const necessarios = State.templateSelecionado.frames_necessarios;
  goToStep(4);
  
  // Helper para atualizar status do step
  function setStepLoading(n) {
    const circle = document.getElementById(`plCircle${n}`);
    const status = document.getElementById(`plStatus${n}`);
    const step = document.getElementById(`plStep${n}`);
    const content = document.getElementById(`plContent${n}`);
    circle.classList.add('active');
    step.classList.add('step-active');
    status.className = 'step-status loading';
    status.innerHTML = '<span class="spinner-inline"></span>Processando...';
    content.classList.remove('hidden');
  }
  function setStepDone(n, msg) {
    const circle = document.getElementById(`plCircle${n}`);
    const status = document.getElementById(`plStatus${n}`);
    const step = document.getElementById(`plStep${n}`);
    circle.classList.remove('active');
    circle.classList.add('done');
    circle.innerHTML = '✓';
    step.classList.remove('step-active');
    step.classList.add('step-done');
    status.className = 'step-status complete';
    status.textContent = msg || 'Concluído ✓';
  }
  function setStepError(n, msg) {
    const circle = document.getElementById(`plCircle${n}`);
    const status = document.getElementById(`plStatus${n}`);
    circle.classList.remove('active');
    circle.style.borderColor = 'var(--red)';
    circle.style.color = 'var(--red)';
    circle.innerHTML = '✗';
    status.className = 'step-status';
    status.style.color = 'var(--red)';
    status.textContent = msg || 'Erro';
  }

  // ── ETAPA 1: Validação Vision ──
  setStepLoading(1);
  document.getElementById('visionResultados').innerHTML = '<div style="padding:16px; color:var(--text-dim)"><span class="spinner-inline"></span> Enviando frames para Gemini Vision... aguarde.</div>';

  try {
    const resultados = {};
    for (const f of necessarios) {
      const sel = State.framesSelecionados[f.papel_id];
      if (!sel) continue;

      const r = await fetch(`${API}/analyze-frame`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          frame_path: sel.url,
          papel_id: f.papel_id,
          papel_descricao: f.papel_descricao,
          template: State.templateSelecionado.template,
          emocao_buscada: f.emocao_buscada
        })
      });
      const data = await r.json();
      if (data.success) resultados[f.papel_id] = { frame: sel, analise: data.analise };
      else throw new Error(data.error);
    }

    State.visionResultados = resultados;
    renderVisionResultados(resultados);
    setStepDone(1, `${Object.keys(resultados).length} frames analisados`);
    
    // ── ETAPA 2: Spec JSON ──
    await gerarSpec(setStepLoading, setStepDone, setStepError);
  } catch (err) {
    document.getElementById('visionResultados').innerHTML = `<div style="color:var(--red)">Erro: ${err.message}</div>`;
    setStepError(1, err.message);
    toast(`Erro na Análise Vision: ${err.message}`, 'error');
  }
}

function renderVisionResultados(resultados) {
  const container = document.getElementById('visionResultados');
  container.innerHTML = Object.entries(resultados).map(([papelId, { frame, analise: a }]) => `
    <div class="vision-card">
      <div class="vision-thumb"><img src="${frame.url}" alt="${papelId}" /></div>
      <div>
        <div style="font-size:14px;font-weight:700;margin-bottom:8px;color:var(--accent)">${papelId.toUpperCase()}</div>
        <div class="vision-score-row">
          <span class="vision-score-chip">🎨 Visual: ${a.score_visual}/10</span>
          <span class="vision-score-chip">💫 Emoção: ${a.score_emocao}/10</span>
          <span class="vision-score-chip" style="background:rgba(34,197,94,0.1);border-color:rgba(34,197,94,0.3);color:var(--green)">⭐ Geral: ${a.score_geral}/100</span>
        </div>
        <div class="vision-list" style="margin-top:8px;">
          ${(a.pontos_fortes || []).map(p => `<span class="vision-tag" style="color:var(--green)">✓ ${p}</span>`).join('')}
          ${(a.pontos_fracos || []).map(p => `<span class="vision-tag" style="color:var(--red)">✗ ${p}</span>`).join('')}
        </div>
      </div>
    </div>`).join('');
}

// ─── Etapa 4: Gerar Spec JSON ─────────────────────────────────────────────────
async function gerarSpec(setStepLoading, setStepDone, setStepError) {
  setStepLoading(2);
  document.getElementById('specJson').textContent = 'Consultando DeepSeek V4 Pro... montando blueprint...';

  try {
    const framesSelecionados = Object.entries(State.framesSelecionados).map(([papelId, frame]) => ({
      papel_id: papelId,
      url: frame.url,
      timestamp: frame.timestamp,
      analise: State.visionResultados[papelId]?.analise || {}
    }));

    const r = await fetch(`${API}/generate-thumbnail-spec`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        template: State.templateSelecionado.template,
        frames_selecionados: framesSelecionados,
        analise_roteiro: State.analiseRoteiro,
        identificacao: State.identificacao
      })
    });
    const data = await r.json();
    if (!data.success) throw new Error(data.error);

    State.specFinal = data.spec;
    document.getElementById('specJson').textContent = JSON.stringify(data.spec, null, 2);
    setStepDone(2, 'Blueprint criado');

    // ── ETAPA 3: Gerar Imagem ──
    await gerarThumbnailFinalIA(setStepLoading, setStepDone, setStepError);
  } catch (err) {
    document.getElementById('specJson').textContent = `Erro: ${err.message}`;
    setStepError(2, err.message);
    toast(`Erro no Spec JSON: ${err.message}`, 'error');
  }
}

// ─── Renderizar Capa ───────────────────────────────────────────────────────────
async function gerarThumbnailFinalIA(setStepLoading, setStepDone, setStepError) {
  setStepLoading(3);
  
  const resultImage = document.getElementById('renderedThumbnailImage');
  resultImage.src = ''; // Limpar img anterior
  resultImage.alt = 'Gerando imagem... aguarde...';

  try {
    const framesSelecionados = Object.entries(State.framesSelecionados).map(([papelId, frame]) => ({
      papel_id: papelId,
      url: frame.url,
      path: frame.path,
      timestamp: frame.timestamp
    }));

    const r = await fetch(`${API}/generate-thumbnail`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        token: State.seoToken,
        spec: State.specFinal,
        frames_selecionados: framesSelecionados
      })
    });
    
    const data = await r.json();
    if (!data.success) throw new Error(data.error);

    if (data.images && data.images.length > 0) {
      resultImage.src = data.images[0].url;
      setStepDone(3, 'Capa renderizada!');
      
      toast('Capa gerada com sucesso!', 'success');
      document.getElementById('btnNovaIteracao').classList.remove('hidden');
    } else {
      throw new Error("Nenhuma imagem retornada pela API.");
    }
  } catch (err) {
    resultImage.alt = `Erro: ${err.message}`;
    setStepError(3, err.message);
    toast(`Erro ao gerar thumbnail: ${err.message}`, 'error');
  }
}

