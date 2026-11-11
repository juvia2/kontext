// kontext 화면. 서버가 보낸 값은 모두 textContent로만 넣는다(HTML로 해석하지 않는다).
const $ = id => document.getElementById(id);
const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
};
const add = (parent, tag, className, text) => parent.appendChild(el(tag, className, text));

const EXAMPLES = {
  fix: '어제 책이 읽었어요. 근데 정말 재미있었어요.',
  clean: '주말에 친구를 만나서 같이 저녁을 먹을 거예요.',
};
const CATEGORY = { particle: '조사', ending: '어미', tense: '시제', honorific: '높임·말투', pattern: '문형', word: '어휘', spelling: '맞춤법' };
const JUDGMENT = { error: '오류', less_natural: '덜 자연스러움', acceptable: '괜찮음', uncertain: '판단 보류' };
const STEPS = [
  { key: 'input', name: '입력 확인', who: '코드', file: 'src/pipeline.py' },
  { key: 'profile', name: '학습 기록 읽기', who: '코드', file: 'src/learner.py' },
  { key: 'analysis', name: '문장 분석', who: '모델', file: 'src/llm.py' },
  { key: 'retrieval', name: '문법 근거 검색', who: '코드', file: 'src/rag.py' },
  { key: 'generation', name: '피드백과 문제 생성', who: '모델', file: 'src/llm.py' },
  { key: 'tools', name: '검증 후 저장', who: '코드', file: 'src/learner.py' },
];

// 로그인 대신 브라우저마다 임의의 학습자 ID를 하나 만들어 둔다.
const ID_KEY = 'kontext-learner-id';
let learnerId = null;
try { learnerId = localStorage.getItem(ID_KEY); } catch { /* 저장소를 못 쓰면 이번 방문에만 쓰는 ID */ }
if (!learnerId || !/^demo-[a-f0-9-]{32,36}$/.test(learnerId)) {
  const random = crypto.randomUUID ? crypto.randomUUID()
    : Array.from(crypto.getRandomValues(new Uint8Array(16)), b => b.toString(16).padStart(2, '0')).join('');
  learnerId = `demo-${random}`;
  try { localStorage.setItem(ID_KEY, learnerId); } catch { /* 무시 */ }
}

const utterance = $('utterance');
const analyzeButton = $('analyze');
const layout = $('view-write');
let configured = false;
let busy = false;

// ── 공통 ────────────────────────────────────────────────
function notice(message) {
  $('notice').textContent = message || '';
  $('notice').hidden = !message;
}
function refreshButton() {
  $('count').textContent = `${utterance.value.length} / ${utterance.maxLength}`;
  analyzeButton.disabled = busy || !configured || !utterance.value.trim();
  analyzeButton.textContent = busy ? '살펴보는 중' : '살펴보기';
}
async function api(url, options) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '요청을 처리하지 못했습니다.');
  return data;
}
function showView(name) {
  $('view-write').hidden = name !== 'write';
  $('view-record').hidden = name !== 'record';
  document.querySelectorAll('[data-view]').forEach(tab => {
    if (tab.dataset.view === name) tab.setAttribute('aria-current', 'page');
    else tab.removeAttribute('aria-current');
  });
  window.scrollTo(0, 0);
}
const seconds = ms => (ms >= 1000 ? `${(ms / 1000).toFixed(1)}초` : `${Math.round(ms)}ms`);
function arrow() {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('width', '22'); svg.setAttribute('height', '22');
  svg.setAttribute('fill', 'none'); svg.setAttribute('stroke', '#5c6066'); svg.setAttribute('stroke-width', '2');
  svg.setAttribute('stroke-linecap', 'round'); svg.setAttribute('stroke-linejoin', 'round'); svg.setAttribute('aria-hidden', 'true');
  const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  path.setAttribute('d', 'M5 12h14M13 6l6 6-6 6');
  svg.appendChild(path);
  return svg;
}

