(() => {
  "use strict";

  const state = { sessionId: null, eventSource: null, usageTimer: null };

  const $ = (id) => document.getElementById(id);

  const STATUS_LABELS = {
    INPUT: "대기 중",
    PHASE1_RUNNING: "Phase 1 진행 중 (기획)",
    HITL_GATE1: "Gate 1 대기 중",
    PHASE1_APPROVED: "Phase 1 승인됨",
    PHASE2_RUNNING: "Phase 2 진행 중 (초안 작성)",
    PHASE2_COMPLETE: "Phase 2 완료",
    PHASE3_RUNNING: "Phase 3 진행 중 (검증)",
    HITL_GATE2: "Gate 2 대기 중",
    PHASE3_APPROVED: "Phase 3 승인됨",
    PHASE4_RUNNING: "Phase 4 진행 중 (최종 감사)",
    COMPLETE: "완료",
    ERROR: "오류",
  };

  // ---------------------------------------------------------------- 메타데이터 로드
  async function loadMeta() {
    const res = await fetch("/api/meta");
    const meta = await res.json();

    const ptSel = $("f-paper-type");
    ptSel.innerHTML = "";
    for (const [key, info] of Object.entries(meta.paper_types)) {
      const opt = document.createElement("option");
      opt.value = key;
      opt.textContent = `${info.label} — ${info.description}`;
      if (key === meta.default_paper_type) opt.selected = true;
      ptSel.appendChild(opt);
    }

    const csSel = $("f-citation-style");
    csSel.innerHTML = "";
    for (const style of meta.citation_styles) {
      const opt = document.createElement("option");
      opt.value = style;
      opt.textContent = style;
      if (style === meta.default_citation_style) opt.selected = true;
      csSel.appendChild(opt);
    }

    const langSel = $("f-language");
    langSel.innerHTML = "";
    for (const [key, label] of Object.entries(meta.languages || {})) {
      const opt = document.createElement("option");
      opt.value = key;
      opt.textContent = label;
      if (key === meta.default_language) opt.selected = true;
      langSel.appendChild(opt);
    }
  }

  // ---------------------------------------------------------------- 입력 폼 → 세션 생성 → Phase 1 시작
  function collectFormData() {
    return {
      topic: $("f-topic").value.trim(),
      field: $("f-field").value.trim(),
      purpose: $("f-purpose").value.trim(),
      methods_notes: $("f-methods").value.trim(),
      results_notes: $("f-results").value.trim(),
      keywords: $("f-keywords").value.trim(),
      references_raw: $("f-references").value.trim(),
      ethics_statement: $("f-ethics").value.trim(),
      extra_instructions: $("f-extra").value.trim(),
      paper_type: $("f-paper-type").value,
      citation_style: $("f-citation-style").value,
      language: $("f-language").value,
    };
  }

  async function startPipeline() {
    const data = collectFormData();
    if (!data.topic && !data.purpose) {
      alert("논문 주제 또는 연구 목적 중 하나는 입력해주세요.");
      return;
    }

    $("btn-start").disabled = true;
    $("btn-start").textContent = "생성 중...";

    try {
      const sessRes = await fetch("/api/session/new", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      if (!sessRes.ok) throw new Error((await sessRes.json()).detail || "세션 생성 실패");
      const sess = await sessRes.json();
      state.sessionId = sess.session_id;

      const startRes = await fetch("/api/phase1/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: state.sessionId }),
      });
      if (!startRes.ok) throw new Error((await startRes.json()).detail || "Phase 1 시작 실패");

      $("view-input").classList.add("hidden");
      $("view-pipeline").classList.remove("hidden");
      $("usage-badge").classList.remove("hidden");

      openStream(state.sessionId);
      startUsagePolling();
    } catch (e) {
      alert("오류: " + e.message);
      $("btn-start").disabled = false;
      $("btn-start").textContent = "논문 초안 생성 시작";
    }
  }

  // ---------------------------------------------------------------- SSE 스트림
  function openStream(sessionId) {
    if (state.eventSource) state.eventSource.close();
    const es = new EventSource(`/api/stream/${sessionId}`);
    state.eventSource = es;

    es.onmessage = (ev) => {
      let data;
      try { data = JSON.parse(ev.data); } catch { return; }
      handleEvent(data);
    };

    es.onerror = () => {
      es.close();
      // 세션이 아직 끝나지 않았다면 재연결
      fetch(`/api/session/${sessionId}`).then((r) => r.json()).then((s) => {
        if (s.status && !["COMPLETE", "ERROR"].includes(s.status)) {
          setTimeout(() => openStream(sessionId), 1000);
        }
      }).catch(() => {});
    };
  }

  function handleEvent(data) {
    if (data.type === "connected" || data.type === "stream_end") return;

    if (data.type === "status_update") {
      updateStatusBadge(data.status);
      if (data.status === "HITL_GATE1") loadGate1();
      else if (data.status === "HITL_GATE2") loadGate2();
      else if (data.status === "COMPLETE") loadComplete();
      else if (data.status === "ERROR") showError(data.message || "알 수 없는 오류가 발생했습니다.");
      return;
    }

    if (data.agent_name) appendLog(data);
  }

  function updateStatusBadge(status) {
    const badge = $("status-badge");
    badge.textContent = STATUS_LABELS[status] || status;
    badge.className = "status-badge";
    if (status === "ERROR") badge.classList.add("error");
    else if (status === "COMPLETE") badge.classList.add("complete");
    else badge.classList.add("running");
  }

  function appendLog(ev) {
    const panel = $("log-panel");
    const line = document.createElement("div");
    line.className = "log-line";
    const time = ev.timestamp ? ev.timestamp.split("T")[1]?.split(".")[0] || "" : "";
    line.innerHTML =
      `<span style="color:#64748B">[${time}]</span> ` +
      `<span class="agent">${escapeHtml(ev.agent_name)}</span> ` +
      `<span class="ev-${escapeHtml(ev.event_type || "LOG")}">${escapeHtml(ev.content || "")}</span>`;
    panel.appendChild(line);
    panel.scrollTop = panel.scrollHeight;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  // ---------------------------------------------------------------- Gate 1
  async function loadGate1() {
    const res = await fetch(`/api/phase1/hitl-data/${state.sessionId}`);
    if (!res.ok) return;
    const data = await res.json();
    const outline = data.outline || {};

    const warnBox = $("gate1-warnings");
    warnBox.innerHTML = "";
    for (const w of data.input_warnings || []) {
      const div = document.createElement("div");
      div.className = "w-item";
      div.textContent = `${w.level === "warning" ? "⚠️" : "ℹ️"} ${w.message}`;
      warnBox.appendChild(div);
    }

    const outlineBox = $("gate1-outline");
    outlineBox.innerHTML = "";

    const titleEl = document.createElement("div");
    titleEl.className = "outline-title";
    titleEl.textContent = outline.title || "(제목 없음)";
    outlineBox.appendChild(titleEl);

    if (outline.working_title_alternatives?.length) {
      const alt = document.createElement("div");
      alt.className = "outline-alt";
      alt.textContent = "대안 제목: " + outline.working_title_alternatives.join(" / ");
      outlineBox.appendChild(alt);
    }

    const lc = outline.logic_chain || {};
    const lcBox = document.createElement("div");
    lcBox.className = "logic-chain";
    for (const [key, label] of [["background", "Background"], ["gap", "Gap"], ["purpose", "Purpose"], ["expected_conclusion", "Expected Conclusion"]]) {
      if (!lc[key]) continue;
      const item = document.createElement("div");
      item.className = "item";
      item.innerHTML = `<b>${label}</b>`;
      item.appendChild(document.createTextNode(lc[key]));
      lcBox.appendChild(item);
    }
    outlineBox.appendChild(lcBox);

    for (const section of outline.sections || []) {
      const block = document.createElement("div");
      block.className = "section-block";
      const key = document.createElement("div");
      key.className = "key";
      key.textContent = section.key;
      block.appendChild(key);
      const thesis = document.createElement("div");
      thesis.className = "thesis";
      thesis.textContent = section.thesis || "";
      block.appendChild(thesis);
      if (section.key_points?.length) {
        const ul = document.createElement("ul");
        for (const kp of section.key_points) {
          const li = document.createElement("li");
          li.textContent = kp;
          ul.appendChild(li);
        }
        block.appendChild(ul);
      }
      if (section.gap_warning) {
        const gw = document.createElement("div");
        gw.className = "gap-warning";
        gw.textContent = "⚠ " + section.gap_warning;
        block.appendChild(gw);
      }
      outlineBox.appendChild(block);
    }

    $("gate1-summary").textContent = data.summary || "";
    $("gate2-card").classList.add("hidden");
    $("complete-card").classList.add("hidden");
    $("reviewer-qa-card").classList.add("hidden");
    $("error-card").classList.add("hidden");
    $("gate1-card").classList.remove("hidden");
    $("gate1-card").scrollIntoView({ behavior: "smooth" });
  }

  async function gate1Action(action) {
    const feedback = $("gate1-feedback").value.trim();
    if (action === "revise" && !feedback) {
      alert("수정 요청 내용을 입력해주세요.");
      return;
    }
    $("gate1-card").classList.add("hidden");
    await fetch("/api/phase1/approve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: state.sessionId, action, feedback: feedback || undefined }),
    });
  }

  // ---------------------------------------------------------------- Gate 2
  async function loadGate2() {
    const res = await fetch(`/api/phase3/hitl-data/${state.sessionId}`);
    if (!res.ok) return;
    const data = await res.json();
    const fc = data.fact_check || {};
    const lc = data.language_check || {};

    const stats = $("gate2-stats");
    stats.innerHTML = "";
    const statDefs = [
      ["근거 부족 주장", (fc.unsupported_claims || []).length],
      ["재현성 이슈", (fc.reproducibility_issues || []).length],
      ["어색한 문장", (lc.awkward_sentences || []).length],
      ["약어 이슈", (lc.abbreviation_issues || []).length],
      ["윤리 정보", fc.ethics_check?.has_ethics_statement ? "있음" : "없음"],
    ];
    for (const [label, n] of statDefs) {
      const div = document.createElement("div");
      div.className = "stat";
      div.innerHTML = `<div class="n">${n}</div><div class="l">${label}</div>`;
      stats.appendChild(div);
    }

    fillIssueList("gate2-unsupported", (fc.unsupported_claims || []).map(
      (c) => `<span class="tag">${escapeHtml(c.section)}</span> ${escapeHtml(c.excerpt)} — ${escapeHtml(c.issue)}`
    ));
    fillIssueList("gate2-repro", (fc.reproducibility_issues || []).map(
      (c) => `${escapeHtml(c.excerpt)} — ${escapeHtml(c.issue)}`
    ));
    fillIssueList("gate2-awkward", (lc.awkward_sentences || []).map(
      (c) => `<span class="tag">${escapeHtml(c.section)}</span> ${escapeHtml(c.issue)}<br><em>제안: ${escapeHtml(c.suggestion || "")}</em>`
    ));
    fillIssueList("gate2-abbrev", (lc.abbreviation_issues || []).map(
      (c) => `<b>${escapeHtml(c.abbreviation)}</b>: ${escapeHtml(c.issue)}`
    ));

    $("gate1-card").classList.add("hidden");
    $("complete-card").classList.add("hidden");
    $("reviewer-qa-card").classList.add("hidden");
    $("error-card").classList.add("hidden");
    $("gate2-card").classList.remove("hidden");
    $("gate2-card").scrollIntoView({ behavior: "smooth" });
  }

  function fillIssueList(elId, htmlItems) {
    const ul = $(elId);
    ul.innerHTML = "";
    if (!htmlItems.length) {
      ul.className = "issue-list empty-ok";
      const li = document.createElement("li");
      li.style.borderLeft = "none";
      li.style.background = "none";
      li.textContent = "✓ 발견된 이슈 없음";
      ul.appendChild(li);
      return;
    }
    ul.className = "issue-list";
    for (const html of htmlItems) {
      const li = document.createElement("li");
      li.innerHTML = html;
      ul.appendChild(li);
    }
  }

  async function gate2Action(action) {
    const feedback = $("gate2-feedback").value.trim();
    $("gate2-card").classList.add("hidden");
    await fetch("/api/phase3/approve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: state.sessionId, action, feedback: feedback || undefined }),
    });
  }

  // ---------------------------------------------------------------- 완료
  async function loadComplete() {
    const res = await fetch(`/api/phase4/hitl-data/${state.sessionId}`);
    if (!res.ok) return;
    const data = await res.json();
    const sc = data.static_checks || {};

    const stats = $("complete-stats");
    stats.innerHTML = "";
    const statDefs = [
      ["단어 수", sc.word_count],
      ["목표 분량", `${sc.word_count_target?.[0]}~${sc.word_count_target?.[1]}`],
      ["잔여 NEEDS DATA", sc.remaining_needs_data_count],
      ["참고문헌", sc.citation_check?.reference_count ?? 0],
      ["윤리 정보", sc.has_ethics_statement ? "있음" : "없음"],
    ];
    for (const [label, n] of statDefs) {
      const div = document.createElement("div");
      div.className = "stat";
      div.innerHTML = `<div class="n">${n}</div><div class="l">${label}</div>`;
      stats.appendChild(div);
    }

    $("complete-verdict").textContent = data.final_verdict || "";
    renderReviewerQa(data.review_qa || { questions: [] });

    $("gate1-card").classList.add("hidden");
    $("gate2-card").classList.add("hidden");
    $("error-card").classList.add("hidden");
    $("complete-card").classList.remove("hidden");
    $("reviewer-qa-card").classList.remove("hidden");
    $("complete-card").scrollIntoView({ behavior: "smooth" });
    stopUsagePolling();
    refreshUsage();
  }

  function renderReviewerQa(reviewQa) {
    const list = $("reviewer-qa-list");
    list.innerHTML = "";
    const questions = reviewQa.questions || [];
    if (!questions.length) {
      list.innerHTML = '<p style="color:var(--text-muted);font-size:0.85rem">생성된 예상 질문이 없습니다.</p>';
      return;
    }
    for (const q of questions) {
      const sev = q.severity === "major" ? "major" : "minor";
      const div = document.createElement("div");
      div.className = `qa-item ${sev}`;
      div.innerHTML =
        `<div class="qa-tags"><span class="sev-${sev}">${sev === "major" ? "MAJOR" : "MINOR"}</span> · ${escapeHtml((q.category || "other").toUpperCase())}</div>` +
        `<div class="qa-question">Q. ${escapeHtml(q.question || "")}</div>` +
        `<div class="qa-defense"><b>디펜스:</b> ${escapeHtml(q.defense || "")}</div>`;
      list.appendChild(div);
    }
  }

  function showError(message) {
    $("gate1-card").classList.add("hidden");
    $("gate2-card").classList.add("hidden");
    $("complete-card").classList.add("hidden");
    $("reviewer-qa-card").classList.add("hidden");
    $("error-message").textContent = message;
    $("error-card").classList.remove("hidden");
    stopUsagePolling();
  }

  // ---------------------------------------------------------------- 토큰/비용
  async function refreshUsage() {
    if (!state.sessionId) return;
    try {
      const res = await fetch(`/api/usage/${state.sessionId}`);
      const data = await res.json();
      const s = data.summary || {};
      $("usage-badge").textContent =
        `API 호출 ${s.api_call_count || 0}회 · 토큰 ${(s.total_tokens || 0).toLocaleString()} · $${(s.total_cost_usd || 0).toFixed(4)}`;
    } catch {}
  }

  function startUsagePolling() {
    refreshUsage();
    state.usageTimer = setInterval(refreshUsage, 4000);
  }

  function stopUsagePolling() {
    if (state.usageTimer) clearInterval(state.usageTimer);
    state.usageTimer = null;
  }

  // ---------------------------------------------------------------- 초기화
  function init() {
    loadMeta();
    $("btn-start").addEventListener("click", startPipeline);
    $("gate1-approve").addEventListener("click", () => gate1Action("approve"));
    $("gate1-revise").addEventListener("click", () => gate1Action("revise"));
    $("gate1-regenerate").addEventListener("click", () => {
      if (confirm("아웃라인을 처음부터 다시 생성할까요?")) gate1Action("regenerate");
    });
    $("gate2-approve").addEventListener("click", () => gate2Action("approve"));
    $("gate2-revise").addEventListener("click", () => gate2Action("revise"));
    $("gate2-regenerate").addEventListener("click", () => {
      if (confirm("검증을 다시 실행할까요?")) gate2Action("regenerate");
    });
    $("btn-download-manuscript").addEventListener("click", () => {
      window.open(`/api/export/${state.sessionId}/manuscript`, "_blank");
    });
    $("btn-download-manuscript-pdf").addEventListener("click", () => {
      window.open(`/api/export/${state.sessionId}/manuscript-pdf`, "_blank");
    });
    $("btn-download-manuscript-md").addEventListener("click", () => {
      window.open(`/api/export/${state.sessionId}/manuscript-md`, "_blank");
    });
    $("btn-download-checklist").addEventListener("click", () => {
      window.open(`/api/export/${state.sessionId}/checklist`, "_blank");
    });
    $("btn-download-reviewer-qa").addEventListener("click", () => {
      window.open(`/api/export/${state.sessionId}/reviewer-qa`, "_blank");
    });
  }

  document.addEventListener("DOMContentLoaded", init);
})();
