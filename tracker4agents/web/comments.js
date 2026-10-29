/* ChipLoom Studio: comments with a place, the browser side. Plain script, no dependencies, loaded before app.js.

   What it does
   - "Comment" button in the cell editor's header: comments on the focused cell, or on the block chosen in
     "Select block" mode, through the studio API `comment` {text, place: {pattern, row, rows, channel, channels}}.
   - Marks the grid cells covered by an open comment (class `cmt`, a corner triangle; the text in the cell's
     tooltip) and lists the comments that cover the current selection in the editor card (that is how a tap
     on a tablet shows them).
   - The Agent tab's Comments card (#comments-card): open comments first, each with Go to / Reply / Resolve,
     a whole-song comment, and a toggle that also shows resolved ones (with Reopen). Uses `comments`, `reply`
     and `resolve`. The count of open comments is shown on the card and on the Agent tab (#tab-cmt).
   - Its EN/FR strings (keys "cmt.*") are merged into app.js's I18N table by create().
   Comment text is only ever written with textContent / text nodes (through app.js's `h`), never innerHTML.

   What it uses from app.js (passed to create(ctx); nothing else is reached):
     state     S (pattern, loadedPattern, rows, channels, els, sel, block, blockMode, anchor, sheet, overview, lang)
               and the I18N table
     helpers   h(tag, props, ...kids), fill(el, ...kids), $(selector), api(method, params), t(key, vars),
               toast(text, error), errText(e), who(author), whoClass(author), hex2(n)
     actions   selectPattern(index), toggleBlockMode(on), updateSelectionClasses(), renderEditor(reset),
               renderPlayer(), paintGrid(), showTab(name)
   What app.js calls (the returned object):
     wire()            once, when the studio is built
     load()            on entering the studio; reloads the list (and repaints the grid)
     onChanges(c)      from the `changes` polling: reloads when an entry has kind "comment" (or on a gap)
     onStatus(status)  from the periodic status refresh: reloads when `open_comments` disagrees
     paint()           at the end of paintGrid(): the cell markers
     onSelection()     at the end of updateSelectionClasses(): the Comment button and the editor's comment notes
     render()          on a language change
   Elements it expects in index.html: #cmt-open, #cmt-editor (in the editor card), #comments-card with
   #comments-count and #comments-body, and #tab-cmt on the Agent tab. */