// ── 분석 과정 패널 ──────────────────────────────────────
const stepNodes = {};
function resetProcess() {
  $('steps').replaceChildren();
  $('totals').replaceChildren();
  STEPS.forEach((step, index) => {
    const item = add($('steps'), 'li', 'step pending');
    add(item, 'span', 'step-no', String(index + 1).padStart(2, '0'));
    const body = add(item, 'div', 'step-body');
    const head = add(body, 'div', 'step-head');
    const title = add(head, 'h3', '', step.name);
    add(title, 'span', step.who === '모델' ? 'who model' : 'who', step.who);
    const state = add(head, 'span', 'step-state', '대기');
    const detail = add(body, 'div', 'step-body');
    stepNodes[step.key] = { item, state, detail, meta: step };
  });
  $('process').hidden = false;
  layout.classList.add('with-process');
}
function row(parent, left, right, rightClass) {
  const line = add(parent, 'div', 'step-row');
  add(line, 'span', '', left);
  add(line, 'span', rightClass || '', right);
}
function describeStep(key, data, parent, findings) {
  if (key === 'input') add(parent, 'p', 'step-line', `${data.length}자 · 길이와 형식 통과`);
  if (key === 'profile') {
    const counts = Object.entries(data.category_counts || {}).map(([k, n]) => `${CATEGORY[k] || k} ${n}회`);
    add(parent, 'p', 'step-line', `수준 ${data.level} · ${counts.length ? `이전 기록: ${counts.join(', ')}` : '이전 기록 없음'}`);
  }
  if (key === 'analysis') {
    if (data.attempts > 1) add(parent, 'p', 'step-line', `응답 형식이 맞지 않아 ${data.attempts}번 요청함`);
    if (!data.findings.length) add(parent, 'p', 'step-line', '살펴볼 표현을 고르지 않음');
    for (const f of data.findings) {
      const change = f.judgment === 'error' || f.judgment === 'less_natural' ? `${f.expression} → ${f.suggestion}` : f.expression;
      const tone = f.judgment === 'error' ? 'c-error' : f.judgment === 'less_natural' ? 'c-less' : 'muted';
      const note = f.actionable ? '' : (f.judgment === 'error' || f.judgment === 'less_natural' ? ' · 기준 미만' : ' · 검색 제외');
      row(parent, change, `${JUDGMENT[f.judgment]} · ${f.confidence.toFixed(2)}${note}`, tone);
    }
    for (const d of data.dropped) row(parent, d.expression, `버림 · ${d.reason}`, 'muted');
  }
  if (key === 'retrieval') {
    for (const item of data) {
      if (item.matches.length) {
        for (const m of item.matches) row(parent, `${item.expression} · ${m.title}`, `유사도 ${m.score.toFixed(2)} · 통과`);
      } else {
        const best = item.rejected[0];
        row(parent, item.expression, best ? `최고 ${best.score.toFixed(2)} · 기준 미만 · 근거 없음` : '근거 없음', 'muted');
      }
    }
  }
  if (key === 'generation') {
    const out = data.output;
    add(parent, 'p', 'step-line', `원문 + 분석 + 학습 기록 + 근거를 입력으로 전달. 피드백 ${out.items.length}건, 문제 1개, 도구 호출 제안 ${out.tool_calls.length}건`);
    if (data.attempts > 1) add(parent, 'p', 'step-line', `응답 형식이 맞지 않아 ${data.attempts}번 요청함`);
    for (const note of data.repairs) add(parent, 'p', 'step-line', `바로잡음: ${note}`);
  }
  if (key === 'tools') {
    if (!data.results.length) add(parent, 'p', 'step-line', '문장만 기록함 · 도구 호출 제안 없음');
    for (const r of data.results) {
      const f = findings[r.arguments.index];
      row(parent, f ? `${f.expression} → ${f.suggestion}` : `${r.arguments.index}번`,
        r.status === 'saved' ? '저장함' : r.status === 'duplicate' ? '이미 저장됨' : `저장 안 함 · ${r.reason}`,
        r.status === 'saved' ? '' : 'muted');
    }
  }
}
let traceFindings = [];
function updateStep(step) {
  const node = stepNodes[step.key];
  if (!node) return;
  node.item.className = `step ${step.status}`;
  node.detail.replaceChildren();
  if (step.status === 'ok') {
    node.state.textContent = seconds(step.latency_ms);
    if (step.key === 'analysis') traceFindings = step.data.findings;
    describeStep(step.key, step.data, node.detail, traceFindings);
  } else if (step.status === 'skipped') {
    node.state.textContent = '건너뜀';
    add(node.detail, 'p', 'step-message', step.message);
  } else {
    node.state.textContent = `실패 · ${seconds(step.latency_ms)}`;
    add(node.detail, 'p', 'step-message', step.message);
  }
  const foot = add(node.detail, 'div', 'step-foot');
  add(foot, 'code', '', step.file);
  if (step.data !== undefined && step.data !== null) {
    const toggle = add(foot, 'button', '', '원본 JSON');
    toggle.type = 'button';
    toggle.setAttribute('aria-expanded', 'false');
    const pre = add(node.detail, 'pre', '', JSON.stringify(step.data, null, 2));
    pre.hidden = true;
    toggle.addEventListener('click', () => {
      pre.hidden = !pre.hidden;
      toggle.setAttribute('aria-expanded', String(!pre.hidden));
    });
  }
}
function markRunning(key) {
  const node = stepNodes[key];
  if (!node) return;
  node.item.className = 'step running';
  node.state.textContent = '진행 중';
}
function finishProcess(trace, failed) {
  for (const node of Object.values(stepNodes)) {
    if (node.item.classList.contains('pending') || node.item.classList.contains('running')) {
      node.item.className = 'step pending';
      node.state.textContent = failed ? '실행 안 됨' : '';
    }
  }
  if (!trace) return;
  const totals = $('totals');
  totals.replaceChildren();
  const total = (value, label) => { const box = add(totals, 'div'); add(box, 'dd', '', value); add(box, 'dt', '', label); };
  total(seconds(trace.latency_ms), '전체 시간');
  total(`${trace.model_calls}회`, '모델 호출');
  if (!failed) {
    const tools = trace.steps.find(s => s.key === 'tools');
    const saved = tools && tools.data ? tools.data.results.filter(r => r.status === 'saved').length : 0;
    total(`${saved}건`, '저장한 기록');
  }
}

