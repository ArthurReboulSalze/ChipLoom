/* ChipLoom Studio: the browser side of a live session. Plain JavaScript, no build step, no external
   resources. It talks only to /web/join and /web/api/<method> on its own origin. There is no code to type: on load
   the page joins the session and gets an HttpOnly cookie; it never holds a long-lived secret (only a
   per-device CSRF value in memory). */
"use strict";
(() => {
  // ---------------------------------------------------------------------------------------------
  // helpers
  const Cells = window.ChipLoomCells;   // cells.js: the grid's cell spelling for MOD and XM
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  function h(tag, props, ...kids) {
    const el = document.createElement(tag);
    for (const [key, value] of Object.entries(props || {})) {
      if (value === null || value === undefined || value === false) continue;
      if (key === "class") el.className = value;
      else if (key === "text") el.textContent = value;
      else if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
      else if (value === true) el.setAttribute(key, "");
      else el.setAttribute(key, String(value));
    }
    for (const kid of kids.flat(Infinity)) {
      if (kid === null || kid === undefined || kid === false) continue;
      el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    }
    return el;
  }

  function fill(el, ...kids) {
    el.replaceChildren(...kids.flat(Infinity).filter((kid) => kid !== null && kid !== undefined && kid !== false));
  }

  const store = {
    get(key) { try { return localStorage.getItem("chiploom." + key); } catch (e) { return null; } },
    set(key, value) { try { localStorage.setItem("chiploom." + key, value); } catch (e) { /* private mode */ } },
  };

  const hex2 = (n) => n.toString(16).toUpperCase().padStart(2, "0");
  const fmtTime = (s) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`;
  const clamp = (n, lo, hi) => Math.min(hi, Math.max(lo, n));

  // ---------------------------------------------------------------------------------------------
  // translations
  const I18N = {
    en: {
      "connect.tagline": "Compose with your agent from this browser",
      "connect.connecting": "Connecting…",
      "connect.lost": "Connection lost. The session may have been stopped: check that ChipLoom is still running, then try again.",
      "aria.theme": "Change colour theme", "aria.lang": "Change language",
      "aria.grid": "Pattern grid", "aria.close": "Close the editor", "aria.channels": "Channels you hear",
      "theme.auto": "Auto", "theme.dark": "Midnight", "theme.light": "Light",
      "track": "Track {n}", "track.muted": "Track {n} · MUTED",
      "tab.score": "Score", "tab.agent": "Agent",
      "orders": "Orders", "pattern": "Pattern", "block": "Select block", "block.done": "Done selecting",
      "editor": "Cell editor", "proposals": "Agent proposals", "activity": "Recent changes", "takes": "Takes",
      "speakers": "Sound", "speakers.here": "This device", "speakers.computer": "Computer",
      "listen.row": "From row {row}", "listen.block": "Rows {row}–{end}", "listen.order": "Order", "listen.stop": "Stop", "listen.length": "Length",
      "listen.sec": "{n} s", "listen.nochan": "Keep at least one channel on.",
      "player.idle": "Pick a spot in the score and press play. The section is rendered by ChipLoom and played here.",
      "player.rendering": "Rendering…", "player.ready": "{engine} · {seconds} s from order {order}, row {row}",
      "player.computer": "Playing on the computer from order {order}.", "player.stopped": "Stopped.",
      "player.unavailable": "Listening here needs libxmp or FFmpeg on the computer that runs ChipLoom.",
      "player.autoplay": "Ready. Press play on the player to listen.",
      "player.noorder": "This pattern is not in the order list, so it cannot be played from here yet.",
      "net.live": "Live", "net.sync": "Syncing", "net.offline": "Reconnecting…",
      "net.offline.long": "The connection to ChipLoom dropped. Trying again…",
      "net.lost": "ChipLoom is not answering. Check that the session is still running; this page keeps trying.",
      "hint.tap": "Tap a cell to edit it. Arrow keys move, Enter opens the editor, Delete clears.",
      "hint.block1": "Block mode: tap the first corner of the block.", "hint.block2": "Now tap the opposite corner.",
      "hint.block3": "Block selected. Use the tools, or tap a corner to start again.",
      "grid.row": "ROW", "grid.loading": "Loading the pattern…", "grid.error": "The pattern could not be loaded.", "retry": "Try again",
      "cell.aria": "Row {row}, channel {ch}: {text}", "cell.empty": "empty",
      "ed.none": "Select a cell to edit it", "ed.none.hint": "Notes, samples and effects are edited here. Your changes appear for your agent and in the window at once.",
      "ed.where": "Row {row} · Channel {ch}", "ed.prev": "Row above", "ed.next": "Row below", "ed.left": "Channel on the left", "ed.right": "Channel on the right",
      "ed.note": "Note", "ed.octave": "Octave {n}", "ed.nonote": "No note", "ed.sample": "Sample", "ed.nosample": "No sample", "ed.noinstrument": "No instrument",
      "ed.effect": "Effect", "ed.noeffect": "No effect", "ed.param": "Value", "ed.raw": "Cell text",
      "ed.apply": "Apply", "ed.clear": "Clear cell", "ed.show": "Show on computer", "ed.changed": "This cell changed while you were editing (now {text}).",
      "ed.reload": "Load it", "ed.same": "Nothing to change.", "ed.saved": "Saved",
      "ed.err.format": "Use a note like C-2 or G#3 (or ---), a sample 00-1F (or --) and an effect like C20 (or ...).",
      "ed.err.format.xm": "Use a note like C-4 or G#3 (or --- or ===), an instrument (or --), a volume byte (or --) and an effect like A0F or G40 (or ...).",
      "ed.err.note": "Unknown note for this song; use {range}.", "ed.err.volume": "Volume-column bytes are 10-50 (volume) or 60-FF (slides, vibrato, panning, portamento).",
      "ed.err.effect": "This effect is not available in this format.",
      "ed.instrument": "Instrument", "ed.volume": "Volume column", "ed.vol.none": "No volume column", "ed.keyoff": "Key off", "ed.oct": "Oct {n}",
      "vol.vol": "Set volume (0-64)", "vol.vsd": "Volume slide down", "vol.vsu": "Volume slide up", "vol.vfd": "Fine volume down", "vol.vfu": "Fine volume up",
      "vol.vib": "Vibrato speed", "vol.vid": "Vibrato depth", "vol.pan": "Set panning", "vol.psl": "Panning slide left", "vol.psr": "Panning slide right", "vol.tpo": "Tone portamento",
      "chip.channels": "{n} ch", "player.alltracks": "All tracks on", "player.tracks": "Click a track header to mute it.",
      "ed.err.sample": "The sample must be between 00 and 1F.",
      "blk.title": "Block", "blk.size": "Rows {row}–{end} · channel {c1}{c2}  ({n} cells)", "blk.hint": "Tap two corners in the grid to choose a block.",
      "blk.move": "Move", "blk.up": "Up one row", "blk.down": "Down one row", "blk.left": "One channel left", "blk.right": "One channel right",
      "blk.dup": "Duplicate below", "blk.copyto": "Copy to pattern", "blk.copy": "Copy", "blk.transpose": "Transpose", "blk.clear": "Clear block",
      "blk.bounds": "The block cannot go past the edge of the pattern.", "blk.st": "{n} semitones", "blk.done": "Done",
      "conflict.title": "Someone changed these cells first",
      "conflict.row": "Row {row}, channel {ch}: now {current} (by {who}), you wanted {yours}",
      "conflict.other": "{unit} was changed by {who}.", "conflict.keep": "Keep theirs", "conflict.overwrite": "Overwrite",
      "props.empty": "No proposal waiting", "props.empty.hint": "When your agent suggests a change instead of making it, it appears here with a preview you can hear.",
      "props.cells": "{n} cells", "props.stale": "Changed since", "props.preview": "Preview", "props.hide": "Hide preview",
      "props.listen": "Listen", "props.accept": "Accept", "props.anyway": "Accept anyway", "props.reject": "Reject",
      "props.more": "…and {n} more", "props.other": "Also changes: {what}", "props.accepted": "Accepted", "props.rejected": "Rejected",
      "confirm.sure": "Sure?", "confirm.overwrite": "Overwrite my edits?",
      "act.empty": "Nothing yet", "act.empty.hint": "Your edits, the window's and your agent's show up here as they happen.",
      "who.me": "You (browser)", "who.window": "Window", "who.file": "File", "act.more": "…",
      "takes.empty": "No take yet", "takes.empty.hint": "Your agent can save a version of the song for you to hear and compare.",
      "takes.listen": "Listen", "takes.by": "by {who}",
      "chip.bpm": "BPM", "chip.speed": "Speed", "chip.time": "Time", "chip.rev": "Rev", "chip.window": "Window open", "chip.headless": "No window", "chip.devices": "{n} browser(s)",
      "err.NETWORK": "ChipLoom did not answer. Check the connection and that the session is still running.",
      "err.LIVE_WEB_AUTH": "This browser could not join the session.", "err.LIVE_BUSY": "A section is still rendering; try again in a moment.",
      "err.LIVE_NO_WINDOW": "No ChipLoom window is open, so the computer cannot play.",
      "err.LIVE_RENDER_UNAVAILABLE": "Listening here needs libxmp or FFmpeg on the computer that runs ChipLoom.",
      "err.LIVE_CSRF": "The page is out of date; reload it.", "toast.accepted": "Proposal accepted", "toast.rejected": "Proposal rejected",
    },
    fr: {
      "connect.tagline": "Compose avec ton agent depuis ce navigateur",
      "connect.connecting": "Connexion…",
      "connect.lost": "Connexion perdue. La session a peut-être été arrêtée : vérifie que ChipLoom tourne toujours, puis réessaie.",
      "aria.theme": "Changer le thème de couleurs", "aria.lang": "Changer de langue",
      "aria.grid": "Grille du pattern", "aria.close": "Fermer l'éditeur", "aria.channels": "Canaux écoutés",
      "theme.auto": "Auto", "theme.dark": "Minuit", "theme.light": "Clair",
      "track": "Voie {n}", "track.muted": "Voie {n} · MUET",
      "tab.score": "Partition", "tab.agent": "Agent",
      "orders": "Ordres", "pattern": "Pattern", "block": "Sélectionner un bloc", "block.done": "Fin de sélection",
      "editor": "Éditeur de cellule", "proposals": "Propositions de l'agent", "activity": "Modifications récentes", "takes": "Prises",
      "speakers": "Son", "speakers.here": "Cet appareil", "speakers.computer": "Ordinateur",
      "listen.row": "Depuis la ligne {row}", "listen.block": "Lignes {row}–{end}", "listen.order": "Ordre", "listen.stop": "Stop", "listen.length": "Durée",
      "listen.sec": "{n} s", "listen.nochan": "Garde au moins un canal actif.",
      "player.idle": "Choisis un endroit de la partition et lance la lecture. ChipLoom calcule l'extrait et il se joue ici.",
      "player.rendering": "Calcul de l'extrait…", "player.ready": "{engine} · {seconds} s depuis l'ordre {order}, ligne {row}",
      "player.computer": "Lecture sur l'ordinateur depuis l'ordre {order}.", "player.stopped": "Arrêté.",
      "player.unavailable": "L'écoute ici demande libxmp ou FFmpeg sur l'ordinateur qui fait tourner ChipLoom.",
      "player.autoplay": "Prêt. Appuie sur lecture dans le lecteur pour écouter.",
      "player.noorder": "Ce pattern n'est pas dans la liste d'ordres : on ne peut pas encore le jouer d'ici.",
      "net.live": "En direct", "net.sync": "Synchronisation", "net.offline": "Reconnexion…",
      "net.offline.long": "La connexion à ChipLoom a été coupée. Nouvelle tentative…",
      "net.lost": "ChipLoom ne répond plus. Vérifie que la session tourne toujours ; cette page continue d'essayer.",
      "hint.tap": "Touche une cellule pour la modifier. Flèches : déplacer, Entrée : éditeur, Suppr : effacer.",
      "hint.block1": "Mode bloc : touche le premier coin du bloc.", "hint.block2": "Touche maintenant le coin opposé.",
      "hint.block3": "Bloc choisi. Utilise les outils, ou touche un coin pour recommencer.",
      "grid.row": "LIGNE", "grid.loading": "Chargement du pattern…", "grid.error": "Impossible de charger le pattern.", "retry": "Réessayer",
      "cell.aria": "Ligne {row}, canal {ch} : {text}", "cell.empty": "vide",
      "ed.none": "Choisis une cellule à modifier", "ed.none.hint": "Notes, samples et effets se modifient ici. Tes changements apparaissent aussitôt chez ton agent et dans la fenêtre.",
      "ed.where": "Ligne {row} · Canal {ch}", "ed.prev": "Ligne au-dessus", "ed.next": "Ligne en dessous", "ed.left": "Canal de gauche", "ed.right": "Canal de droite",
      "ed.note": "Note", "ed.octave": "Octave {n}", "ed.nonote": "Aucune note", "ed.sample": "Sample", "ed.nosample": "Aucun sample", "ed.noinstrument": "Aucun instrument",
      "ed.effect": "Effet", "ed.noeffect": "Aucun effet", "ed.param": "Valeur", "ed.raw": "Texte de la cellule",
      "ed.apply": "Appliquer", "ed.clear": "Vider la cellule", "ed.show": "Montrer sur l'ordinateur", "ed.changed": "Cette cellule a changé pendant que tu la modifiais (maintenant {text}).",
      "ed.reload": "La charger", "ed.same": "Rien à changer.", "ed.saved": "Enregistré",
      "ed.err.format": "Utilise une note comme C-2 ou G#3 (ou ---), un sample 00-1F (ou --) et un effet comme C20 (ou ...).",
      "ed.err.format.xm": "Utilise une note comme C-4 ou G#3 (ou --- ou ===), un instrument (ou --), un octet de volume (ou --) et un effet comme A0F ou G40 (ou ...).",
      "ed.err.note": "Note inconnue pour ce morceau ; utilise {range}.", "ed.err.volume": "Les octets de la colonne volume vont de 10 à 50 (volume) ou de 60 à FF (glissements, vibrato, panoramique, portamento).",
      "ed.err.effect": "Cet effet n'existe pas dans ce format.",
      "ed.instrument": "Instrument", "ed.volume": "Colonne volume", "ed.vol.none": "Pas de colonne volume", "ed.keyoff": "Fin de note", "ed.oct": "Oct. {n}",
      "vol.vol": "Volume (0-64)", "vol.vsd": "Glissement de volume bas", "vol.vsu": "Glissement de volume haut", "vol.vfd": "Volume fin bas", "vol.vfu": "Volume fin haut",
      "vol.vib": "Vitesse du vibrato", "vol.vid": "Profondeur du vibrato", "vol.pan": "Panoramique", "vol.psl": "Glissement panoramique gauche", "vol.psr": "Glissement panoramique droite", "vol.tpo": "Portamento",
      "chip.channels": "{n} voies", "player.alltracks": "Toutes les voies actives", "player.tracks": "Touche l'en-tête d'une voie pour la couper.",
      "ed.err.sample": "Le sample doit être compris entre 00 et 1F.",
      "blk.title": "Bloc", "blk.size": "Lignes {row}–{end} · canal {c1}{c2}  ({n} cellules)", "blk.hint": "Touche deux coins dans la grille pour choisir un bloc.",
      "blk.move": "Déplacer", "blk.up": "Une ligne plus haut", "blk.down": "Une ligne plus bas", "blk.left": "Un canal à gauche", "blk.right": "Un canal à droite",
      "blk.dup": "Dupliquer en dessous", "blk.copyto": "Copier vers le pattern", "blk.copy": "Copier", "blk.transpose": "Transposer", "blk.clear": "Vider le bloc",
      "blk.bounds": "Le bloc ne peut pas dépasser le bord du pattern.", "blk.st": "{n} demi-tons", "blk.done": "Terminé",
      "conflict.title": "Quelqu'un a modifié ces cellules avant toi",
      "conflict.row": "Ligne {row}, canal {ch} : maintenant {current} (par {who}), tu voulais {yours}",
      "conflict.other": "{unit} a été modifié par {who}.", "conflict.keep": "Garder la version de l'autre", "conflict.overwrite": "Écraser",
      "props.empty": "Aucune proposition en attente", "props.empty.hint": "Quand ton agent suggère un changement au lieu de le faire, il apparaît ici avec un aperçu que tu peux écouter.",
      "props.cells": "{n} cellules", "props.stale": "Modifié depuis", "props.preview": "Aperçu", "props.hide": "Masquer l'aperçu",
      "props.listen": "Écouter", "props.accept": "Accepter", "props.anyway": "Accepter quand même", "props.reject": "Refuser",
      "props.more": "…et {n} de plus", "props.other": "Change aussi : {what}", "props.accepted": "Acceptée", "props.rejected": "Refusée",
      "confirm.sure": "Sûr ?", "confirm.overwrite": "Écraser mes modifications ?",
      "act.empty": "Rien pour l'instant", "act.empty.hint": "Tes modifications, celles de la fenêtre et celles de ton agent apparaissent ici au fur et à mesure.",
      "who.me": "Toi (navigateur)", "who.window": "Fenêtre", "who.file": "Fichier", "act.more": "…",
      "takes.empty": "Aucune prise", "takes.empty.hint": "Ton agent peut enregistrer une version du morceau pour que tu l'écoutes et la compares.",
      "takes.listen": "Écouter", "takes.by": "par {who}",
      "chip.bpm": "BPM", "chip.speed": "Vitesse", "chip.time": "Durée", "chip.rev": "Rév.", "chip.window": "Fenêtre ouverte", "chip.headless": "Sans fenêtre", "chip.devices": "{n} navigateur(s)",
      "err.NETWORK": "ChipLoom ne répond pas. Vérifie la connexion et que la session tourne toujours.",
      "err.LIVE_WEB_AUTH": "Ce navigateur n'a pas pu rejoindre la session.", "err.LIVE_BUSY": "Un extrait est encore en calcul ; réessaie dans un instant.",
      "err.LIVE_NO_WINDOW": "Aucune fenêtre ChipLoom n'est ouverte : l'ordinateur ne peut pas jouer.",
      "err.LIVE_RENDER_UNAVAILABLE": "L'écoute ici demande libxmp ou FFmpeg sur l'ordinateur qui fait tourner ChipLoom.",
      "err.LIVE_CSRF": "La page n'est plus à jour ; recharge-la.", "toast.accepted": "Proposition acceptée", "toast.rejected": "Proposition refusée",
    },
  };
  // Effect names by letter. MOD letters 0-F (E is the extended family) and the XM letters G-X.
  const FX = {
    en: { "0": "Arpeggio", "1": "Slide up", "2": "Slide down", "3": "Tone portamento", "4": "Vibrato", "5": "Portamento + volume slide",
          "6": "Vibrato + volume slide", "7": "Tremolo", "8": "Set panning", "9": "Sample offset", A: "Volume slide", B: "Position jump",
          C: "Set volume", D: "Pattern break", E: "Extended (Exy)", F: "Speed / tempo", G: "Set global volume", H: "Global volume slide",
          K: "Key off", L: "Set envelope position", P: "Panning slide", R: "Multi retrigger", T: "Tremor", X: "Extra fine slide" },
    fr: { "0": "Arpège", "1": "Glissando haut", "2": "Glissando bas", "3": "Portamento", "4": "Vibrato", "5": "Portamento + volume",
          "6": "Vibrato + volume", "7": "Trémolo", "8": "Panoramique", "9": "Décalage du sample", A: "Glissement de volume", B: "Saut de position",
          C: "Volume", D: "Saut de pattern", E: "Étendu (Exy)", F: "Vitesse / tempo", G: "Volume global", H: "Glissement du volume global",
          K: "Fin de note", L: "Position d'enveloppe", P: "Glissement panoramique", R: "Re-déclenchement", T: "Tremor", X: "Glissement extra fin" },
  };

  // ---------------------------------------------------------------------------------------------
  // state
  const S = {
    lang: store.get("lang") || ((navigator.language || "en").toLowerCase().startsWith("fr") ? "fr" : "en"),
    theme: ["dark", "light", "auto"].includes(store.get("theme")) ? store.get("theme") : "dark",
    csrf: null, status: null, overview: null, revision: 0,
    order: 0, pattern: 0, cells: null, els: null, loadedPattern: null,
    sel: null, block: null, blockMode: false, anchor: null, sheet: false,
    draft: null, baseText: null, dirty: false, octave: 2, conflict: null, editorError: "",
    proposals: [], takes: [], activity: [], preview: null,
    profile: null, channels: 4, rows: 64, gridKey: null,
    audible: [], seconds: 20, speaker: "browser", renderSeq: 0, objectUrl: null,
    joining: null, connect: null, failures: 0, ticks: 0, timer: null, running: false, busy: false, tab: "score", flashTimers: new Map(),
  };

  const t = (key, vars) => {
    const text = (I18N[S.lang] || {})[key] ?? I18N.en[key] ?? key;
    return vars ? text.replace(/\{(\w+)\}/g, (_, name) => (vars[name] ?? "")) : text;
  };

  class ApiError extends Error {
    constructor(data, status) {
      super((data && data.message) || `HTTP ${status}`);
      this.code = (data && data.code) || (status ? "HTTP_" + status : "NETWORK");
      this.status = status; this.data = data || {};
    }
  }
  const errText = (e) => (e instanceof ApiError ? (I18N[S.lang]["err." + e.code] || e.message) : String(e && e.message || e));

  async function post(url, body, extra = {}) {
    let response;
    try {
      response = await fetch(url, {
        method: "POST", credentials: "same-origin", cache: "no-store",
        headers: { "Content-Type": "application/json", ...(S.csrf ? { "X-ChipLoom-CSRF": S.csrf } : {}) },
        body: JSON.stringify(body || {}),
      });
    } catch (e) { throw new ApiError(null, 0); }
    if (extra.blob && response.ok) {
      let info = {};
      try { info = JSON.parse(response.headers.get("X-ChipLoom-Render") || "{}"); } catch (e) { /* header optional */ }
      return { blob: await response.blob(), info };
    }
    let data = null;
    try { data = await response.json(); } catch (e) { /* not JSON */ }
    if (!response.ok || !data || data.ok === false) throw new ApiError(data, response.status);
    return data;
  }
  // Joining is automatic: a same-origin POST that sets this browser's HttpOnly cookie and returns its CSRF value.
  // Shared, so several calls failing together join once.
  function join() {
    if (!S.joining) {
      S.joining = post("/web/join", {}).then((data) => { S.csrf = data.csrf; return data; }).finally(() => { S.joining = null; });
    }
    return S.joining;
  }
  // A call refused for lack of a cookie (expired, or the session restarted) joins again and is repeated once.
  async function api(method, params, extra) {
    try {
      return await post("/web/api/" + method, params, extra);
    } catch (e) {
      if (e.code !== "LIVE_WEB_AUTH") throw e;
      await join();
      return post("/web/api/" + method, params, extra);
    }
  }

  // ---------------------------------------------------------------------------------------------
  // theme, language
  function applyTheme() {
    const root = document.documentElement;
    root.setAttribute("data-theme", S.theme);
    $$("[data-theme-label]").forEach((el) => { el.textContent = t("theme." + S.theme); });
  }
  function cycleTheme() {
    S.theme = { dark: "light", light: "auto", auto: "dark" }[S.theme] || "dark";
    store.set("theme", S.theme); applyTheme();
  }
  function applyI18n() {
    document.documentElement.lang = S.lang;
    $$("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
    $$("[data-i18n-html]").forEach((el) => { el.innerHTML = t(el.dataset.i18nHtml); });
    $$("[data-i18n-aria]").forEach((el) => el.setAttribute("aria-label", t(el.dataset.i18nAria)));
    $$("[data-i18n-placeholder]").forEach((el) => el.setAttribute("placeholder", t(el.dataset.i18nPlaceholder)));
    applyTheme();
    renderConnect();
    if (S.status) renderAll();
  }
  function toggleLang() {
    S.lang = S.lang === "fr" ? "en" : "fr"; store.set("lang", S.lang); applyI18n();
  }

  // ---------------------------------------------------------------------------------------------
  // toasts and small widgets
  function toast(message, error = false) {
    const el = h("div", { class: "toast" + (error ? " error" : ""), text: message });
    $("#toasts").append(el);
    setTimeout(() => el.remove(), error ? 6500 : 3200);
  }
  function confirmInline(button, label, action) {
    let armed = false, timer = null, original = [];
    const disarm = () => { armed = false; clearTimeout(timer); button.replaceChildren(...original); button.classList.remove("danger"); };
    button.addEventListener("click", () => {
      if (!armed) {
        armed = true; original = Array.from(button.childNodes); button.replaceChildren(label); button.classList.add("danger");
        timer = setTimeout(disarm, 4000);
        return;
      }
      disarm(); action();
    });
  }
  const who = (author) => (author === "human-web" ? t("who.me") : author === "human" ? t("who.window") : author === "file" ? t("who.file") : author);
  const whoClass = (author) => (author === "human-web" ? "me" : author === "human" || author === "file" ? "win" : "agent");
  // comments.js: comments with a place (button, grid markers, the Agent tab's list); merges its strings into I18N.
  const Comments = window.ChipLoomComments.create({ S, I18N, h, fill, $, api, t, toast, errText, who, whoClass, hex2,
    selectPattern, toggleBlockMode, updateSelectionClasses, renderEditor, renderPlayer, paintGrid, showTab });

  // ---------------------------------------------------------------------------------------------
  // connecting
  function renderConnect() {
    const c = S.connect;
    if (!c) return;
    $("#connect-spinner").hidden = c.kind !== "connecting";
    $("#connect-text").textContent = c.kind === "connecting" ? t("connect.connecting") : "";
    $("#connect-text").hidden = c.kind !== "connecting";
    $("#connect-error").textContent = c.kind === "error" ? (c.key ? t(c.key) : c.message) : "";
    $("#connect-retry").hidden = c.kind !== "error";
  }
  function showConnect(kind, { key = null, message = "" } = {}) {
    stopPolling();
    S.connect = { kind, key, message };
    $("#studio").hidden = true; $("#connect").hidden = false; $("#offline").hidden = true;
    S.csrf = null; S.status = null;
    renderConnect();
    if (kind === "error") setTimeout(() => $("#connect-retry").focus(), 30);
  }
  const connectionLost = () => showConnect("error", { key: "connect.lost" });

  async function connect() {
    showConnect("connecting");
    try {
      await join();
      await enterStudio();
    } catch (e) {
      showConnect("error", e.code === "NETWORK" ? { key: "err.NETWORK" } : { message: errText(e) });
    }
  }

  // ---------------------------------------------------------------------------------------------
  // loading data
  async function enterStudio() {
    const hello = await api("hello");
    S.csrf = hello.csrf; S.status = hello;
    S.seconds = Math.min(S.seconds, hello.render.max_seconds);
    $("#connect").hidden = true; $("#studio").hidden = false;
    buildStatic();
    renderHeader(); renderPlayer(); renderEditor(true); renderGridLoading();
    try {
      const overview = await loadOverview();     // also brings the grid shape and the cell vocabulary (S.profile)
      S.order = 0; S.pattern = overview.orders[0] ?? 0;
      S.revision = overview.revision;
      await loadPattern();
      await Promise.all([loadProposals(), loadTakes(), loadActivity(), Comments.load()]);
    } catch (e) {
      if (e.code === "LIVE_WEB_AUTH") return connectionLost();
      renderGridError(e);
    }
    startPolling();
  }

  async function loadOverview() {
    const data = await api("score");
    S.overview = data; S.profile = data.profile;
    syncChannels();
    renderOrders(); renderPatternSelect(); renderHeader(); renderPlayer();
    return data;
  }

  // One listening state per channel: a different file may have another channel count.
  function syncChannels() {
    const count = S.profile.channels;
    S.channels = count;
    if (S.audible.length !== count) {
      const window = S.status && Array.isArray(S.status.audible) && S.status.audible.length === count ? S.status.audible : null;
      S.audible = window ? window.slice() : new Array(count).fill(true);
      S.audibleTouched = false;
    }
  }

  async function loadPattern() {
    const total = (S.overview.patterns[S.pattern] || {}).rows || 64;       // 64 in a MOD, 1-256 in an XM
    const data = await api("score", { pattern: S.pattern, start: 0, rows: total });
    const cells = data.lines.map(Cells.splitLine);
    S.rows = cells.length;
    const key = `${S.profile.format}|${S.rows}|${S.channels}`;
    const previous = S.loadedPattern === S.pattern && S.gridKey === key ? S.cells : null;
    S.cells = cells;
    if (S.loadedPattern !== S.pattern || !S.els || S.gridKey !== key) { S.gridKey = key; buildGrid(); }
    S.loadedPattern = S.pattern;
    paintGrid();
    return { data, previous };
  }

  async function loadProposals() {
    const data = await api("proposals");
    S.proposals = data.proposals;
    if (S.preview && !S.proposals.some((p) => p.id === S.preview)) S.preview = null;
    renderProposals(); paintGrid();
  }
  async function loadTakes() {
    S.takes = (await api("takes")).takes; renderTakes();
  }
  async function loadActivity() {
    const data = await api("changes", { since: Math.max(0, S.revision - 25) });
    S.activity = data.entries.slice().reverse().slice(0, 30); renderActivity();
  }

  // ---------------------------------------------------------------------------------------------
  // polling: the session revision decides what to reload
  function startPolling() { stopPolling(); S.running = true; schedule(250); }
  function stopPolling() { S.running = false; clearTimeout(S.timer); }
  function schedule(ms) { clearTimeout(S.timer); if (S.running) S.timer = setTimeout(poll, ms); }
  document.addEventListener("visibilitychange", () => { if (!document.hidden && S.running) schedule(50); });

  async function poll() {
    if (!S.running) return;
    if (document.hidden) return schedule(1500);
    try {
      const changes = await api("changes", { since: S.revision });
      S.ticks += 1;
      let reload = changes.revision !== S.revision || changes.gap;
      if (reload) await onRevision(changes);
      if (reload || S.ticks % 3 === 0) await refreshStatus();
      S.failures = 0; setNet("live");
      schedule(1000);
    } catch (e) {
      if (e.code === "LIVE_WEB_AUTH") return connectionLost();
      S.failures += 1; setNet("offline"); schedule(Math.min(1000 * 2 ** S.failures, 8000));
    }
  }

  async function onRevision(changes) {
    const foreign = changes.entries.filter((entry) => !entry.own);
    S.activity = [...changes.entries.slice().reverse(), ...S.activity].slice(0, 30);
    renderActivity();
    const structural = changes.gap || changes.entries.some((entry) => entry.structure);
    const touchesPattern = structural || changes.entries.some((entry) => entry.patterns.includes(S.pattern));
    if (structural) {
      await loadOverview();
      if (!S.overview.patterns[S.pattern]) { S.pattern = S.overview.orders[0] ?? 0; S.order = 0; S.loadedPattern = null; }
      renderPatternSelect();
    }
    if (touchesPattern) {
      const { previous } = await loadPattern();
      if (previous && foreign.length) {
        const kind = foreign.some((entry) => entry.author !== "human" && entry.author !== "file") ? "agent" : "mine";
        flashChanged(previous, S.cells, kind);
      }
    }
    await loadProposals();
    await Comments.onChanges(changes);
    S.revision = Math.max(S.revision, changes.revision);   // only once everything above was reloaded
  }

  async function refreshStatus() {
    const status = await api("status");
    const takesChanged = status.takes !== S.takes.length;
    S.status = { ...S.status, ...status };
    if (Array.isArray(status.audible) && !S.audibleTouched && status.audible.length === S.channels) S.audible = status.audible.slice();
    renderHeader(); renderPlayer();
    if (takesChanged) await loadTakes();
    await Comments.onStatus(status);
  }

  function setNet(state) {
    const dot = $("#net-dot"); $("#net").dataset.state = state;
    dot.className = "dot " + (state === "live" ? "live" : state === "sync" ? "warn" : "bad");
    $("#net-text").textContent = t("net." + state);
    // Tablets and phones hide the small status text, so a lost connection also gets a banner (after two misses, to avoid flicker).
    const banner = $("#offline"), lost = state === "offline" && S.failures >= 2;
    banner.hidden = !lost;
    if (lost) $("#offline-text").textContent = t(S.failures >= 5 ? "net.lost" : "net.offline.long");
  }

  // ---------------------------------------------------------------------------------------------
  // header
  function chip(label, value, optional, tight, low) { return h("span", { class: "chip" + (optional ? " opt" : "") + (tight ? " tight" : "") + (low ? " lo" : "") }, h("span", { class: "k", text: label + " " }), h("b", { text: value })); }

  function renderHeader() {
    const s = S.status; if (!s) return;
    $("#song-title").textContent = s.title || "";
    document.title = `${s.title || "ChipLoom"} · ChipLoom Studio`;
    const meta = $("#song-meta"); meta.replaceChildren(
      h("span", { class: "chip" }, h("b", { text: (s.format || "mod").toUpperCase() }), " " + t("chip.channels", { n: s.channels || 4 })),
      chip(t("chip.bpm"), s.bpm), chip(t("chip.speed"), s.speed, true), chip(t("chip.time"), fmtTime(s.duration_seconds), false, true),
      chip(t("chip.rev"), s.revision, true, false, true),
      h("span", { class: "chip opt" }, h("span", { class: "dot " + (s.window ? "live" : "") }), s.window ? t("chip.window") : t("chip.headless")));
  }

  // ---------------------------------------------------------------------------------------------
  // orders and pattern select
  function renderOrders() {
    const host = $("#orders-field");
    let box = $("#orders", host);
    if (!box) { box = h("div", { class: "orders", id: "orders", role: "listbox", "aria-labelledby": "orders-label" }); host.append(box); }
    box.replaceChildren(...S.overview.orders.map((pattern, index) => h("button", {
      class: "btn order", type: "button", role: "option", "aria-selected": String(index === S.order),
      "aria-label": `${t("orders")} ${index}: ${t("pattern")} ${pattern}`,
      onclick: () => selectOrder(index),
    }, h("small", { text: hex2(index) }), h("span", { text: "P" + hex2(pattern) }))));
    const current = $(`[aria-selected="true"]`, box);
    if (current) {
      const a = current.getBoundingClientRect(), b = box.getBoundingClientRect();
      box.scrollLeft += a.left - b.left - (b.width - a.width) / 2;
    }
  }

  function renderPatternSelect() {
    const select = $("#pattern-select");
    select.replaceChildren(...S.overview.patterns.map((p) => h("option", { value: p.index, text:
      `${hex2(p.index)} · ${p.name || "Pattern"}${S.profile.format === "xm" ? ` · ${p.rows}` : ""}${p.used_in_orders.length ? "" : " (·)"}` })));
    select.value = String(S.pattern);
  }

  async function selectOrder(index) {
    S.order = index; S.pattern = S.overview.orders[index];
    clearSelection(); renderOrders(); $("#pattern-select").value = String(S.pattern);
    renderGridLoading(true);
    try { await loadPattern(); } catch (e) { renderGridError(e); }
    renderPlayer();
  }
  async function selectPattern(index) {
    S.pattern = index; S.order = S.overview.orders.indexOf(index);
    clearSelection(); renderOrders();
    renderGridLoading(true);
    try { await loadPattern(); } catch (e) { renderGridError(e); }
    renderPlayer();
  }

  // ---------------------------------------------------------------------------------------------
  // the grid
  function renderGridLoading(keep) {
    if (keep && S.els) { $("#grid-wrap").classList.add("loading"); return; }
    S.els = null; S.loadedPattern = null;
    $("#grid").replaceChildren(h("div", { class: "empty grid-state" }, h("span", { class: "spinner" }), t("grid.loading")));
  }
  function renderGridError(e) {
    S.els = null; S.loadedPattern = null; $("#grid-wrap").classList.remove("loading");
    $("#grid").replaceChildren(h("div", { class: "alert grid-state", role: "alert" }, h("strong", { text: t("grid.error") }), h("span", { text: errText(e) }),
      h("div", { class: "row-actions" }, h("button", { class: "btn", type: "button", onclick: () => selectPattern(S.pattern) }, t("retry")))));
  }

  function buildGrid() {
    const grid = $("#grid");
    $("#grid-wrap").classList.remove("loading");
    const xm = S.profile.format === "xm", channels = S.channels;
    grid.style.setProperty("--chs", String(channels));
    grid.dataset.format = S.profile.format;
    if (S.sel && (S.sel.row >= S.rows || S.sel.channel >= channels)) { S.sel = null; S.block = null; S.anchor = null; S.sheet = false; }
    const nodes = [h("div", { class: "gh corner", role: "columnheader", text: t("grid.row") })];
    for (let c = 0; c < channels; c++) {
      nodes.push(h("button", { class: `gh c${c + 1}${c && c % 4 === 0 ? " grp" : ""}`, type: "button", role: "columnheader", "data-head": c, onclick: () => toggleChannel(c) }));
    }
    S.els = []; S.rowHeads = [];
    for (let r = 0; r < S.rows; r++) {
      const shade = r % 16 === 0 ? " bar" : r % 4 === 0 ? " beat" : "";
      const head = h("div", { class: "rn" + shade, role: "rowheader", text: hex2(r) });
      S.rowHeads.push(head);
      const row = h("div", { class: "row", role: "row" }, head);
      const line = [];
      for (let c = 0; c < channels; c++) {
        const button = h("button", {
          class: `cell c${c + 1}${c && c % 4 === 0 ? " grp" : ""}${shade}`, type: "button", role: "gridcell", tabindex: r === 0 && c === 0 ? "0" : "-1",
          "data-row": r, "data-ch": c,
        }, h("span", { class: "n" }), h("span", { class: "s" }), xm ? h("span", { class: "v" }) : null, h("span", { class: "e" }));
        row.append(button); line.push(button);
      }
      S.els.push(line); nodes.push(row);
    }
    grid.replaceChildren(...nodes);
    updateChannelHeads();
  }

  function toggleChannel(c) {
    if (S.audible[c] && S.audible.filter(Boolean).length === 1) { toast(t("listen.nochan")); return; }
    S.audible[c] = !S.audible[c]; S.audibleTouched = true; renderPlayer();
  }

  function updateChannelHeads() {
    $$("[data-head]").forEach((el) => {
      const c = Number(el.dataset.head), on = S.audible[c];
      const label = t(on ? "track" : "track.muted", { n: c + 1 });
      if (el.textContent !== label) el.textContent = label;
      el.classList.toggle("off", !on);
      el.setAttribute("aria-pressed", String(on));
      el.title = label;
    });
    if (S.els) S.els.forEach((line) => line.forEach((el, c) => el.classList.toggle("muted-ch", !S.audible[c])));
  }

  function splitCell(text) {
    const p = Cells.parts(text, S.profile.format);
    return { ...p, emptyNote: p.note === "---", emptySample: p.sample === "--", emptyVolume: p.volume === "--", emptyEffect: p.effect === "..." };
  }
  function describeCell(text) {
    const p = splitCell(text);
    if (p.emptyNote && p.emptySample && p.emptyVolume && p.emptyEffect) return t("cell.empty");
    const sample = S.profile.sample_label === "instrument" ? "instrument " : "sample ";
    return [p.emptyNote ? "" : p.note, p.emptySample ? "" : sample + p.sample, p.emptyVolume ? "" : "vol " + p.volume, p.emptyEffect ? "" : "fx " + p.effect].filter(Boolean).join(", ");
  }

  function previewMap() {
    const proposal = S.proposals.find((p) => p.id === S.preview);
    const map = new Map();
    if (proposal) for (const cell of proposal.cells) if (cell.pattern === S.pattern) map.set(`${cell.row},${cell.channel}`, cell.after);
    return map;
  }

  function paintGrid() {
    if (!S.els || !S.cells) return;
    $("#grid-wrap").classList.remove("loading");
    const proposed = previewMap();
    const xm = S.profile.format === "xm";
    for (let r = 0; r < S.rows; r++) {
      for (let c = 0; c < S.channels; c++) {
        const text = S.cells[r][c], el = S.els[r][c];
        if (el._text !== text) {
          const p = splitCell(text), spans = el.children;
          const show = (span, value, empty, filler) => {
            const shown = empty ? filler : value;
            if (span.textContent !== shown) span.textContent = shown;
            span.classList.toggle("z", empty);
          };
          show(spans[0], p.note, p.emptyNote, "···"); show(spans[1], p.sample, p.emptySample, "··");
          if (xm) show(spans[2], p.volume, p.emptyVolume, "··");
          show(spans[xm ? 3 : 2], p.effect, p.emptyEffect, "···");
          el.setAttribute("aria-label", t("cell.aria", { row: hex2(r), ch: c + 1, text: describeCell(text) }));
          el._text = text;
        }
        const proposedText = proposed.get(`${r},${c}`);
        el.classList.toggle("prop", proposedText !== undefined);
        if (proposedText !== undefined) el.title = proposedText; else el.removeAttribute("title");
      }
    }
    Comments.paint();
    updateSelectionClasses();
    if (S.sel) refreshEditorFromGrid();
  }

  function flashChanged(before, after, kind) {
    for (let r = 0; r < after.length; r++) for (let c = 0; c < after[r].length; c++) {
      if (before[r] && before[r][c] !== after[r][c]) flash(S.els[r][c], kind);
    }
  }
  function flash(el, kind) {
    el.classList.remove("agent", "mine"); void el.offsetWidth; el.classList.add(kind);
    clearTimeout(S.flashTimers.get(el));
    S.flashTimers.set(el, setTimeout(() => el.classList.remove(kind), 4000));
  }

  // selection -------------------------------------------------------------------------------
  function clearSelection() { S.sel = null; S.block = null; S.anchor = null; S.sheet = false; S.conflict = null; S.editorError = ""; renderEditor(true); updateSelectionClasses(); renderPlayer(); }

  function updateSelectionClasses() {
    if (!S.els) return;
    for (let r = 0; r < S.rows; r++) for (let c = 0; c < S.channels; c++) {
      const el = S.els[r][c];
      const inside = S.block && r >= S.block.row && r < S.block.row + S.block.rows && c >= S.block.channel && c < S.block.channel + S.block.channels;
      el.classList.toggle("inblock", Boolean(inside));
      const selected = !S.blockMode && S.sel && S.sel.row === r && S.sel.channel === c;
      el.classList.toggle("sel", Boolean(selected));
      el.classList.toggle("rowcur", Boolean(S.sel && !S.blockMode && S.sel.row === r));
      el.setAttribute("aria-selected", String(Boolean(selected || inside)));
      el.tabIndex = S.sel ? (S.sel.row === r && S.sel.channel === c ? 0 : -1) : (r === 0 && c === 0 ? 0 : -1);
    }
    if (S.rowHeads) S.rowHeads.forEach((head, r) => head.classList.toggle("cur", Boolean(S.sel && S.sel.row === r)));
    $$("[data-head]").forEach((head) => head.classList.toggle("cur", Boolean(S.sel && !S.blockMode && S.sel.channel === Number(head.dataset.head))));
    $("#grid-hint").textContent = S.blockMode ? t(S.block && S.anchor === null ? "hint.block3" : S.anchor ? "hint.block2" : "hint.block1") : t("hint.tap");
    Comments.onSelection();
  }

  function pickCell(row, channel, opts = {}) {
    if (S.blockMode) {
      if (S.anchor === null) { S.anchor = { row, channel }; S.block = { row, rows: 1, channel, channels: 1 }; }
      else if (opts.extend === false) { S.anchor = { row, channel }; S.block = { row, rows: 1, channel, channels: 1 }; }
      else {
        const a = S.anchor;
        S.block = { row: Math.min(a.row, row), rows: Math.abs(a.row - row) + 1, channel: Math.min(a.channel, channel), channels: Math.abs(a.channel - channel) + 1 };
        S.anchor = null;
      }
      S.sel = { row, channel }; S.sheet = S.anchor === null; S.conflict = null; S.editorError = "";
    } else {
      S.sel = { row, channel }; S.block = null; S.conflict = null; S.editorError = "";
      if (opts.open !== false) S.sheet = true;
    }
    updateSelectionClasses(); renderEditor(true); renderPlayer();
  }

  function moveSelection(dr, dc) {
    const focused = document.activeElement && document.activeElement.classList.contains("cell") ? document.activeElement : null;
    const base = focused ? { row: Number(focused.dataset.row), channel: Number(focused.dataset.ch) } : S.sel || { row: 0, channel: 0 };
    const row = clamp(base.row + dr, 0, S.rows - 1), channel = clamp(base.channel + dc, 0, S.channels - 1);
    if (!S.blockMode) pickCell(row, channel, { open: false });
    S.els[row][channel].focus();
  }

  // grid events (delegated)
  function wireGrid() {
    const grid = $("#grid");
    grid.addEventListener("click", (event) => {
      const el = event.target.closest(".cell"); if (!el) return;
      pickCell(Number(el.dataset.row), Number(el.dataset.ch), { extend: S.blockMode && event.shiftKey ? true : undefined });
    });
    grid.addEventListener("keydown", (event) => {
      const el = event.target.closest(".cell"); if (!el) return;
      const row = Number(el.dataset.row), channel = Number(el.dataset.ch);
      const keys = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1] };
      if (keys[event.key]) { event.preventDefault(); moveSelection(...keys[event.key]); }
      else if (event.key === "PageDown") { event.preventDefault(); moveSelection(16, 0); }
      else if (event.key === "PageUp") { event.preventDefault(); moveSelection(-16, 0); }
      else if (event.key === "Home") { event.preventDefault(); moveSelection(-S.rows, 0); }
      else if (event.key === "End") { event.preventDefault(); moveSelection(S.rows, 0); }
      else if (event.key === "Enter" && !S.blockMode) { event.preventDefault(); pickCell(row, channel); const raw = $("#raw"); if (raw) raw.focus(); }
      else if ((event.key === "Delete" || event.key === "Backspace") && !S.blockMode) { event.preventDefault(); S.dirty = false; applyOps([setOp(row, channel, emptyText())], "Clear cell", [[row, channel]]); }
      else if (event.key === "Escape") { S.sheet = false; renderEditor(true); }
    });
  }

  // ---------------------------------------------------------------------------------------------
  // editing
  const NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
  const noteText = (index, octave) => Cells.noteText(NOTE_NAMES[index], octave);
  const octavesOf = () => [...new Set(S.profile.notes.map((name) => Number(name[2])))];
  const emptyText = () => Cells.format({ note: "---", sample: 0, volume: 0, cmd: null, param: "00" }, S.profile.format);

  function parseDraft(text) {
    const result = Cells.parse(text, S.profile);
    return result.error ? { error: result.error } : { draft: result.cell };
  }
  function draftText(d) { return Cells.format(d, S.profile.format); }
  // The message for a codec error key, with the note range and an example of this format's spelling.
  function cellError(key) {
    const notes = S.profile.notes;
    if (key === "ed.err.format" && S.profile.format === "xm") key = "ed.err.format.xm";
    return t(key, { range: `${notes[0]}..${notes[notes.length - 1]}` });
  }
  const setOp = (row, channel, cell) => ({ op: "set", pattern: S.pattern, row, channel, cell });

  function currentText() { return S.sel && S.cells ? S.cells[S.sel.row][S.sel.channel] : null; }

  function refreshEditorFromGrid() {
    if (S.blockMode || !S.sel) return;
    const text = currentText();
    if (text === S.baseText) return;
    if (!S.dirty) { S.baseText = text; S.draft = parseDraft(text).draft; syncPickers(); }
    else { changedNotice(text); }
  }

  // On a phone the editor is a bottom sheet and the orders/toolbar fold away (class "editing"), so the
  // grid is tall enough; the selected row is scrolled just under the sticky column heads.
  function revealSelection() {
    if (!S.sel || !S.els || !window.matchMedia("(max-width: 1000px)").matches) return;
    const wrap = $("#grid-wrap"), el = S.els[S.sel.row][S.sel.channel];
    wrap.scrollTop = Math.max(0, el.offsetTop - 40);
  }

  function renderEditor(reset) {
    const card = $("#editor"), body = $("#editor-body");
    const has = Boolean(S.cells) && (Boolean(S.sel) || S.blockMode);
    card.classList.toggle("empty-state", !has);
    card.classList.toggle("open", Boolean(has && S.sheet));
    const editing = Boolean(has && S.sheet);
    const main = $("#studio");
    if (main.classList.contains("editing") !== editing) {
      main.classList.toggle("editing", editing);
      if (editing) requestAnimationFrame(revealSelection);
    }
    if (!has) {
      body.replaceChildren(h("div", { class: "empty editor-empty" }, h("strong", { text: t("ed.none") }), h("span", { text: t("ed.none.hint") })));
      return;
    }
    if (S.blockMode) return renderBlockEditor(body);
    if (reset || !S.draft) {
      S.baseText = currentText(); S.draft = parseDraft(S.baseText).draft; S.dirty = false;
      const octaves = octavesOf();
      if (S.draft.note !== "---" && S.draft.note !== Cells.KEY_OFF) S.octave = Number(S.draft.note[2]);
      else if (!octaves.includes(S.octave)) S.octave = octaves[Math.min(octaves.length - 1, S.profile.format === "xm" ? 4 : 1)];
    }
    const { row, channel } = S.sel;
    const nav = (label, icon, dr, dc) => h("button", { class: "btn small", type: "button", "aria-label": label, title: label, onclick: () => moveSelection(dr, dc) }, h("span", { "aria-hidden": "true", text: icon }));
    const xm = S.profile.format === "xm";
    const octaves = h("div", { class: "seg octaves", role: "group", "aria-label": t("ed.note") }, octavesOf().map((n) => h("button", {
      class: "btn small", type: "button", "data-octave": n, "aria-pressed": String(n === S.octave), "aria-label": t("ed.octave", { n }),
      onclick: () => { S.octave = n; syncPickers(); },
    }, t("ed.oct", { n }))));
    const piano = h("div", { class: "piano", role: "group", "aria-label": t("ed.note") }, NOTE_NAMES.map((name, index) => h("button", {
      class: "btn" + (name.length > 1 ? " sharp" : ""), type: "button", "data-note": index,
      onclick: () => { S.draft.note = noteText(index, S.octave); touch(); },
    }, name)));
    const names = new Map((S.overview.samples || []).map((sample) => [sample.slot, sample.name]));
    const sampleSelect = h("select", { class: "select", id: "sample", onchange: (e) => { S.draft.sample = Number(e.target.value); touch(); } },
      h("option", { value: 0, text: "-- " + t(xm ? "ed.noinstrument" : "ed.nosample") }),
      Array.from({ length: S.profile.sample_slots }, (_, i) => h("option", { value: i + 1, text: `${hex2(i + 1)} · ${names.get(i + 1) || "—"}` })));
    const volKind = xm ? h("select", { class: "select", id: "vol-kind", "aria-label": t("ed.volume"), onchange: (e) => {
      const value = Number($("#vol-value").value) || 0;
      S.draft.volume = e.target.value ? (Cells.volumeJoin(e.target.value, Math.min(value, volumeMax(e.target.value))) || 0) : 0; touch();
    } }, h("option", { value: "", text: t("ed.vol.none") }), Cells.VOLUME_KINDS.map((kind) => h("option", { value: kind.id, text: t("vol." + kind.id) }))) : null;
    const volValue = xm ? h("input", { class: "input mono", id: "vol-value", maxlength: "2", autocomplete: "off", inputmode: "numeric", "aria-label": t("ed.param"),
      oninput: (e) => {
        const kind = $("#vol-kind").value; if (!kind) return;
        const value = Math.min(Number(e.target.value.replace(/\D/g, "")) || 0, volumeMax(kind)); e.target.value = String(value);
        S.draft.volume = Cells.volumeJoin(kind, value) || 0; S.dirty = true; syncPickers(false, true);
      } }) : null;
    const fxSelect = h("select", { class: "select", id: "fx", onchange: (e) => {
      const v = e.target.value; S.draft.cmd = v === "" ? null : Number(v); if (S.draft.cmd === null) S.draft.param = "00"; touch();
    } }, h("option", { value: "", text: "... " + t("ed.noeffect") }),
      S.profile.effects.map((letter) => h("option", { value: Cells.EFFECT_DIGITS.indexOf(letter), text: `${letter} · ${FX[S.lang][letter] || ""}` })));
    const param = h("input", { class: "input mono", id: "param", maxlength: "2", autocomplete: "off", spellcheck: "false", "aria-label": t("ed.param"), inputmode: "text",
      oninput: (e) => { const v = e.target.value.replace(/[^0-9a-fA-F]/g, "").toUpperCase().slice(0, 2); e.target.value = v; S.draft.param = v.padStart(2, "0"); if (S.draft.cmd === null && v) S.draft.cmd = 0; S.dirty = true; syncPickers(false, true); } });
    const raw = h("input", { class: "input mono", id: "raw", autocomplete: "off", spellcheck: "false", autocapitalize: "characters", "aria-describedby": "ed-error",
      oninput: (e) => {
        const parsed = parseDraft(e.target.value);
        if (parsed.error) { e.target.setAttribute("aria-invalid", "true"); $("#ed-error").textContent = cellError(parsed.error); S.dirty = true; return; }
        e.target.removeAttribute("aria-invalid"); $("#ed-error").textContent = ""; S.draft = parsed.draft; S.dirty = true; syncPickers(true);
      },
      onkeydown: (e) => { if (e.key === "Enter") { e.preventDefault(); submitCell(); } } });

    const conflict = S.conflict ? conflictView() : null;
    fill(body,
      h("div", { class: "editor-title" },
        h("span", { class: "where", text: t("ed.where", { row: hex2(row), ch: channel + 1 }) }),
        h("span", { class: "nav-arrows" }, nav(t("ed.prev"), "▲", -1, 0), nav(t("ed.next"), "▼", 1, 0), nav(t("ed.left"), "◀", 0, -1), nav(t("ed.right"), "▶", 0, 1))),
      conflict,
      h("div", { class: "field", id: "changed-note", hidden: true }),
      h("div", { class: "field" }, h("label", { for: "raw", text: t("ed.raw") }),
        h("div", { class: "raw-row" }, raw, h("button", { class: "btn primary", type: "button", id: "apply", onclick: submitCell }, t("ed.apply"))),
        h("div", { class: "inline-error", id: "ed-error", role: "alert", text: S.editorError })),
      h("div", { class: "field" }, h("span", { class: "label", text: t("ed.note") }), octaves, piano,
        h("div", { class: "note-extra" },
          h("button", { class: "btn small", type: "button", "data-keyoff": xm ? "1" : null, onclick: () => { S.draft.note = "---"; touch(); } }, t("ed.nonote")),
          xm ? h("button", { class: "btn small", type: "button", id: "keyoff", "aria-pressed": "false", onclick: () => { S.draft.note = Cells.KEY_OFF; touch(); } }, t("ed.keyoff")) : null)),
      h("div", { class: "two-col" },
        h("div", { class: "field" }, h("label", { for: "sample", text: t(xm ? "ed.instrument" : "ed.sample") }), sampleSelect),
        h("div", { class: "field" }, h("label", { for: "fx", text: t("ed.effect") }), h("div", { class: "two" }, fxSelect, param))),
      xm ? h("div", { class: "field" }, h("label", { for: "vol-kind", text: t("ed.volume") }), h("div", { class: "two" }, volKind, volValue)) : null,
      h("div", { class: "editor-actions" },
        h("button", { class: "btn", type: "button", onclick: () => { S.dirty = false; applyOps([setOp(row, channel, emptyText())], "Clear cell", [[row, channel]]); } }, t("ed.clear")),
        S.status.window ? h("button", { class: "btn ghost", type: "button", onclick: showOnComputer }, t("ed.show")) : null));
    syncPickers();
    if (S.dirty) { const text = currentText(); if (text !== S.baseText) changedNotice(text); }
  }

  function changedNotice(text) {
    const note = $("#changed-note"); if (!note) return;
    note.hidden = false;
    note.replaceChildren(h("div", { class: "alert warn" }, h("span", { text: t("ed.changed", { text }) }),
      h("div", { class: "row-actions" }, h("button", { class: "btn small", type: "button", onclick: () => { S.baseText = text; S.draft = parseDraft(text).draft; S.dirty = false; renderEditor(false); } }, t("ed.reload")))));
  }

  const volumeMax = (kind) => (Cells.VOLUME_KINDS.find((item) => item.id === kind) || { max: 15 }).max;

  function touch() { S.dirty = true; syncPickers(); }

  function syncPickers(skipRaw, keepParam) {
    const d = S.draft; if (!d || !$("#raw")) return;
    const raw = $("#raw");
    if (!skipRaw) { raw.value = draftText(d); raw.removeAttribute("aria-invalid"); $("#ed-error").textContent = ""; }
    $$("[data-octave]").forEach((el) => el.setAttribute("aria-pressed", String(Number(el.dataset.octave) === S.octave)));
    $$("[data-note]").forEach((el) => el.setAttribute("aria-pressed", String(d.note !== "---" && d.note !== Cells.KEY_OFF && d.note === noteText(Number(el.dataset.note), d.note[2]) && Number(d.note[2]) === S.octave)));
    const keyOff = $("#keyoff"); if (keyOff) keyOff.setAttribute("aria-pressed", String(d.note === Cells.KEY_OFF));
    $("#sample").value = String(d.sample);
    const volKind = $("#vol-kind");
    if (volKind) {
      const split = Cells.volumeSplit(d.volume);
      volKind.value = split ? split.kind : "";
      if (!keepParam) $("#vol-value").value = split ? String(split.value) : "";
      $("#vol-value").disabled = !split;
    }
    $("#fx").value = d.cmd === null ? "" : String(d.cmd);
    const param = $("#param");
    if (!keepParam) param.value = d.cmd === null ? "" : d.param;
    param.disabled = d.cmd === null;
  }

  async function submitCell() {
    const parsed = parseDraft($("#raw").value);
    if (parsed.error) { $("#ed-error").textContent = cellError(parsed.error); $("#raw").setAttribute("aria-invalid", "true"); $("#raw").focus(); return; }
    const finalText = draftText(parsed.draft);
    if (finalText === S.baseText) { toast(t("ed.same")); return; }
    const previous = S.baseText;
    S.dirty = false; S.baseText = finalText; S.draft = parsed.draft;   // the grid refresh inside applyOps must not call this "changed"
    const ok = await applyOps([setOp(S.sel.row, S.sel.channel, finalText)], `Set ${hex2(S.sel.row)}/${S.sel.channel + 1}`, [[S.sel.row, S.sel.channel]]);
    if (ok) { S.baseText = currentText(); S.draft = parseDraft(S.baseText).draft; syncPickers(); }
    else { S.dirty = true; S.baseText = previous; }
  }

  async function applyOps(ops, label, flashCells, baseOverride) {
    if (S.busy) return false;
    S.busy = true; setNet("sync");
    $$("#editor button").forEach((b) => { b.disabled = true; });
    try {
      const result = await api("patch", { ops, base_revision: baseOverride ?? S.revision, label });
      S.conflict = null; S.editorError = "";
      if (!result.changed) { toast(t("ed.same")); return true; }
      const { data } = await loadPattern();
      S.revision = Math.max(S.revision, data.revision, result.revision);
      (flashCells || result.diff.cells.map((c) => [c.row, c.channel])).forEach(([r, c]) => flash(S.els[r][c], "mine"));
      S.activity = [{ revision: result.revision, author: "human-web", label, summary: result.summary.slice(0, 3), at: new Date().toISOString(), own: true, patterns: [S.pattern], structure: false }, ...S.activity].slice(0, 30);
      renderActivity(); await refreshStatus(); await loadProposals();
      return true;
    } catch (e) {
      if (e.code === "LIVE_CONFLICT") { S.conflict = { error: e, ops, label, flashCells }; }
      else if (e.code === "LIVE_WEB_AUTH") { connectionLost(); return false; }
      else { S.editorError = errText(e); }
      renderEditor(false);
      return false;
    } finally {
      S.busy = false; setNet("live");
      $$("#editor button").forEach((b) => { b.disabled = false; });
      if (S.blockMode) renderEditor(false); else syncPickers();
    }
  }

  function conflictView() {
    const { error, ops, label, flashCells } = S.conflict;
    const items = (error.data.conflicts || []).slice(0, 5).map((c) => c.unit === "cell"
      ? h("li", { text: t("conflict.row", { row: hex2(c.row), ch: c.channel + 1, current: c.current, who: who(c.author), yours: c.yours }) })
      : h("li", { text: t("conflict.other", { unit: c.unit, who: who(c.author || "?") }) }));
    const keep = h("button", { class: "btn", type: "button", onclick: async () => { S.conflict = null; S.dirty = false; await loadPattern(); renderEditor(true); } }, t("conflict.keep"));
    const over = h("button", { class: "btn", type: "button" }, t("conflict.overwrite"));
    confirmInline(over, t("confirm.overwrite"), () => applyOps(ops, label, flashCells, error.data.revision));
    return h("div", { class: "alert", role: "alert" }, h("strong", { text: t("conflict.title") }), h("ul", { class: "diff" }, items), h("div", { class: "row-actions" }, keep, over));
  }

  async function showOnComputer() {
    if (!S.sel) return;
    const b = S.block || { row: S.sel.row, rows: 1, channel: S.sel.channel, channels: 1 };
    try { await api("select", { pattern: S.pattern, row: b.row, rows: b.rows, channel: b.channel, channels: b.channels }); } catch (e) { toast(errText(e), true); }
  }

  // block tools -----------------------------------------------------------------------------
  function renderBlockEditor(body) {
    const b = S.block;
    if (!b) {
      body.replaceChildren(h("div", { class: "empty editor-empty" }, h("strong", { text: t("blk.title") }), h("span", { text: t("blk.hint") })));
      return;
    }
    const base = { pattern: S.pattern, row: b.row, rows: b.rows, channel: b.channel, channels: b.channels };
    const move = (dr, dc) => () => {
      const to_row = b.row + dr, to_channel = b.channel + dc;
      if (to_row < 0 || to_row + b.rows > S.rows || to_channel < 0 || to_channel + b.channels > S.channels) { S.editorError = t("blk.bounds"); renderEditor(false); return; }
      S.editorError = "";
      applyOps([{ op: "move", ...base, to_row, to_channel }], "Move block", null).then((ok) => {
        if (ok) { S.block = { ...b, row: to_row, channel: to_channel }; S.sel = { row: to_row, channel: to_channel }; updateSelectionClasses(); renderEditor(false); }
      });
    };
    const copyTarget = h("select", { class: "select", id: "copy-target", "aria-label": t("blk.copyto") },
      S.overview.patterns.map((p) => h("option", { value: p.index, text: `${hex2(p.index)} · ${p.name || "Pattern"}` })));
    copyTarget.value = String(S.pattern);
    const tools = (semis) => h("button", { class: "btn", type: "button", onclick: () => applyOps([{ op: "transpose", ...base, semitones: semis }], `Transpose ${semis}`, null) }, (semis > 0 ? "+" : "") + semis);
    fill(body,
      h("div", { class: "editor-title" },
        h("span", { class: "where", text: t("blk.size", { row: hex2(b.row), end: hex2(b.row + b.rows - 1), c1: b.channel + 1, c2: b.channels > 1 ? "–" + (b.channel + b.channels) : "", n: b.rows * b.channels }) })),
      S.conflict ? conflictView() : null,
      h("div", { class: "field" }, h("span", { class: "label", text: t("blk.move") }),
        h("div", { class: "dpad" },
          h("button", { class: "btn up", type: "button", "aria-label": t("blk.up"), title: t("blk.up"), onclick: move(-1, 0) }, "▲"),
          h("button", { class: "btn left", type: "button", "aria-label": t("blk.left"), title: t("blk.left"), onclick: move(0, -1) }, "◀"),
          h("button", { class: "btn down", type: "button", "aria-label": t("blk.down"), title: t("blk.down"), onclick: move(1, 0) }, "▼"),
          h("button", { class: "btn right", type: "button", "aria-label": t("blk.right"), title: t("blk.right"), onclick: move(0, 1) }, "▶"))),
      h("div", { class: "field" }, h("span", { class: "label", text: t("blk.transpose") }),
        h("div", { class: "block-grid" }, tools(-12), tools(12), tools(-1), tools(1))),
      h("div", { class: "field" }, h("label", { for: "copy-target", text: t("blk.copyto") }),
        h("div", { class: "two" }, copyTarget, h("button", { class: "btn", type: "button", onclick: () => applyOps([{ op: "copy", ...base, to_pattern: Number($("#copy-target").value) }], "Copy block", null) }, t("blk.copy")))),
      h("div", { class: "editor-actions" },
        h("button", { class: "btn", type: "button", onclick: () => {
          if (b.row + b.rows * 2 > S.rows) { S.editorError = t("blk.bounds"); renderEditor(false); return; }
          applyOps([{ op: "copy", ...base, to_row: b.row + b.rows }], "Duplicate block", null);
        } }, t("blk.dup")),
        h("button", { class: "btn danger", type: "button", onclick: () => applyOps([{ op: "clear", ...base }], "Clear block", null) }, t("blk.clear")),
        h("button", { class: "btn ghost", type: "button", onclick: () => toggleBlockMode(false) }, t("blk.done"))),
      h("div", { class: "inline-error", role: "alert", text: S.editorError }));
  }

  function toggleBlockMode(on) {
    $("#studio").classList.toggle("blockmode", on);
    S.blockMode = on; S.anchor = null; S.block = null; S.conflict = null; S.editorError = ""; S.draft = null;
    const button = $("#block-mode");
    button.setAttribute("aria-pressed", String(on));
    $("span:last-child", button).textContent = t(on ? "block.done" : "block");
    if (!on) S.sheet = false;
    updateSelectionClasses();
    S.sel = on ? null : S.sel;
    renderEditor(true);
  }

  // ---------------------------------------------------------------------------------------------
  // proposals, activity, takes
  function emptyState(titleKey, hintKey) {
    return h("li", { class: "empty" }, h("strong", { text: t(titleKey) }), h("span", { text: t(hintKey) }));
  }

  function renderProposals() {
    const list = $("#proposals");
    const count = $("#proposals-count"); count.textContent = String(S.proposals.length); count.classList.toggle("hot", S.proposals.length > 0);
    const tab = $("#tab-count"); tab.textContent = String(S.proposals.length); tab.hidden = S.proposals.length === 0;
    if (!S.proposals.length) { list.replaceChildren(emptyState("props.empty", "props.empty.hint")); return; }
    list.replaceChildren(...S.proposals.map((p) => {
      const open = S.preview === p.id;
      const previewBtn = h("button", { class: "btn small", type: "button", "aria-expanded": String(open), onclick: () => { S.preview = open ? null : p.id; renderProposals(); paintGrid(); } }, open ? t("props.hide") : t("props.preview"));
      const accept = h("button", { class: "btn small primary", type: "button" }, p.stale ? t("props.anyway") : t("props.accept"));
      const act = async (fn, done) => {
        try { await fn(); toast(done); S.preview = S.preview === p.id ? null : S.preview; await onProposalSettled(); } catch (e) {
          if (e.code === "LIVE_CONFLICT") { toast(errText(e) + " " + (e.data.conflicts || []).length, true); await loadProposals(); } else toast(errText(e), true);
        }
      };
      if (p.stale) confirmInline(accept, t("confirm.overwrite"), () => act(() => api("accept", { id: p.id, force: true }), t("toast.accepted")));
      else accept.addEventListener("click", () => act(() => api("accept", { id: p.id }), t("toast.accepted")));
      const reject = h("button", { class: "btn small", type: "button", onclick: () => act(() => api("reject", { id: p.id }), t("toast.rejected")) }, t("props.reject"));
      const listen = h("button", { class: "btn small", type: "button", onclick: () => listenFrom({ proposal: p.id, order: Math.max(S.order, 0), row: 0 }) }, "▶ " + t("props.listen"));
      const diff = open ? h("ul", { class: "diff" }, p.cells.slice(0, 40).map((c) => h("li", {}, `P${hex2(c.pattern)} ${hex2(c.row)}/${c.channel + 1} `, h("span", { class: "before", text: c.before }), " → ", h("span", { class: "after", text: c.after }))),
        p.cells_total > 40 ? h("li", { class: "muted", text: t("props.more", { n: p.cells_total - 40 }) }) : null,
        p.other.length ? h("li", { class: "muted", text: t("props.other", { what: p.other.join(", ") }) }) : null) : null;
      return h("li", { class: "item" + (p.stale ? " stale" : ""), "data-id": p.id },
        h("h3", { text: p.label }),
        h("div", { class: "sub" }, h("span", { class: "badge agent", text: p.author }), h("span", { text: t("props.cells", { n: p.cells_total }) }), p.stale ? h("span", { class: "badge warn", text: t("props.stale") }) : null),
        diff, h("div", { class: "actions" }, previewBtn, listen, accept, reject));
    }));
  }

  async function onProposalSettled() {
    const status = await api("changes", { since: S.revision });
    if (status.revision !== S.revision) await onRevision(status); else await loadProposals();
    await refreshStatus();
  }

  function renderActivity() {
    const list = $("#activity");
    if (!S.activity.length) { list.replaceChildren(emptyState("act.empty", "act.empty.hint")); return; }
    list.replaceChildren(...S.activity.slice(0, 12).map((entry) => h("li", {},
      h("div", { class: "what" }, h("span", { class: "badge " + whoClass(entry.author), text: who(entry.author) }), h("strong", { text: entry.label }),
        h("span", { class: "muted mono", text: entry.at ? new Date(entry.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "" })),
      entry.summary && entry.summary.length ? h("div", { class: "mono", text: entry.summary[0] }) : null)));
  }

  function renderTakes() {
    const list = $("#takes");
    const count = $("#takes-count"); count.textContent = String(S.takes.length);
    if (!S.takes.length) { list.replaceChildren(emptyState("takes.empty", "takes.empty.hint")); return; }
    list.replaceChildren(...S.takes.slice().reverse().map((take) => h("li", { class: "item" },
      h("h3", { text: take.label }),
      h("div", { class: "sub" }, h("span", { class: "badge " + whoClass(take.author), text: t("takes.by", { who: who(take.author) }) }), h("span", { class: "mono", text: fmtTime(take.duration_seconds) }), h("span", { text: take.title })),
      h("div", { class: "actions" }, h("button", { class: "btn small", type: "button", onclick: () => listenFrom({ take: take.id, order: 0, row: 0 }) }, "▶ " + t("takes.listen"))))));
  }

  // ---------------------------------------------------------------------------------------------
  // listening
  function renderPlayer() {
    const s = S.status; if (!s) return;
    const row = S.block ? S.block.row : S.sel ? S.sel.row : 0;
    $("#listen-row-text").textContent = S.block && S.block.rows > 1 ? t("listen.block", { row: hex2(row), end: hex2(S.block.row + S.block.rows - 1) }) : t("listen.row", { row: hex2(row) });
    $("#speakers").hidden = !s.window;
    if (!s.window) S.speaker = "browser";
    $$("[data-speaker]").forEach((el) => el.setAttribute("aria-pressed", String(el.dataset.speaker === S.speaker)));
    const unavailable = S.speaker === "browser" && !s.render.engine;
    const noOrder = S.order < 0 && S.speaker === "browser";
    $("#listen-row").disabled = unavailable || S.order < 0;
    $("#listen-order").disabled = unavailable || S.order < 0;
    const select = $("#listen-seconds");
    if (!select.options.length || select.dataset.max !== String(s.render.max_seconds)) {
      select.dataset.max = String(s.render.max_seconds);
      select.replaceChildren(...[10, 20, 30, 60].filter((n) => n <= s.render.max_seconds).map((n) => h("option", { value: n, text: t("listen.sec", { n }) })));
      select.value = String(S.seconds);
    }
    select.disabled = S.speaker !== "browser";
    const chans = $("#chans");
    if (chans.dataset.count !== String(S.channels)) {      // up to 8 tracks get a button each; wider songs use the grid's track headers
      chans.dataset.count = String(S.channels);
      chans.replaceChildren();
      if (S.channels <= 8) {
        for (let c = 0; c < S.channels; c++) chans.append(h("button", { class: `btn small c${c + 1}`, type: "button", "data-chan": c,
          onclick: () => toggleChannel(c), "aria-label": t("track", { n: c + 1 }) }, String(c + 1)));
      } else {
        chans.append(h("button", { class: "btn small", type: "button", id: "chans-all", title: t("player.tracks"),
          onclick: () => { S.audible = new Array(S.channels).fill(true); S.audibleTouched = true; renderPlayer(); } }, t("player.alltracks")));
      }
    }
    $$("[data-chan]", chans).forEach((el) => el.setAttribute("aria-pressed", String(S.audible[Number(el.dataset.chan)])));
    const all = $("#chans-all"); if (all) all.disabled = S.audible.every(Boolean);
    if (!S.playerMessage) setPlayerStatus(unavailable ? t("player.unavailable") : noOrder ? t("player.noorder") : t("player.idle"), false);
    else if (unavailable) setPlayerStatus(t("player.unavailable"), false);
    updateChannelHeads();
  }

  function setPlayerStatus(text, busy) {
    const box = $("#player-status");
    const key = (busy ? "1" : "0") + text;
    if (box.dataset.key === key) return;
    box.dataset.key = key;
    box.replaceChildren(...(busy ? [h("span", { class: "spinner" })] : []), h("span", { text }));
  }

  async function listenFrom({ order, row, proposal, take }) {
    if (S.speaker === "computer") {
      try { await api("play", { order }); S.playerMessage = true; setPlayerStatus(t("player.computer", { order: hex2(order) }), false); } catch (e) { toast(errText(e), true); }
      return;
    }
    const seq = ++S.renderSeq;
    S.playerMessage = true; setPlayerStatus(t("player.rendering"), true);
    $("#listen-row").disabled = true;
    try {
      const body = { order, row, seconds: Number($("#listen-seconds").value), audible: S.audible };
      if (proposal) body.proposal = proposal; if (take) body.take = take;
      const { blob, info } = await api("render", body, { blob: true });
      if (seq !== S.renderSeq) return;
      const audio = $("#audio");
      if (S.objectUrl) URL.revokeObjectURL(S.objectUrl);
      S.objectUrl = URL.createObjectURL(blob);
      audio.src = S.objectUrl; audio.hidden = false;
      setPlayerStatus(t("player.ready", { engine: info.engine, seconds: info.seconds, order: hex2(info.order), row: hex2(info.row) }), false);
      try { await audio.play(); } catch (e) { setPlayerStatus(t("player.autoplay"), false); }
    } catch (e) {
      if (seq === S.renderSeq) { setPlayerStatus(errText(e), false); toast(errText(e), true); }
    } finally { renderPlayerButtons(); }
  }
  function renderPlayerButtons() { const unavailable = S.speaker === "browser" && !S.status.render.engine; $("#listen-row").disabled = unavailable || S.order < 0; }

  async function stopListening() {
    S.renderSeq += 1;
    if (S.speaker === "computer") { try { await api("stop"); } catch (e) { toast(errText(e), true); } }
    else $("#audio").pause();
    S.playerMessage = true; setPlayerStatus(t("player.stopped"), false); renderPlayerButtons();
  }

  // ---------------------------------------------------------------------------------------------
  // wiring
  let built = false;
  function buildStatic() {
    if (built) return; built = true;
    wireGrid();
    $("#pattern-select").addEventListener("change", (e) => selectPattern(Number(e.target.value)));
    $("#block-mode").addEventListener("click", () => toggleBlockMode(!S.blockMode));
    $("#editor-close").addEventListener("click", () => { S.sheet = false; renderEditor(false); const el = S.sel && S.els && S.els[S.sel.row][S.sel.channel]; if (el) el.focus(); });
    $("#listen-row").addEventListener("click", () => {
      const row = S.block ? S.block.row : S.sel ? S.sel.row : 0;
      listenFrom({ order: S.order, row });
    });
    $("#listen-order").addEventListener("click", () => listenFrom({ order: S.order, row: 0 }));
    $("#listen-stop").addEventListener("click", stopListening);
    $("#listen-seconds").addEventListener("change", (e) => { S.seconds = Number(e.target.value); });
    $$("[data-speaker]").forEach((el) => el.addEventListener("click", () => { S.speaker = el.dataset.speaker; renderPlayer(); }));
    $$("#tabs [data-tab]").forEach((el) => el.addEventListener("click", () => showTab(el.dataset.tab)));
    Comments.wire();
    document.addEventListener("keydown", (event) => { if (event.key === "Escape" && S.sheet) { S.sheet = false; renderEditor(false); } });
    $("#audio").addEventListener("ended", () => { S.playerMessage = false; });
  }

  function showTab(name) {
    S.tab = name; $("#main").dataset.tab = name;
    $$("#tabs [data-tab]").forEach((o) => o.setAttribute("aria-pressed", String(o.dataset.tab === name)));
    if (name !== "score" && S.sheet) { S.sheet = false; renderEditor(false); }   // the bottom sheet's padding would squeeze the Agent tab
  }

  function renderAll() {
    renderHeader(); renderPlayer(); renderProposals(); renderActivity(); renderTakes(); renderEditor(false); Comments.render();
    if (S.overview) { renderOrders(); renderPatternSelect(); }
    if (S.cells && S.els) { S.els.forEach((line, r) => line.forEach((el, c) => { el._text = null; })); paintGrid(); }
    updateSelectionClasses();
    $("#block-mode span:last-child").textContent = t(S.blockMode ? "block.done" : "block");
  }

  function boot() {
    applyTheme(); applyI18n();
    $$('[data-action="theme"]').forEach((el) => el.addEventListener("click", cycleTheme));
    $$('[data-action="lang"]').forEach((el) => el.addEventListener("click", toggleLang));
    $("#connect-retry").addEventListener("click", connect);
    $("#offline-retry").addEventListener("click", () => { if (S.running) schedule(0); });
    connect();
  }
  boot();
})();