"use strict";
(function (root) {
  const MAX_TEXT = 1000;          // the server's limit (COMMENT_INVALID past it)

  const STRINGS = {
    en: {
      "cmt.title": "Comments", "cmt.comment": "Comment", "cmt.comment.aria": "Comment on the selected cells",
      "cmt.song": "Comment on the whole song", "cmt.whole": "Whole song",
      "cmt.place": "Pattern {p}", "cmt.row": "row {r}", "cmt.rows": "rows {r}-{end}", "cmt.channel": "channel {c}", "cmt.channels": "channels {c}-{end}",
      "cmt.placeholder": "What should your agent look at here?", "cmt.reply.placeholder": "Your reply",
      "cmt.send": "Send", "cmt.cancel": "Cancel", "cmt.goto": "Go to", "cmt.reply": "Reply", "cmt.resolve": "Resolve", "cmt.reopen": "Reopen",
      "cmt.show.resolved": "Show resolved", "cmt.hide.resolved": "Hide resolved", "cmt.resolved.by": "Resolved by {who}",
      "cmt.empty": "No open comment", "cmt.empty.hint": "Select a cell or a block in the score and press Comment: your agent sees exactly where.",
      "cmt.none.place": "Select a cell or a block first.", "cmt.too.long": "A comment is limited to {n} characters.", "cmt.blank": "Write something first.",
      "cmt.sent": "Comment sent", "cmt.replied": "Reply sent", "cmt.resolved": "Comment resolved", "cmt.reopened": "Comment reopened",
      "cmt.here": "Comments here", "cmt.open.count": "{n} open comment(s)", "cmt.replies": "{n} replies", "cmt.replies.1": "1 reply",
      "err.COMMENT_UNKNOWN": "This comment no longer exists.",
    },
    fr: {
      "cmt.title": "Commentaires", "cmt.comment": "Commenter", "cmt.comment.aria": "Commenter les cellules choisies",
      "cmt.song": "Commenter tout le morceau", "cmt.whole": "Tout le morceau",
      "cmt.place": "Pattern {p}", "cmt.row": "ligne {r}", "cmt.rows": "lignes {r}-{end}", "cmt.channel": "canal {c}", "cmt.channels": "canaux {c}-{end}",
      "cmt.placeholder": "Que doit regarder ton agent ici ?", "cmt.reply.placeholder": "Ta réponse",
      "cmt.send": "Envoyer", "cmt.cancel": "Annuler", "cmt.goto": "Aller à", "cmt.reply": "Répondre", "cmt.resolve": "Résoudre", "cmt.reopen": "Rouvrir",
      "cmt.show.resolved": "Afficher les résolus", "cmt.hide.resolved": "Masquer les résolus", "cmt.resolved.by": "Résolu par {who}",
      "cmt.empty": "Aucun commentaire ouvert", "cmt.empty.hint": "Choisis une cellule ou un bloc dans la partition et appuie sur Commenter : ton agent voit exactement où.",
      "cmt.none.place": "Choisis d'abord une cellule ou un bloc.", "cmt.too.long": "Un commentaire est limité à {n} caractères.", "cmt.blank": "Écris d'abord quelque chose.",
      "cmt.sent": "Commentaire envoyé", "cmt.replied": "Réponse envoyée", "cmt.resolved": "Commentaire résolu", "cmt.reopened": "Commentaire rouvert",
      "cmt.here": "Commentaires ici", "cmt.open.count": "{n} commentaire(s) ouvert(s)", "cmt.replies": "{n} réponses", "cmt.replies.1": "1 réponse",
      "err.COMMENT_UNKNOWN": "Ce commentaire n'existe plus.",
    },
  };

  function create(ctx) {
    const { S, h, fill, $, api, t, toast, errText, who, whoClass, hex2 } = ctx;
    for (const lang of Object.keys(STRINGS)) Object.assign(ctx.I18N[lang] || (ctx.I18N[lang] = {}), STRINGS[lang]);

    const C = {
      list: [], open: 0, showResolved: false, seq: 0,
      compose: null,        // what the open text box writes: {kind: "place"} | {kind: "song"} | {kind: "reply", id}
      draft: "", busy: false, hereKey: null,
    };

    // --- places ------------------------------------------------------------------------------------
    /** The place the Comment button would use: the chosen block in block mode, else the focused cell. */
    function selectionPlace() {
      if (!S.els || S.loadedPattern !== S.pattern) return null;
      if (S.blockMode) {
        const b = S.block;
        return b && S.anchor === null ? { pattern: S.pattern, row: b.row, rows: b.rows, channel: b.channel, channels: b.channels } : null;
      }
      return S.sel ? { pattern: S.pattern, row: S.sel.row, rows: 1, channel: S.sel.channel, channels: 1 } : null;
    }
    /** "Pattern 01 · rows 00-1F · channels 4-5", rows in hexadecimal as the grid shows them, tracks from 1. */
    function placeText(p) {
      if (!p) return t("cmt.whole");
      const rows = p.rows > 1 ? t("cmt.rows", { r: hex2(p.row), end: hex2(p.row + p.rows - 1) }) : t("cmt.row", { r: hex2(p.row) });
      const chans = p.channels > 1 ? t("cmt.channels", { c: p.channel + 1, end: p.channel + p.channels }) : t("cmt.channel", { c: p.channel + 1 });
      return [t("cmt.place", { p: hex2(p.pattern) }), rows, chans].join(" · ");
    }
    const overlaps = (p, q) => p.pattern === q.pattern && p.row < q.row + q.rows && q.row < p.row + p.rows
      && p.channel < q.channel + q.channels && q.channel < p.channel + p.channels;
    const openOnes = () => C.list.filter((c) => c.status === "open");

    function when(at) {
      if (!at) return "";
      const date = new Date(at);
      if (Number.isNaN(date.getTime())) return "";
      const today = date.toDateString() === new Date().toDateString();
      return today ? date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
        : date.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
    }

    // --- loading -----------------------------------------------------------------------------------
    async function load() {
      const seq = ++C.seq;
      let data;
      try { data = await api("comments", { status: C.showResolved ? "all" : "open" }); } catch (e) {
        if (e.code === "LIVE_WEB_AUTH") throw e;
        return;                             // the polling reports the connection; try again on the next change
      }
      if (seq !== C.seq) return;            // a newer load is on its way
      C.list = data.comments || [];
      C.open = openOnes().length;
      if (C.compose && C.compose.kind === "reply" && !C.list.some((c) => c.id === C.compose.id)) closeComposer();
      render();
      ctx.paintGrid();                      // the markers (paintGrid ends with paint() and onSelection())
    }
    async function onChanges(changes) {
      if (changes.gap || changes.entries.some((entry) => entry.kind === "comment")) await load();
    }
    async function onStatus(status) {
      if (typeof status.open_comments === "number" && status.open_comments !== C.open) await load();
    }

    // --- the grid markers ----------------------------------------------------------------------------
    function paint() {
      if (!S.els) return;
      const covering = openOnes().filter((c) => c.place && c.place.pattern === S.pattern);
      for (let r = 0; r < S.els.length; r++) {
        const line = S.els[r];
        for (let ch = 0; ch < line.length; ch++) {
          const el = line[ch];
          const here = covering.filter((c) => r >= c.place.row && r < c.place.row + c.place.rows && ch >= c.place.channel && ch < c.place.channel + c.place.channels);
          el.classList.toggle("cmt", here.length > 0);
          if (here.length) {
            // paintGrid() has just set or removed the title (a proposal preview); the comments come after it.
            const lines = here.map((c) => `${who(c.author)}: ${c.text}`);
            el.title = [el.getAttribute("title"), ...lines].filter(Boolean).join("\n");
          }
        }
      }
    }

    // --- the editor card: Comment button, comments covering the selection, the text box ------------
    function onSelection() {
      const button = $("#cmt-open");
      if (!button) return;
      const place = selectionPlace();
      button.disabled = !place;
      const here = place ? openOnes().filter((c) => c.place && overlaps(c.place, place)) : [];
      const key = JSON.stringify([place, here.map((c) => [c.id, c.replies.length]), C.compose && C.compose.kind === "place", S.lang]);
      if (key === C.hereKey) return;
      C.hereKey = key;
      renderEditorPanel(place, here);
    }

    function renderEditorPanel(place, here) {
      const panel = $("#cmt-editor");
      const composing = C.compose && C.compose.kind === "place";
      const kids = [];
      if (here.length) {
        kids.push(h("div", { class: "cmt-here", role: "note", "aria-label": t("cmt.here") },
          here.slice(0, 4).map((c) => h("div", { class: "cmt-note" },
            h("span", { class: "badge " + whoClass(c.author), text: who(c.author) }), " ",
            h("span", { class: "cmt-text", text: c.text }),
            c.replies.length ? h("span", { class: "muted", text: " · " + t(c.replies.length === 1 ? "cmt.replies.1" : "cmt.replies", { n: c.replies.length }) }) : null))));
      }
      if (composing) kids.push(composer(place ? placeText(place) : t("cmt.none.place"), t("cmt.placeholder"), !place));
      panel.hidden = kids.length === 0;
      keepFocus(() => fill(panel, kids));
    }

    /** A small text box. The draft and the caret survive re-renders (the list re-renders on every change). */
    function composer(label, placeholder, disabled) {
      const area = h("textarea", { class: "input cmt-input", rows: "3", maxlength: String(MAX_TEXT), placeholder, "aria-label": placeholder, "data-cmt-input": "1",
        oninput: (e) => { C.draft = e.target.value; },
        onkeydown: (e) => {
          if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); send(); }
          else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); closeComposer(); }
        } });
      area.value = C.draft;
      return h("div", { class: "cmt-compose" },
        h("div", { class: "cmt-where mono", text: label }),
        area,
        h("div", { class: "actions" },
          h("button", { class: "btn small primary", type: "button", disabled: disabled || C.busy, onclick: send }, t("cmt.send")),
          h("button", { class: "btn small ghost", type: "button", onclick: closeComposer }, t("cmt.cancel"))));
    }
    function keepFocus(rebuild) {
      const active = document.activeElement;
      const had = active && active.dataset && active.dataset.cmtInput ? [active.selectionStart, active.selectionEnd] : null;
      rebuild();
      if (!had) return;
      const area = document.querySelector("[data-cmt-input]");
      if (area) { area.focus(); try { area.setSelectionRange(had[0], had[1]); } catch (e) { /* not focusable yet */ } }
    }

    function openComposer(spec) {
      const same = C.compose && C.compose.kind === spec.kind && C.compose.id === spec.id;
      if (!same) C.draft = "";
      C.compose = spec; C.hereKey = null;
      render(); onSelection();
      setTimeout(() => { const area = document.querySelector("[data-cmt-input]"); if (area) area.focus(); }, 0);
    }
    function closeComposer() {
      const wasPlace = C.compose && C.compose.kind === "place";
      C.compose = null; C.draft = ""; C.hereKey = null;
      render(); onSelection();
      if (wasPlace) { const button = $("#cmt-open"); if (button && !button.disabled) button.focus(); }
    }

    async function send() {
      const spec = C.compose;
      if (!spec || C.busy) return;
      const text = C.draft.trim();
      if (!text) { toast(t("cmt.blank"), true); return; }
      if (text.length > MAX_TEXT) { toast(t("cmt.too.long", { n: MAX_TEXT }), true); return; }
      let call, done;
      if (spec.kind === "reply") { call = ["reply", { id: spec.id, text }]; done = "cmt.replied"; }
      else if (spec.kind === "song") { call = ["comment", { text, place: null }]; done = "cmt.sent"; }
      else {
        const place = selectionPlace();
        if (!place) { toast(t("cmt.none.place"), true); return; }
        call = ["comment", { text, place }]; done = "cmt.sent";
      }
      C.busy = true;
      try {
        await api(...call);
        C.busy = false;
        closeComposer(); toast(t(done));
        await load();
      } catch (e) {
        C.busy = false; toast(errText(e), true);
        if (e.code === "COMMENT_UNKNOWN") { closeComposer(); await load(); }
      }
    }

    async function settle(comment, reopen) {
      try {
        await api("resolve", reopen ? { id: comment.id, reopen: true } : { id: comment.id });
        toast(t(reopen ? "cmt.reopened" : "cmt.resolved"));
      } catch (e) { toast(errText(e), true); }
      await load();
    }

    /** Show the comment's pattern and select its block, as "Select block" would. */
    async function goTo(comment) {
      const p = comment.place;
      if (!p) return;
      ctx.showTab("score");
      if (S.pattern !== p.pattern || S.loadedPattern !== p.pattern) await ctx.selectPattern(p.pattern);
      if (!S.els || S.loadedPattern !== p.pattern) return;
      if (!S.blockMode) ctx.toggleBlockMode(true);
      const row = Math.min(p.row, S.rows - 1), channel = Math.min(p.channel, S.channels - 1);
      const rows = Math.max(1, Math.min(p.rows, S.rows - row)), channels = Math.max(1, Math.min(p.channels, S.channels - channel));
      S.block = { row, rows, channel, channels }; S.anchor = null; S.sel = { row, channel }; S.sheet = true;
      ctx.updateSelectionClasses(); ctx.renderEditor(true); ctx.renderPlayer();
      const el = S.els[row][channel];
      if (el) { el.scrollIntoView({ block: "center", inline: "nearest" }); el.focus({ preventScroll: true }); }
    }

    // --- the Agent tab's card ------------------------------------------------------------------------
    function render() {
      const body = $("#comments-body");
      if (!body) return;
      const count = $("#comments-count");
      count.textContent = String(C.open); count.classList.toggle("hot", C.open > 0);
      const tab = $("#tab-cmt");
      tab.textContent = String(C.open); tab.hidden = C.open === 0; tab.title = t("cmt.open.count", { n: C.open });
      tab.setAttribute("aria-label", t("cmt.open.count", { n: C.open }));
      const shown = C.list.filter((c) => c.status === "open").reverse()
        .concat(C.showResolved ? C.list.filter((c) => c.status !== "open").reverse() : []);
      const songComposing = C.compose && C.compose.kind === "song";
      keepFocus(() => fill(body,
        h("div", { class: "cmt-tools" },
          h("button", { class: "btn small", type: "button", "aria-expanded": String(Boolean(songComposing)),
            onclick: () => (songComposing ? closeComposer() : openComposer({ kind: "song" })) }, t("cmt.song")),
          h("button", { class: "btn small ghost", type: "button", "aria-pressed": String(C.showResolved),
            onclick: () => { C.showResolved = !C.showResolved; render(); load(); } }, t(C.showResolved ? "cmt.hide.resolved" : "cmt.show.resolved"))),
        songComposing ? composer(t("cmt.whole"), t("cmt.placeholder"), false) : null,
        h("ul", { class: "list cmt-list" }, shown.length ? shown.map(item)
          : h("li", { class: "empty" }, h("strong", { text: t("cmt.empty") }), h("span", { text: t("cmt.empty.hint") })))));
    }

    function item(c) {
      const resolved = c.status !== "open";
      const replying = C.compose && C.compose.kind === "reply" && C.compose.id === c.id;
      return h("li", { class: "item cmt-item" + (resolved ? " resolved" : ""), "data-id": c.id },
        h("div", { class: "sub" },
          h("span", { class: "badge " + whoClass(c.author), text: who(c.author) }),
          h("span", { class: "mono", text: when(c.at) }),
          h("span", { class: "mono cmt-where", text: placeText(c.place) })),
        h("p", { class: "cmt-text", text: c.text }),
        c.replies.length ? h("ul", { class: "cmt-replies" }, c.replies.map((r) => h("li", {},
          h("span", { class: "badge " + whoClass(r.author), text: who(r.author) }), " ",
          h("span", { class: "cmt-text", text: r.text }), " ",
          h("span", { class: "muted mono", text: when(r.at) })))) : null,
        resolved ? h("div", { class: "sub", text: t("cmt.resolved.by", { who: who(c.resolved_by || "") }) + (c.resolved_at ? " · " + when(c.resolved_at) : "") }) : null,
        replying ? composer(t("cmt.reply"), t("cmt.reply.placeholder"), false) : null,
        h("div", { class: "actions" },
          c.place ? h("button", { class: "btn small", type: "button", onclick: () => goTo(c) }, t("cmt.goto")) : null,
          resolved ? null : h("button", { class: "btn small", type: "button", "aria-expanded": String(Boolean(replying)),
            onclick: () => (replying ? closeComposer() : openComposer({ kind: "reply", id: c.id })) }, t("cmt.reply")),
          h("button", { class: "btn small" + (resolved ? "" : " primary"), type: "button", onclick: () => settle(c, resolved) },
            t(resolved ? "cmt.reopen" : "cmt.resolve"))));
    }

    function wire() {
      const button = $("#cmt-open");
      if (button) button.addEventListener("click", () => {
        if (C.compose && C.compose.kind === "place") closeComposer(); else openComposer({ kind: "place" });
      });
      render(); onSelection();
    }

    return { wire, load, onChanges, onStatus, paint, onSelection, render: () => { C.hereKey = null; render(); onSelection(); } };
  }

  const exported = { create, STRINGS, MAX_TEXT };
  if (typeof module !== "undefined" && module.exports) module.exports = exported;
  else root.ChipLoomComments = exported;
})(typeof globalThis !== "undefined" ? globalThis : this);