// ── 결과 ────────────────────────────────────────────────
function renderSentence(data) {
  const box = $('sentence');
  box.replaceChildren();
  let cursor = 0;
  for (const f of data.findings.filter(item => item.actionable)) {
    box.append(data.utterance.slice(cursor, f.start));
    add(box, 'span', f.judgment === 'error' ? 'mark-error' : 'mark-less', data.utterance.slice(f.start, f.end));
    cursor = f.end;
  }
  box.append(data.utterance.slice(cursor));
}
function renderResult(data) {
  renderSentence(data);
  const shown = data.findings.filter(f => f.actionable);
  const errors = shown.filter(f => f.judgment === 'error').length;
  const less = shown.length - errors;
  const legend = $('legend');
  legend.replaceChildren();
  if (errors) { const s = add(legend, 'span'); add(s, 'i', 'l-error'); s.append(`오류 ${errors}`); }
  if (less) { const s = add(legend, 'span'); add(s, 'i', 'l-less'); s.append(`덜 자연스러움 ${less}`); }
  add(legend, 'span', '', shown.length ? '나머지는 괜찮아요' : '고칠 곳을 찾지 못했어요');
  $('overall').textContent = data.overall;
  const corrected = $('corrected');
  corrected.replaceChildren();
  corrected.hidden = !data.corrected;
  if (data.corrected) { add(corrected, 'b', '', '고친 문장'); corrected.append(data.corrected); }

  const list = $('findings');
  list.replaceChildren();
  for (const f of shown) {
    const card = add(list, 'article', 'finding');
    add(card, 'span', `tag ${f.judgment}`, `${f.judgment_label} · ${f.category_label}`);
    const change = add(card, 'div', 'change');
    add(change, 'span', `before ${f.judgment}`, f.expression);
    change.appendChild(arrow());
    add(change, 'span', 'after', f.suggestion);
    add(card, 'p', '', f.explanation);
    for (const source of f.evidence.filter(item => item.cited)) {
      const box = add(card, 'div', 'evidence');
      add(box, 'b', '', '문법 근거');
      const text = add(box, 'p');
      add(text, 'strong', '', source.title);
      text.append(` — ${source.rule}`);
      if (source.example) add(box, 'p', '', `예: ${source.example}`);
      if (/^https:\/\//.test(source.source_url)) {
        const link = add(box, 'a', '', '한국어기초사전에서 찾아보기');
        link.href = source.source_url; link.target = '_blank'; link.rel = 'noopener noreferrer';
      }
    }
    const parts = [];
    if (f.seen_count >= 2) parts.push(`이 문법은 이번이 ${f.seen_count}번째예요`);
    if (f.record && f.record.status === 'saved') parts.push('학습 기록에 추가함');
    else if (f.record) parts.push(`학습 기록에 넣지 않음 (${f.record.reason})`);
    else parts.push(f.evidence.length ? '학습 기록에 넣지 않음' : '맞는 문법 자료가 없어 학습 기록에 넣지 않음');
    add(card, 'p', 'meta', parts.join(' · '));
  }

  const notes = $('notes');
  notes.replaceChildren();
  for (const f of data.findings.filter(item => !item.actionable)) {
    const line = add(notes, 'li');
    add(line, 'strong', '', f.expression);
    if (f.judgment === 'acceptable') line.append(` · 괜찮아요. ${f.explanation}`);
    else if (f.judgment === 'uncertain') line.append(` · 문맥이 부족해 판단하지 않았어요. ${f.explanation}`);
    else line.append(` → ${f.suggestion} · 확신이 낮아 참고만 하세요. ${f.explanation}`);
  }
  renderPractice(data);
  $('result').hidden = false;
}
function renderPractice(data) {
  const box = $('practice');
  box.replaceChildren();
  box.hidden = !data.question;
  if (!data.question) return;
  const head = add(box, 'div', 'practice-head');
  add(head, 'h2', '', data.question.grammar_title ? `한 문제 연습 · ${data.question.grammar_title}` : '한 문제 연습');
  add(head, 'span', '', '결과는 기록에 남아요');
  add(box, 'p', 'practice-prompt', data.question.prompt);
  const choices = add(box, 'div', 'choices');
  const answer = add(box, 'p', 'practice-answer');
  answer.hidden = true;
  answer.setAttribute('role', 'status');
  data.question.choices.forEach((choice, index) => {
    const button = add(choices, 'button', 'choice', choice);
    button.type = 'button';
    button.addEventListener('click', async () => {
      const buttons = [...choices.children];
      buttons.forEach(other => { other.disabled = true; });
      try {
        const check = await api('/api/practice', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ learner_id: learnerId, request_id: data.request_id, choice_index: index }),
        });
        buttons[check.answer_index].classList.add('correct');
        if (!check.correct) button.classList.add('wrong');
        answer.replaceChildren();
        add(answer, 'strong', '', check.correct ? '맞았어요. ' : `정답은 '${data.question.choices[check.answer_index]}'예요. `);
        answer.append(check.explanation);
        answer.hidden = false;
        loadProfile();
      } catch (error) {
        buttons.forEach(other => { other.disabled = false; });
        answer.textContent = error.message;
        answer.hidden = false;
      }
    });
  });
}

