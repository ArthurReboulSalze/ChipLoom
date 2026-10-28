/* The cell spelling of the grid, in JavaScript: the page's counterpart of patch.cell_text / patch.parse_cell.
   MOD cells read `NOTE SS EEE` (C-2 01 C20); XM cells add the raw volume-column byte: `NOTE II VV EEE`
   (C-4 01 40 A0F), with notes C-0..B-7, key off `===` and effect letters 0-9 A-Z. The server stays the authority
   (it re-parses every patch); this codec only builds the text and gives quick, friendly feedback.
   Plain script, no dependencies; also loadable by Node for the test-suite. */
"use strict";
(function (root) {
  const hex2 = (n) => n.toString(16).toUpperCase().padStart(2, "0");
  const EFFECT_DIGITS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ";
  const EMPTY_NOTE = "---", EMPTY_SAMPLE = "--", EMPTY_VOLUME = "--", EMPTY_EFFECT = "...";
  const KEY_OFF = "===";

  /* XM volume column: the raw byte's high nibble picks the meaning, `base + n` is the byte. */
  const VOLUME_KINDS = [
    { id: "vol", base: 0x10, max: 64, step: "decimal" },   // 10-50: set volume 0..64
    { id: "vsd", base: 0x60, max: 15 },                    // 60-6F: volume slide down
    { id: "vsu", base: 0x70, max: 15 },                    // 70-7F: volume slide up
    { id: "vfd", base: 0x80, max: 15 },                    // 80-8F: fine volume slide down
    { id: "vfu", base: 0x90, max: 15 },                    // 90-9F: fine volume slide up
    { id: "vib", base: 0xA0, max: 15 },                    // A0-AF: vibrato speed
    { id: "vid", base: 0xB0, max: 15 },                    // B0-BF: vibrato depth
    { id: "pan", base: 0xC0, max: 15 },                    // C0-CF: set panning
    { id: "psl", base: 0xD0, max: 15 },                    // D0-DF: panning slide left
    { id: "psr", base: 0xE0, max: 15 },                    // E0-EF: panning slide right
    { id: "tpo", base: 0xF0, max: 15 },                    // F0-FF: tone portamento
  ];

  /** The volume-column byte as {kind, value} (`null` for none or an undefined byte). */
  function volumeSplit(byte) {
    if (!byte) return null;
    if (byte >= 0x10 && byte <= 0x50) return { kind: "vol", value: byte - 0x10 };
    if (byte >= 0x60) {
      const kind = VOLUME_KINDS.find((item) => item.base === (byte & 0xF0));
      return kind ? { kind: kind.id, value: byte & 15 } : null;
    }
    return null;
  }
  function volumeJoin(kind, value) {
    const found = VOLUME_KINDS.find((item) => item.id === kind);
    if (!found || !Number.isInteger(value) || value < 0 || value > found.max) return null;
    return found.base + value;
  }

  /** Tokens of one cell as the grid prints it. */
  function parts(text, fmt) {
    const tokens = text.split(" ");
    if (fmt === "xm") {
      return { note: tokens[0], sample: tokens[1], volume: tokens[2], effect: tokens[3] };
    }
    return { note: tokens[0], sample: tokens[1], volume: EMPTY_VOLUME, effect: tokens[2] };
  }

  /** The cells of one grid line `NN | cell | cell ...` (the row label is dropped). */
  function splitLine(line) {
    return line.split(" | ").slice(1);
  }

  /** {note, sample, volume (0..255), cmd (null or 0..35), param ("00".."FF")} -> grid text. */
  function format(cell, fmt) {
    const effect = cell.cmd === null || cell.cmd === undefined ? EMPTY_EFFECT : EFFECT_DIGITS[cell.cmd] + cell.param;
    const sample = cell.sample ? hex2(cell.sample) : EMPTY_SAMPLE;
    if (fmt === "xm") return `${cell.note || EMPTY_NOTE} ${sample} ${cell.volume ? hex2(cell.volume) : EMPTY_VOLUME} ${effect}`;
    return `${cell.note || EMPTY_NOTE} ${sample} ${effect}`;
  }

  /** Grid text -> cell. `profile` is the server's {format, notes, key_off, effects, volume_column, sample_slots}.
      Returns {cell} or {error: "<i18n key>"}; like the server, trailing tokens may be left out and a
      three-character token after the note is the effect, a two-character one the next column. */
  function parse(text, profile) {
    const xm = profile.format === "xm";
    const tokens = String(text).trim().split(/\s+/).filter(Boolean);
    if (!tokens.length) return { cell: { note: EMPTY_NOTE, sample: 0, volume: 0, cmd: null, param: "00" } };
    const note = tokens[0].toUpperCase();
    if (note !== EMPTY_NOTE && !profile.notes.includes(note) && !(xm && note === KEY_OFF)) return { error: "ed.err.note" };
    const slots = xm ? ["sample", "volume"] : ["sample"];
    const found = { sample: EMPTY_SAMPLE, volume: EMPTY_VOLUME, effect: EMPTY_EFFECT };
    let slot = 0, seenEffect = false;
    for (const token of tokens.slice(1)) {
      if (seenEffect) return { error: "ed.err.format" };
      if (token.length === 3) { found.effect = token; seenEffect = true; }
      else if (token.length === 2 && slot < slots.length) found[slots[slot++]] = token;
      else return { error: "ed.err.format" };
    }
    let sample = 0, volume = 0;
    if (!["--", ".."].includes(found.sample)) {
      if (!/^[0-9A-Fa-f]{2}$/.test(found.sample)) return { error: "ed.err.format" };
      sample = parseInt(found.sample, 16);
      if (sample > profile.sample_slots) return { error: "ed.err.sample" };
    }
    if (xm && !["--", ".."].includes(found.volume)) {
      if (!/^[0-9A-Fa-f]{2}$/.test(found.volume)) return { error: "ed.err.format" };
      volume = parseInt(found.volume, 16);
      if (volume < 0x10 || (volume > 0x50 && volume < 0x60)) return { error: "ed.err.volume" };
    }
    let cmd = null, param = "00";
    if (!["...", "000", ".."].includes(found.effect)) {
      const letter = found.effect[0].toUpperCase();
      if (!/^[0-9A-Za-z][0-9A-Fa-f]{2}$/.test(found.effect) || (!xm && !/[0-9A-Fa-f]/.test(letter))) return { error: "ed.err.format" };
      if (!profile.effects.includes(letter)) return { error: "ed.err.effect" };
      cmd = EFFECT_DIGITS.indexOf(letter);
      param = found.effect.slice(1).toUpperCase();
    }
    return { cell: { note, sample, volume, cmd, param } };
  }

  /** The tracker spelling of a note: letter, `-` or `#`, octave. */
  function noteText(pitch, octave) {
    return pitch[0] + (pitch.length > 1 ? "#" : "-") + octave;
  }

  const api = { hex2, EFFECT_DIGITS, VOLUME_KINDS, volumeSplit, volumeJoin, parts, splitLine, format, parse, noteText,
                EMPTY_NOTE, EMPTY_SAMPLE, EMPTY_VOLUME, EMPTY_EFFECT, KEY_OFF };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.ChipLoomCells = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
