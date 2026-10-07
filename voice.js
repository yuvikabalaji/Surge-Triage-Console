/* Live voice intake: Web Speech API transcription + keyword triage + vocal-stress estimate.
   Reuses DATA, render(), flyTo(), esc() from the dashboard script. */
(function () {
  const V = DATA.config.vocab;
  const $ = id => document.getElementById(id);
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const clamp = x => Math.max(0, Math.min(1, x));

  // ------------------------------------------------------------ scoring (mirror of engine.py)
  const clean = t => t.toLowerCase().replace(/['’]/g, "").replace(/\bfifth\b/g, "5th")
    .replace(/[^a-z0-9 \n]/g, "").replace(/\s+/g, " ").trim();
  const toks = t => clean(t).split(" ").filter(Boolean);
  const canon = t => new Set(toks(t).filter(w => !V.stop.includes(w) && w.length > 1).map(w => V.syn[w] || w));
  const dice = (a, b) => { if (!a.size || !b.size) return 0; let n = 0; a.forEach(x => b.has(x) && n++); return 2 * n / (a.size + b.size); };
  const hav = (a, b, c, d) => { const r = 6371000, p = Math.PI / 180, dp = (c - a) * p, dl = (d - b) * p;
    const h = Math.sin(dp / 2) ** 2 + Math.cos(a * p) * Math.cos(c * p) * Math.sin(dl / 2) ** 2; return 2 * r * Math.asin(Math.sqrt(h)); };

  function classify(text) {
    const set = new Set(toks(text)); let best = "other", bn = 0; const seen = new Set();
    for (const [t, words] of Object.entries(V.type_words)) {
      const n = words.filter(w => set.has(w)).length;
      if (n) seen.add(t);
      if (n > bn) { best = t; bn = n; }
    }
    return [best, seen.size ? seen : new Set(["other"])];
  }

  function scorePriority(raw, audioCue) {
    let text = clean(raw), points = 0; const reasons = [];
    for (const [ph, [pts, label]] of Object.entries(V.phrases)) {
      if (text.includes(ph)) { points += pts; reasons.push(`${label} (+${pts})`); text = text.split(ph).join(" "); }
    }
    const tk = text.split(" ").filter(Boolean), hits = new Set();
    tk.forEach((t, i) => {
      const w = V.words[t]; if (!w) return;
      if (tk.slice(Math.max(0, i - 6), i).some(x => V.negators.includes(x))) { reasons.push(`'${t}' negated - ignored`); return; }
      points += w[0]; hits.add(t); reasons.push(`${w[1]} (+${w[0]})`);
    });
    const vul = V.vulnerable.filter(x => tk.includes(x)).sort();
    if (vul.length) { points += 2; reasons.push(`vulnerable person: ${vul[0]} (+2)`);
      if (V.hazard.some(h => hits.has(h))) { points += 1; reasons.push("hazard + vulnerable person (+1)"); } }
    const place = V.critical.filter(p => clean(raw).includes(p));
    if (place.length) { points += 2; reasons.push(`critical location: ${place[0]} (+2)`); }
    const benign = V.benign.some(b => tk.includes(b));
    if (benign) { points = Math.min(points, 0); reasons.push("benign context (movie/bbq/etc.) - suppressed"); }
    else if (audioCue && audioCue.pts) { points += audioCue.pts; reasons.push(`${audioCue.label} (+${audioCue.pts})`); }
    return { points, reasons };
  }

  function analyze(text) {
    const cue = stressCue();
    const { points, reasons } = scorePriority(text, cue);
    return { points, reasons, level: levelOf(points), cue };
  }

  // ------------------------------------------------------------ audio / vocal stress
  const aud = { ctx: null, stream: null, an: null, timer: null, frames: [], hist: [], baseline: null, firstVoice: 0, live: 0, ok: false };
  const VOICED_DB = -48;

  async function startAudio() {
    aud.frames = []; aud.hist = []; aud.baseline = null; aud.firstVoice = 0; aud.live = 0; aud.ok = false;
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return;
    try {
      aud.stream = await navigator.mediaDevices.getUserMedia({ audio: { autoGainControl: false, noiseSuppression: false, echoCancellation: false } });
      aud.ctx = new (window.AudioContext || window.webkitAudioContext)();
      const src = aud.ctx.createMediaStreamSource(aud.stream);
      aud.an = aud.ctx.createAnalyser(); aud.an.fftSize = 1024; src.connect(aud.an);
      const buf = new Float32Array(aud.an.fftSize); let tick = 0;
      aud.ok = true;
      aud.timer = setInterval(() => {
        aud.an.getFloatTimeDomainData(buf);
        let sum = 0; for (const v of buf) sum += v * v;
        const db = 20 * Math.log10(Math.max(Math.sqrt(sum / buf.length), 1e-5));
        const now = performance.now(), voiced = db > VOICED_DB;
        aud.frames.push({ t: now, db, voiced });
        if (voiced && !aud.firstVoice) aud.firstVoice = now;
        $("dbv").textContent = db.toFixed(0) + " dBFS";
        $("dbbar").style.width = Math.round(clamp((db + 60) / 50) * 100) + "%";
        if (!aud.baseline) { const v = aud.frames.filter(f => f.voiced); if (v.length >= 20) aud.baseline = median(v.slice(0, 20).map(f => f.db)); }
        if (++tick % 5 === 0) updateStress();
      }, 100);
    } catch (e) { aud.ok = false; setStatus("Microphone level unavailable (" + e.name + "); stress index disabled."); }
  }

  function stopAudio() {
    clearInterval(aud.timer);
    if (aud.stream) aud.stream.getTracks().forEach(t => t.stop());
    if (aud.ctx) aud.ctx.close().catch(() => {});
    aud.stream = aud.ctx = null;
  }

  const median = a => { const s = [...a].sort((x, y) => x - y); return s[Math.floor(s.length / 2)]; };

  function updateStress() {
    const now = performance.now(), win = aud.frames.filter(f => now - f.t < 4000 && f.voiced);
    if (win.length < 5) return;
    const mean = win.reduce((s, f) => s + f.db, 0) / win.length;
    const words = toks($("vt").value).length, secs = (now - aud.firstVoice) / 1000;
    const wpm = secs > 4 ? words / secs * 60 : 0;
    const abs = clamp((mean + 32) / 14), rate = wpm ? clamp((wpm - 150) / 70) : 0;
    let idx;
    if (aud.baseline !== null) {
      const loud = clamp((mean - aud.baseline) / 10);
      const peak = clamp(win.filter(f => f.db > aud.baseline + 10).length / win.length / 0.2);
      idx = 100 * (0.3 * loud + 0.25 * abs + 0.2 * peak + 0.25 * rate);
    } else idx = 100 * (0.6 * abs + 0.4 * rate);
    aud.live = idx; aud.hist.push({ idx, mean });
    $("stv").textContent = Math.round(idx) + " (" + stressLabel(idx) + ")";
    $("stbar").style.width = Math.round(idx) + "%";
    $("stbar").style.background = idx >= 60 ? "var(--p1)" : idx >= 35 ? "var(--p2)" : "var(--ok)";
  }

  const stressLabel = i => i >= 60 ? "high" : i >= 35 ? "elevated" : "low";
  function stressFinal() {   // 85th percentile of the session, robust to a single spike
    if (aud.hist.length < 2) return null;
    const s = aud.hist.map(h => h.idx).sort((a, b) => a - b);
    const voiced = aud.frames.filter(f => f.voiced);
    const mean = voiced.length ? voiced.reduce((a, f) => a + f.db, 0) / voiced.length : -99;
    return { idx: s[Math.floor(s.length * 0.85)], whisper: voiced.length >= 10 && mean < -46, mean };
  }
  function stressCue() {
    const f = stressFinal(); if (!f) return null;
    if (f.whisper) return { pts: 2, label: "whispering caller", idx: f.idx };
    if (f.idx >= 60) return { pts: 2, label: "high vocal stress (loud/fast speech)", idx: f.idx };
    if (f.idx >= 35) return { pts: 1, label: "elevated vocal stress", idx: f.idx };
    return { pts: 0, label: "", idx: f.idx };
  }

  // ------------------------------------------------------------ recording state (plain object, same role as a React ref)
  const rec = { id: null, phone: null, lastPush: 0, isRecording: false, recognition: null, finalText: "", interim: "", restartTimer: null };

  function setStatus(t) { $("vstatus").textContent = t; }
  function warn(t) { const w = $("vwarn"); w.textContent = t; w.style.display = t ? "block" : "none"; }

  function buildRecognition() {
    const r = new SR();
    r.continuous = true; r.interimResults = true; r.lang = "en-US";
    r.onresult = e => {
      let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const txt = e.results[i][0].transcript;
        if (e.results[i].isFinal) rec.finalText += txt.trim() + " "; else interim += txt;
      }
      rec.interim = interim;
      $("vt").value = rec.finalText + interim;
      refreshLive(); liveUpdate();
    };
    r.onerror = e => {
      if (e.error === "no-speech" || e.error === "aborted") return;           // auto-restart handles it
      if (e.error === "not-allowed" || e.error === "service-not-allowed") { warn("Microphone permission was denied. Allow it in the address bar, or type the transcript instead."); rec.isRecording = false; }
      else if (e.error === "audio-capture") { warn("No microphone found."); rec.isRecording = false; }
      else if (e.error === "network") warn("Speech service unreachable (needs internet). You can type the transcript instead.");
    };
    r.onend = () => {                                                           // browsers stop on silence: restart while active
      if (!rec.isRecording) return;
      clearTimeout(rec.restartTimer);
      rec.restartTimer = setTimeout(() => { try { if (rec.isRecording) r.start(); } catch (_) { /* already started */ } }, 150);
    };
    return r;
  }

  async function startRecording() {
    warn("");
    rec.finalText = ""; rec.interim = ""; $("vt").value = ""; $("vresult").style.display = "none";
    rec.isRecording = true; rec.id = "LIVE-" + String(++liveN).padStart(2, "0"); rec.lastPush = 0;
    rec.phone = (await phoneLocation()) || { lat: CITY_FAR[0], lon: CITY_FAR[1], acc: 500 };
    rec.recognition = buildRecognition();
    try { rec.recognition.start(); } catch (e) { warn("Could not start speech recognition: " + e.message); rec.isRecording = false; return; }
    await startAudio();
    ui(true); $("vt").readOnly = true; setStatus("Recording... speak naturally. Press Stop & submit call when finished.");
  }

  function stopRecording() {
    if (!rec.isRecording) return;
    rec.isRecording = false;                                                    // stops auto-restart first
    clearTimeout(rec.restartTimer);
    setStatus("Finishing transcription...");
    $("mic").disabled = $("analyze").disabled = true;
    try { rec.recognition.stop(); } catch (_) {}
    setTimeout(() => {                                                          // let trailing final results arrive
      const text = (rec.finalText + rec.interim).trim();
      rec.interim = "";
      stopAudio(); ui(false); $("vt").readOnly = false; $("vt").value = text;
      if (text) submit(text, true); else { dropCall(rec.id); render(); setStatus("No speech captured. Try again or type the transcript."); }
    }, 800);
  }

  function ui(recording) {
    $("mic").classList.toggle("rec", recording);
    $("mic").disabled = false; $("analyze").disabled = false;
    $("analyze").textContent = recording ? "Stop & submit call" : "Analyze & submit as call";
  }

  // ------------------------------------------------------------ live keyword chips while speaking
  function refreshLive() {
    const text = $("vt").value.trim();
    if (!text) { $("livechips").innerHTML = ""; return; }
    const a = analyze(text);
    $("livechips").innerHTML = `<span class="badge ${a.level}">${a.level}</span> <span class="meta">${a.points} pts (live)</span><div class="tags">` +
      a.reasons.map(r => `<span>${esc(r)}</span>`).join("") + "</div>";
  }

  // ------------------------------------------------------------ submit the finalized transcript as a call
  const CITY_FAR = [40.78, -73.95];
  function phoneLocation() {
    const v = $("loc").value;
    if (v === "far") return Promise.resolve({ lat: CITY_FAR[0], lon: CITY_FAR[1], acc: 25 });
    if (v === "gps") return new Promise(res => {
      if (!navigator.geolocation) return res(null);
      navigator.geolocation.getCurrentPosition(p => res({ lat: p.coords.latitude, lon: p.coords.longitude, acc: p.coords.accuracy }), () => res(null), { timeout: 4000 });
    });
    const g = V.gazetteer[v];
    return Promise.resolve({ lat: g[0] + (Math.random() - .5) * 0.0004, lon: g[1] + (Math.random() - .5) * 0.0004, acc: 25 });
  }

  const typesOf = c => c._types || (c._types = classify(c.transcript)[1]);
  const toksOf = c => c._toks || (c._toks = canon(c.transcript));

  function pairScore(a, b, clTypes) {
    const d = hav(a.lat, a.lon, b.lat, b.lon), slack = Math.max(0, d - (a.acc + b.acc));
    let geo = Math.max(0, 1 - slack / 300); if (Math.max(a.acc, b.acc) > 300) geo *= .4;
    const dt = Math.abs(a.t - b.t), time = Math.max(0, 1 - dt / 40);
    const isOther = s => s.size === 1 && s.has("other");
    let compat, ts;
    if (isOther(typesOf(a)) || isOther(clTypes)) { compat = true; ts = .7; }
    else { compat = [...typesOf(a)].some(x => clTypes.has(x)); ts = compat ? 1 : 0; }
    const text = Math.min(1, dice(toksOf(a), toksOf(b)) / .35);
    let score = .4 * geo + .15 * time + .2 * ts + .25 * text;
    if (!compat) score *= .3;
    const same = a.caller === b.caller && dt <= 45;
    if (same) score = Math.max(score, .5) + .25;
    return { score, dist_m: Math.round(d), geo: +geo.toFixed(2), time: +time.toFixed(2), text: +text.toFixed(2), same_caller: same };
  }

  function placeLabel(lat, lon) {
    let best = "Unlabeled area", bd = 600;
    for (const [n, [a, b]] of Object.entries(V.gazetteer)) { const d = hav(lat, lon, a, b); if (d < bd) { bd = d; best = n.replace(/\b\w/g, c => c.toUpperCase()).replace("5Th", "5th"); } }
    return best;
  }

  let liveN = 0;
  function dropCall(id) {                                   // remove a provisional call (and its cluster if it was alone)
    const k = DATA.calls.findIndex(c => c.id === id); if (k < 0) return;
    const [c] = DATA.calls.splice(k, 1);
    if (c.cluster && !DATA.calls.some(x => x.cluster === c.cluster)) DATA.clusters = DATA.clusters.filter(x => x.id !== c.cluster);
  }

  function ingest(text, phone, id, final) {
    dropCall(id);
    const T = +$("slider").value, ct = clean(text);
    let lat = phone.lat, lon = phone.lon, acc = phone.acc, src = "phone";
    for (const [n, [gl, go]] of Object.entries(V.gazetteer)) {
      if (ct.includes(n)) { if (acc > 300 || hav(lat, lon, gl, go) > 500) { lat = gl; lon = go; acc = 60; src = "spoken address: " + n; } break; }
    }
    const a = analyze(text), [type, types] = classify(text);
    const accidental = V.accidental.some(k => text.toLowerCase().includes(k));
    const call = { id, t: T, caller: "live-" + id, transcript: text, audio: a.cue && a.cue.label ? a.cue.label : null,
      type, points: a.points, level: a.level, reasons: a.reasons, accidental, cluster: null, match: null,
      loc_source: src, lat, lon, acc, _types: types, _toks: canon(text) };
    if (!accidental) {
      let best = 0, bestCl = null, bestM = null, bestD = null;
      for (const cl of DATA.clusters) {
        const members = DATA.calls.filter(c => c.cluster === cl.id && !c.accidental && c.t <= T);
        if (!members.length) continue;
        const u = new Set(); members.forEach(m => typesOf(m).forEach(x => u.add(x))); u.delete("other");
        const clTypes = u.size ? u : new Set(["other"]);
        for (const m of members) { const r = pairScore(call, m, clTypes); if (r.score > best) { best = r.score; bestCl = cl; bestM = m; bestD = r; } }
      }
      if (bestCl && best >= DATA.config.threshold) {
        call.cluster = bestCl.id;
        call.match = { with: bestM.id, score: +Math.min(best, 1).toFixed(2), dist_m: bestD.dist_m, geo: bestD.geo, time: bestD.time, text: bestD.text, same_caller: bestD.same_caller };
      } else {
        const nid = Math.max(0, ...DATA.clusters.map(c => c.id)) + 1;
        DATA.clusters.push({ id: nid, place: placeLabel(lat, lon) }); call.cluster = nid;
      }
    }
    DATA.calls.push(call);
    render();
    showResult(call, a, final);
    return call;
  }

  function liveUpdate() {                                   // points and incident update while the caller is still talking
    const now = Date.now(), text = (rec.finalText + rec.interim).trim();
    if (!text || !rec.id || now - rec.lastPush < 1000) return;
    rec.lastPush = now;
    ingest(text, rec.phone, rec.id, false);
  }

  async function submit(text, final) {
    setStatus("Analyzing call...");
    const fromVoice = !!(rec.id && rec.phone);
    const phone = fromVoice ? rec.phone : ((await phoneLocation()) || { lat: CITY_FAR[0], lon: CITY_FAR[1], acc: 500 });
    const id = fromVoice ? rec.id : "LIVE-" + String(++liveN).padStart(2, "0");
    const call = ingest(text, phone, id, true);
    rec.id = null; rec.phone = null; rec.finalText = "";
    if (call.cluster) { flyTo(call.cluster); open.add(call.cluster); render(); }
    setStatus("Call submitted: " + call.level + " (" + call.points + " pts).");
  }

  function highlight(text) {
    const words = Object.keys(V.words).concat(V.vulnerable);
    return esc(text).replace(new RegExp("\\b(" + words.join("|") + ")\\b", "gi"), '<span class="hl">$1</span>');
  }

  function showResult(call, a, final) {
    const el = $("vresult"), cl = DATA.clusters.find(c => c.id === call.cluster);
    const link = call.accidental ? "Flagged as accidental call, excluded from incident counts."
      : call.match ? `Duplicate: linked to incident #${call.cluster} (${esc(cl.place)}), match score ${call.match.score} (${call.match.dist_m} m away).`
      : `New incident created: #${call.cluster} (${esc(cl.place)}).`;
    const st = a.cue ? `Vocal stress index ${Math.round(a.cue.idx)} (${stressLabel(a.cue.idx)})${a.cue.label ? " &rarr; " + esc(a.cue.label) + ` (+${a.cue.pts})` : ""}.`
      : "Vocal stress: not measured (no mic level data; typed or very short input).";
    el.style.display = "block";
    el.innerHTML = `<div class="top"><b>${call.id} &middot; ${call.points} pts ${final ? "" : "<span class=\"meta\">(live, updating)</span>"}</b><span class="badge ${call.level}">${call.level}</span></div>
      <p style="margin:6px 0">${highlight(call.transcript)}</p>
      <div class="tags">${call.reasons.map(r => `<span>${esc(r)}</span>`).join("")}</div>
      <p class="meta" style="margin:6px 0 0">${link}<br>${st}<br>Location: ${esc(call.loc_source)}</p>`;
  }

  // ------------------------------------------------------------ wiring
  (function init() {
    const sel = $("loc");
    sel.innerHTML = Object.keys(V.gazetteer).map(n => `<option value="${esc(n)}">Phone at ${esc(n)}</option>`).join("") +
      '<option value="far">Phone elsewhere (use spoken address)</option><option value="gps">Use my GPS</option>';
    $("analyze").onclick = () => {
      if (rec.isRecording) return stopRecording();                       // same button ends the recording
      const t = $("vt").value.trim(); if (t) submit(t, true); else setStatus("Nothing to analyze.");
    };
    $("vt").addEventListener("input", () => { if (!rec.isRecording) refreshLive(); });
    if (!SR) {
      warn("Voice typing is not supported in this browser. Use Chrome or Edge on desktop (served from localhost or https). You can still type or paste a transcript below and press Analyze.");
      $("mic").disabled = true; return;
    }
    $("mic").onclick = () => rec.isRecording ? stopRecording() : startRecording();
  })();
})();