// ── 분석 실행: 단계가 끝날 때마다 한 줄씩 도착한다 ────────
async function analyze() {
  if (busy || !utterance.value.trim()) return;
  busy = true;
  notice('');
  refreshButton();
  $('result').hidden = true;
  $('failure').hidden = true;
  layout.classList.remove('failed');
  layout.classList.add('loading');
  traceFindings = [];
  resetProcess();
  let finished = false;
  try {
    const response = await fetch('/api/analyze', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ learner_id: learnerId, utterance: utterance.value }),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(typeof data.detail === 'string' ? data.detail : '요청을 처리하지 못했습니다.');
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    const handle = event => {
      if (event.type === 'start') markRunning(event.key);
      if (event.type === 'step') updateStep(event.step);
      if (event.type === 'result') {
        finished = true;
        finishProcess(event.trace, false);
        renderResult(event);
        renderRecord(event);
      }
      if (event.type === 'error') {
        finished = true;
        showFailure(event);
      }
    };
    for (;;) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      const lines = buffer.split('\n');
      buffer = lines.pop();
      for (const line of lines) if (line.trim()) handle(JSON.parse(line));
      if (done) break;
    }
    if (!finished) throw new Error('서버 응답이 중간에 끊겼습니다. 다시 시도해 주세요.');
  } catch (error) {
    if (!finished) {
      $('process').hidden = true;
      layout.classList.remove('with-process');
      notice(error.message);
    }
  } finally {
    busy = false;
    layout.classList.remove('loading');
    refreshButton();
  }
}
function showFailure(event) {
  finishProcess(event.trace, true);
  const failed = event.trace ? event.trace.steps.find(step => step.status === 'failed') : null;
  $('failure-text').textContent = failed
    ? `'${failed.name}' 단계에서 멈췄습니다. 입력한 문장은 그대로 남아 있어요.`
    : `${event.message} 입력한 문장은 그대로 남아 있어요.`;
  $('failure').hidden = false;
  layout.classList.add('failed');
  if (!event.trace) { $('process').hidden = true; layout.classList.remove('with-process'); }
}

