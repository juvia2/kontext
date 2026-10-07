const $ = id => document.getElementById(id);
const utterance = $('utterance');
const button = $('analyze-button');
const examples = {
  wrong: '어제 책이 읽었어요. 정말 재미있었어요.',
  everyday: '어제 친구와 영화를 봤어요. 영화가 정말 재미있었어요.'
};
const categoryNames = {
  particle_selection: '조사', connective_ending: '문장 연결',
  tense: '시제', register: '말투·높임', grammar: '문법'
};
const categoryName = value => categoryNames[value] || value;
const storageKey = 'llmzip-learner-id';
let learnerId = localStorage.getItem(storageKey);
if (!learnerId || !/^demo-[a-f0-9-]{32,36}$/.test(learnerId)) {
  const randomId = crypto.randomUUID?.() || Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')).join('');
  learnerId = `demo-${randomId}`;
  localStorage.setItem(storageKey, learnerId);
}
let configured = false;
const el = (tag, className, value) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (value !== undefined) node.textContent = String(value);
  return node;
};
const append = (parent, tag, className, value) => { const node = el(tag, className, value); parent.append(node); return node; };
const clear = node => node.replaceChildren();
const safeLink = value => { try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) ? url.href : null; } catch { return null; } };
const status = (message, error=false) => { const box = $('configuration'); box.textContent = message; box.hidden = !message; box.classList.toggle('error', error); };
function updateButton(){ $('char-count').textContent = `${utterance.value.length.toLocaleString()} / 2,000`; button.disabled = !configured; }
utterance.addEventListener('input', updateButton);
document.querySelectorAll('[data-example]').forEach(exampleButton => {
  exampleButton.addEventListener('click', () => {
    utterance.value = examples[exampleButton.dataset.example];
    updateButton();
    utterance.focus();
  });
});
function showView(name) {
  document.querySelectorAll('[data-view-panel]').forEach(panel => { panel.hidden = panel.dataset.viewPanel !== name; });
  document.querySelectorAll('[data-view]').forEach(tab => {
    const active = tab.dataset.view === name;
    tab.classList.toggle('active', active);
    if (active) tab.setAttribute('aria-current', 'page');
    else tab.removeAttribute('aria-current');
  });
  window.scrollTo({top: 0, behavior: 'smooth'});
}
document.querySelectorAll('[data-view]').forEach(tab => tab.addEventListener('click', () => showView(tab.dataset.view)));
$('again-button').addEventListener('click', () => { utterance.focus(); utterance.scrollIntoView({behavior:'smooth', block:'center'}); });
async function getJson(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) {
    const detail = data.detail;
    const message = typeof detail === 'string' ? detail : detail?.message || '요청에 실패했습니다.';
    const error = new Error(message);
    error.trace = detail?.trace;
    throw error;
  }
  return data;
}
function renderProfile(profile, history) {
  const box = $('profile'); clear(box);
  const pills = append(box, 'div', 'profile-pills');
  append(pills, 'span', 'pill', `레벨 ${profile.level}`);
  append(pills, 'span', 'pill', `모국어 ${profile.native_language === 'English' ? '영어' : profile.native_language}`);
  const patterns = Object.entries(profile.recent_patterns || {});
  if (!patterns.length) append(box, 'p', 'muted', '아직 학습 패턴이 없습니다.');
  for (const [category, count] of patterns) { const row = append(box, 'div', 'pattern'); append(row, 'span', '', categoryName(category)); append(row, 'b', '', `${count}회`); }
  const list = $('history'); clear(list);
  if (!history.length) append(list, 'p', 'muted', '최근 기록이 없습니다.');
  for (const item of history) { const row = append(list, 'div', 'history-item'); append(row, 'strong', '', `${item.expression} → ${item.suggestion}`); append(row, 'span', '', categoryName(item.error_type)); }
}
function renderEvidence(parent, matches, citedIds) {
  const details = append(parent, 'details', 'evidence');
  append(details, 'summary', '', `검색된 문법 근거 ${matches.length}건 보기`);
  for (const match of matches) {
    const row = append(details, 'div', 'evidence-row');
    append(row, 'p', '', `${match.title} · ${match.id}${citedIds.includes(match.id) ? ' · 피드백에 인용됨' : ''}`);
    append(row, 'p', '', match.text);
    append(row, 'small', '', `검색 유사도 ${Number(match.score).toFixed(3)} · 문법 정답 확률이 아닙니다`);
    for (const rawUrl of match.source_urls || []) { const url = safeLink(rawUrl); if (url) { const a = append(row, 'a', '', '사전 자료 보기'); a.href = url; a.target = '_blank'; a.rel = 'noopener noreferrer'; } }
  }
}
function renderAnalysis(data) {
  $('overall').textContent = data.feedback.overall || data.analysis.overall_feedback;
  const box = $('analysis-cards'); clear(box);
  if (!data.analysis.errors.length) append(box, 'div', 'card feedback-card', '수정이 필요한 표현을 발견하지 못했습니다.');
  data.analysis.errors.forEach((error, index) => {
    const card = append(box, 'article', 'card feedback-card');
    append(card, 'div', 'meta', categoryName(error.category));
    const comparison = append(card, 'div', 'comparison');
    const before = append(comparison, 'div', 'phrase');
    append(before, 'span', 'phrase-label', '내 표현');
    append(before, 'strong', '', error.expression);
    const after = append(comparison, 'div', 'phrase suggested');
    append(after, 'span', 'phrase-label', '이렇게 써봐요');
    append(after, 'strong', '', error.suggestion);
    append(card, 'p', '', error.explanation);
    const item = data.feedback.items.find(value => value.error_index === index);
    if (item) {
      append(card, 'p', '', item.explanation);
      append(card, 'p', '', `자연스러운 대안 · ${item.natural_alternative}`);
      append(card, 'p', 'insight', item.personalized_insight);
    }
    const matches = data.evidence[String(index)] || [];
    if (matches.length) renderEvidence(card, matches, item?.evidence_ids || []);
    else if (item) append(card, 'p', 'muted', '이 설명에는 검색된 문법 근거가 없습니다.');
  });
}
function renderPractice(questions) {
  const box = $('practice-cards'); clear(box);
  if (!questions.length) append(box, 'p', 'muted', '이번 발화에는 생성된 연습문제가 없습니다.');
  questions.forEach((question, index) => {
    const card = append(box, 'article', 'card practice-card');
    append(card, 'h3', '', `${index + 1}. ${question.question}`);
    const answer = append(card, 'p', 'answer'); answer.hidden = true;
    question.choices.forEach((choice, choiceIndex) => {
      const option = append(card, 'button', 'choice'); option.type = 'button';
      append(option, 'span', 'letter', String.fromCharCode(65 + choiceIndex)); append(option, 'span', '', choice);
      option.addEventListener('click', () => {
        for (const other of card.querySelectorAll('.choice')) other.disabled = true;
        option.classList.add(choiceIndex === question.answer_index ? 'correct' : 'wrong');
        if (choiceIndex !== question.answer_index) card.querySelectorAll('.choice')[question.answer_index].classList.add('correct');
        answer.textContent = `${choiceIndex === question.answer_index ? '정답입니다!' : '다시 살펴보세요.'} 정답: ${String.fromCharCode(65 + question.answer_index)} · ${question.explanation}`;
        answer.classList.toggle('incorrect', choiceIndex !== question.answer_index);
        answer.hidden = false;
      });
    });
  });
}
function renderTools(results) {
  const box = $('tool-results'); clear(box);
  if (!results.length) append(box, 'p', '', '이번에는 학습 기록을 추가하지 않았습니다.');
  for (const item of results) append(box, 'p', '', `${item.status} · ${item.arguments?.expression || ''} · ${item.reason || ''}`);
}
function renderTrace(trace) {
  const box = $('trace'); clear(box);
  append(box, 'p', 'muted', `요청 ${trace.request_id} · 총 ${Math.round(trace.latency_ms)}ms`);
  for (const [index, step] of trace.steps.entries()) {
    const details = append(box, 'details', 'trace-step');
    append(details, 'summary', '', `${index + 1}. ${step.name} · ${step.status} · ${Math.round(step.latency_ms)}ms`);
    append(details, 'pre', '', JSON.stringify(step.data || {error: step.error, message: step.message}, null, 2));
  }
}
button.addEventListener('click', async () => {
  if (!utterance.value.trim()) { status('먼저 문장을 적어 주세요.', true); utterance.focus(); return; }
  button.disabled = true; button.firstChild.textContent = '분석 중… ';
  status('');
  try {
    const data = await getJson('/api/analyze', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({learner_id:learnerId, utterance:utterance.value})});
    renderAnalysis(data); renderPractice(data.practice.questions); renderTools(data.tool_results);
    renderTrace(data.trace); renderProfile(data.profile, data.history);
    $('results').hidden = false; status('');
    $('results').scrollIntoView({behavior:'smooth', block:'start'});
  } catch (error) {
    status(error.message, true);
    if (error.trace) renderTrace(error.trace);
  } finally { button.firstChild.textContent = '내 문장 살펴보기 '; updateButton(); }
});
(async () => {
  try {
    const [config, profile] = await Promise.all([getJson('/api/config'), getJson(`/api/profile?learner_id=${encodeURIComponent(learnerId)}`)]);
    configured = config.configured;
    status(configured ? '' : 'AI 튜터 연결을 확인해 주세요.', !configured);
    renderProfile(profile.profile, profile.history); updateButton();
  } catch (error) { status(`서버 연결을 확인해 주세요: ${error.message}`, true); }
})();