// ── 학습 기록 ───────────────────────────────────────────
function when(text) {
  const date = new Date(`${text.replace(' ', 'T')}Z`);
  if (Number.isNaN(date.getTime())) return '';
  return date.toDateString() === new Date().toDateString() ? '오늘'
    : date.toLocaleDateString('ko-KR', { month: 'long', day: 'numeric' });
}
function renderRecord(data) {
  const stats = $('stats');
  stats.replaceChildren();
  const stat = (value, label) => { const box = add(stats, 'div'); add(box, 'b', '', value); add(box, 'span', '', label); };
  stat(data.stats.corrections, '고친 표현');
  stat(data.stats.sentences, '쓴 문장');
  stat(data.stats.practice_total ? `${data.stats.practice_correct}/${data.stats.practice_total}` : '–', '연습 정답');

  const patterns = $('patterns');
  patterns.replaceChildren();
  if (!data.patterns.length) add(patterns, 'p', 'empty', '아직 기록이 없어요. 문장을 쓰고 고친 표현이 생기면 여기에 문법별로 모입니다.');
  const top = Math.max(1, ...data.patterns.map(p => p.count));
  for (const pattern of data.patterns.slice(0, 6)) {
    const box = add(patterns, 'div', 'pattern');
    const head = add(box, 'div', 'pattern-top');
    add(head, 'b', '', pattern.title);
    add(head, 'span', '', `${pattern.count}회`);
    add(add(box, 'div', 'bar'), 'i').style.width = `${Math.round((pattern.count / top) * 100)}%`;
  }

  const history = $('history');
  history.replaceChildren();
  if (!data.history.length) add(history, 'p', 'empty', '고친 표현이 여기에 날짜와 함께 남습니다.');
  for (const item of data.history) {
    const box = add(history, 'div', 'history-item');
    const head = add(box, 'div', 'history-top');
    add(head, 'b', '', `${item.expression} → ${item.suggestion}`);
    add(head, 'span', '', when(item.created_at));
    if (item.utterance) add(box, 'p', '', item.utterance);
    const practice = item.practice_correct === null ? '' : item.practice_correct ? ' · 연습 정답' : ' · 연습 오답';
    add(box, 'small', '', `${item.judgment_label} · ${item.category_label}${practice}`);
  }

  const level = $('level');
  if (!level.options.length) for (const value of data.profile.levels) add(level, 'option', '', value).value = value;
  level.value = data.profile.level;
  const native = $('native');
  if (![...native.options].some(option => option.value === data.profile.native_language)) {
    add(native, 'option', '', data.profile.native_language).value = data.profile.native_language;
  }
  native.value = data.profile.native_language;
}
async function loadProfile() {
  renderRecord(await api(`/api/profile?learner_id=${encodeURIComponent(learnerId)}`));
}
async function saveProfile() {
  try {
    renderRecord(await api('/api/profile', {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ learner_id: learnerId, level: $('level').value, native_language: $('native').value }),
    }));
  } catch (error) { notice(error.message); }
}

// ── 연결 ────────────────────────────────────────────────
utterance.addEventListener('input', refreshButton);
analyzeButton.addEventListener('click', analyze);
$('retry').addEventListener('click', analyze);
$('again').addEventListener('click', () => {
  utterance.value = '';
  refreshButton();
  utterance.focus();
  utterance.scrollIntoView({ block: 'center' });
});
$('level').addEventListener('change', saveProfile);
$('native').addEventListener('change', saveProfile);
document.querySelectorAll('[data-example]').forEach(button => button.addEventListener('click', () => {
  utterance.value = EXAMPLES[button.dataset.example];
  refreshButton();
  utterance.focus();
}));
document.querySelectorAll('[data-view]').forEach(tab => tab.addEventListener('click', () => showView(tab.dataset.view)));

(async () => {
  try {
    const [config] = await Promise.all([api('/api/config'), loadProfile()]);
    configured = config.configured;
    utterance.maxLength = config.max_length;
    if (!configured) notice('서버에 GEMINI_API_KEY가 설정되지 않아 분석을 실행할 수 없습니다.');
  } catch (error) {
    notice(`서버에 연결하지 못했습니다. ${error.message}`);
  }
  refreshButton();
})();
