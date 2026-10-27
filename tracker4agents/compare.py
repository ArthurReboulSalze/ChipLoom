"""Blind A/B listening bundle between two versions of a composition.

The bundle is a self-contained directory: ``index.html`` (no external script, font or
stylesheet), neutral-named audio files (``x.wav``, ``y.wav``, optional MP3 copies, the exported
MODs) and ``comparison.json``, which is the answer key. Which version is X and which is Y is
randomized. The page embeds the mapping, the version labels and the per-version measurements
base64-encoded and only decodes them after the listener submits. That is a casual blind test, not
secrecy: anyone reading the page source or ``comparison.json`` can see the answer.
"""

from __future__ import annotations

import base64
import html
import json
import math
from pathlib import Path
import random
import re
import secrets
import tempfile
from datetime import datetime, timezone

from . import __version__, audio, mod, project
from .model import NOTES, Module, ValidationError, playback_plan
from .report import analyze

COMPARISON_SCHEMA = "chiploom.comparison.v1"
RESULT_SCHEMA = "chiploom.comparison-result.v1"
CRITERIA = ("melody", "groove", "palette", "arrangement")
LANGUAGES = ("en", "fr")
MAX_LABEL = 80

TEXTS = {
    "en": {
        "page_title": "Blind A/B listening",
        "intro": "Listen to X and Y in any order, as often as you like. Pick the one you prefer, "
                 "then submit to see which version each one was.",
        "bias_note": "Loudness differences can sway a blind test. The measured peak and RMS level of "
                     "both renders are shown after you submit.",
        "excerpt": "Both versions are rendered excerpts of at most {seconds} s.",
        "version_x": "Version X", "version_y": "Version Y",
        "switch": "Switch X/Y at the same position",
        "choice_legend": "Which do you prefer?",
        "choice_x": "X", "choice_y": "Y", "choice_none": "No preference",
        "ratings_legend": "Ratings (optional, 1 = weak, 5 = strong)",
        "criterion": "Criterion",
        "criterion_melody": "Melody", "criterion_groove": "Groove",
        "criterion_palette": "Sound palette", "criterion_arrangement": "Arrangement",
        "comment": "Comment (optional)",
        "submit": "Submit and reveal",
        "choose_first": "Choose X, Y or no preference first.",
        "result": "Result",
        "you_preferred": "You preferred",
        "no_preference_recorded": "You recorded no preference.",
        "x_was": "X was", "y_was": "Y was",
        "metrics_title": "Measurements (not judgments)",
        "metrics_note": "These values measure the score and the rendered audio. They do not say which "
                        "version is better. The key is an estimate: tracker note names are period "
                        "labels and sample tuning is unknown, so the sounding pitch can be offset.",
        "metric": "Measurement",
        "warnings_title": "Factual flags",
        "no_warnings": "none",
        "files_title": "Files",
        "file_mod": "MOD", "file_wav": "WAV", "file_mp3": "MP3",
        "download": "Download result JSON",
        "reset": "Start over",
        "none_value": "-",
        "metric_duration_seconds": "Duration (s)", "metric_rows_played": "Rows played",
        "metric_loop_start_seconds": "Loop start (s)", "metric_bpm_range": "BPM",
        "metric_note_starts": "Note starts", "metric_notes_per_second": "Note starts per second",
        "metric_lowest_note": "Lowest note", "metric_highest_note": "Highest note",
        "metric_estimated_key": "Estimated key (estimate)", "metric_key_margin": "Key margin",
        "metric_key_confidence": "Key confidence (heuristic)",
        "metric_samples_played": "Samples played", "metric_samples_never_played": "Samples never played",
        "metric_longest_no_note_seconds": "Longest stretch without a note start (s)",
        "metric_repeated_8_fraction": "Repeated 8-row blocks (fraction)",
        "metric_peak_dbfs": "Render peak (dBFS)", "metric_rms_dbfs": "Render RMS (dBFS)",
        "metric_warning_count": "Factual flags (count)",
        "metric_channel_notes": "Channel {n}: note starts",
        "metric_channel_density": "Channel {n}: rows with a note (fraction)",
    },
    "fr": {
        "page_title": "Écoute comparative à l’aveugle",
        "intro": "Écoute X et Y dans l’ordre que tu veux, autant de fois que tu veux. Choisis celle que "
                 "tu préfères, puis valide pour découvrir quelle version se cachait derrière chacune.",
        "bias_note": "Une différence de volume peut fausser un test à l’aveugle. Le pic et le niveau RMS "
                     "mesurés des deux rendus s’affichent après la validation.",
        "excerpt": "Les deux versions sont des extraits rendus de {seconds} s au maximum.",
        "version_x": "Version X", "version_y": "Version Y",
        "switch": "Basculer X/Y à la même position",
        "choice_legend": "Laquelle préfères-tu ?",
        "choice_x": "X", "choice_y": "Y", "choice_none": "Pas de préférence",
        "ratings_legend": "Notes (facultatives, 1 = faible, 5 = forte)",
        "criterion": "Critère",
        "criterion_melody": "Mélodie", "criterion_groove": "Groove",
        "criterion_palette": "Palette sonore", "criterion_arrangement": "Arrangement",
        "comment": "Commentaire (facultatif)",
        "submit": "Valider et révéler",
        "choose_first": "Choisis d’abord X, Y ou « pas de préférence ».",
        "result": "Résultat",
        "you_preferred": "Tu as préféré",
        "no_preference_recorded": "Tu n’as indiqué aucune préférence.",
        "x_was": "X était", "y_was": "Y était",
        "metrics_title": "Mesures (pas des jugements)",
        "metrics_note": "Ces valeurs mesurent la partition et l’audio rendu. Elles ne disent pas quelle "
                        "version est meilleure. La tonalité est une estimation : les noms de notes d’un "
                        "tracker sont des étiquettes de période et l’accord des samples est inconnu, donc "
                        "la hauteur réelle peut être décalée.",
        "metric": "Mesure",
        "warnings_title": "Signalements factuels",
        "no_warnings": "aucun",
        "files_title": "Fichiers",
        "file_mod": "MOD", "file_wav": "WAV", "file_mp3": "MP3",
        "download": "Télécharger le résultat JSON",
        "reset": "Recommencer",
        "none_value": "-",
        "metric_duration_seconds": "Durée (s)", "metric_rows_played": "Lignes jouées",
        "metric_loop_start_seconds": "Début de boucle (s)", "metric_bpm_range": "BPM",
        "metric_note_starts": "Départs de notes", "metric_notes_per_second": "Départs de notes par seconde",
        "metric_lowest_note": "Note la plus grave", "metric_highest_note": "Note la plus aiguë",
        "metric_estimated_key": "Tonalité estimée (estimation)", "metric_key_margin": "Marge de tonalité",
        "metric_key_confidence": "Confiance de tonalité (heuristique)",
        "metric_samples_played": "Samples joués", "metric_samples_never_played": "Samples jamais joués",
        "metric_longest_no_note_seconds": "Plus longue plage sans départ de note (s)",
        "metric_repeated_8_fraction": "Blocs de 8 lignes répétés (fraction)",
        "metric_peak_dbfs": "Pic du rendu (dBFS)", "metric_rms_dbfs": "RMS du rendu (dBFS)",
        "metric_warning_count": "Signalements factuels (nombre)",
        "metric_channel_notes": "Voie {n} : départs de notes",
        "metric_channel_density": "Voie {n} : lignes avec une note (fraction)",
    },
}

# Placeholders: __T:key__ (localized span), __LANG__, __CID__, __TEXTS__, __ANSWER__, __EXCERPT__, __CRITERIA__.
PAGE = r'''<!doctype html>
<html lang="__LANG__" data-cid="__CID__"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ChipLoom A/B</title><link rel="icon" href="data:,">
<style>
:root{color-scheme:dark;--bg:#0d131d;--panel:#151e2b;--line:#2a3547;--text:#e7edf5;--muted:#a3b0c2;--accent:#8fd8e8;--warn:#f6bc7a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.55 system-ui,sans-serif}
main{max-width:980px;margin:auto;padding:36px 16px 64px}h1{font-size:34px;line-height:1.15;margin:8px 0 12px}h2{font-size:20px;margin:0 0 14px}
.topline{font-size:12px;letter-spacing:.18em;text-transform:uppercase;color:var(--accent)}p{color:var(--muted);max-width:760px}
header{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}.lang button{background:none;border:1px solid var(--line);color:var(--muted);padding:5px 10px;border-radius:6px;cursor:pointer;font:inherit}
.lang button[aria-pressed=true]{color:var(--text);border-color:var(--accent)}
.players{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin:22px 0}.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px}
.card h2{margin-bottom:10px}audio{display:block;width:100%}.tools{margin:0 0 22px}
button.action{background:#1b2839;color:var(--text);border:1px solid #40536c;padding:9px 14px;border-radius:8px;font:inherit;cursor:pointer}
button.primary{background:var(--accent);color:#08202a;border-color:var(--accent);font-weight:600}button:disabled{opacity:.5;cursor:default}
form,.result{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:20px}fieldset{border:0;padding:0;margin:0 0 20px}legend{font-weight:600;margin-bottom:8px;padding:0}
.choices{display:flex;flex-wrap:wrap;gap:10px 22px}.choices label{cursor:pointer}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid #1b2636;vertical-align:top}th{color:var(--muted);font-weight:600}
select,textarea{background:#1b2839;color:var(--text);border:1px solid #40536c;border-radius:6px;padding:6px;font:inherit}textarea{width:100%;min-height:90px}
.error{color:var(--warn);margin:10px 0 0}.result{margin-top:22px}.result[hidden],.error[hidden]{display:none}
.metrics td:first-child{color:var(--muted)}.row-actions{display:flex;flex-wrap:wrap;gap:12px;margin-top:18px}a{color:var(--accent)}ul{margin:6px 0 14px;padding-left:20px}
@media(max-width:700px){.players{grid-template-columns:1fr}header{display:block}.lang{margin-top:12px}h1{font-size:28px}}
</style>
<main>
<header><div><div class="topline">ChipLoom</div><h1>__T:page_title__</h1><p>__T:intro__</p><p>__T:bias_note__</p>__EXCERPT__</div>
<div class="lang"><button type="button" data-lang="en">EN</button> <button type="button" data-lang="fr">FR</button></div></header>
<section class="players" aria-label="Players">
<div class="card"><h2>__T:version_x__</h2><audio id="player-x" controls preload="auto" src="x.wav"></audio></div>
<div class="card"><h2>__T:version_y__</h2><audio id="player-y" controls preload="auto" src="y.wav"></audio></div>
</section>
<div class="tools"><button type="button" class="action" id="switch">__T:switch__</button></div>
<form id="form">
<fieldset><legend>__T:choice_legend__</legend><div class="choices">
<label><input type="radio" name="choice" value="x"> __T:choice_x__</label>
<label><input type="radio" name="choice" value="y"> __T:choice_y__</label>
<label><input type="radio" name="choice" value="none"> __T:choice_none__</label></div></fieldset>
<fieldset><legend>__T:ratings_legend__</legend><table><thead><tr><th>__T:criterion__</th><th>__T:version_x__</th><th>__T:version_y__</th></tr></thead><tbody>__CRITERIA__</tbody></table></fieldset>
<fieldset><legend><label for="comment">__T:comment__</label></legend><textarea id="comment" maxlength="2000"></textarea></fieldset>
<button type="submit" class="action primary" id="submit">__T:submit__</button>
<p class="error" id="error" hidden role="alert">__T:choose_first__</p>
</form>
<section class="result" id="result" hidden aria-live="polite"></section>
</main>
<script id="texts" type="application/json">__TEXTS__</script>
<script id="answer" type="text/plain">__ANSWER__</script>
<script>
(function(){
'use strict';
var TEXTS=JSON.parse(document.getElementById('texts').textContent);
var CID=document.documentElement.dataset.cid;
var CRITERIA=['melody','groove','palette','arrangement'];
var BLOB=document.getElementById('answer').textContent.trim();
var lang=document.documentElement.lang==='fr'?'fr':'en';
var answer=null,result=null;
function $(s){return document.querySelector(s)}
function t(k){return (TEXTS[lang]&&TEXTS[lang][k])||TEXTS.en[k]||k}
function keyName(n){return 'chiploom-compare-'+CID+'-'+n}
function save(n,v){try{localStorage.setItem(keyName(n),JSON.stringify(v))}catch(e){}}
function load(n){try{var r=localStorage.getItem(keyName(n));return r?JSON.parse(r):null}catch(e){return null}}
function drop(n){try{localStorage.removeItem(keyName(n))}catch(e){}}
function decode(){var bin=atob(BLOB);var bytes=Uint8Array.from(bin,function(c){return c.charCodeAt(0)});return JSON.parse(new TextDecoder().decode(bytes))}
function el(tag,text,cls){var e=document.createElement(tag);if(text!==undefined&&text!==null)e.textContent=text;if(cls)e.className=cls;return e}
function num(v){return v===''?null:Number(v)}
function show(v){return v===null||v===undefined?t('none_value'):String(v)}

function applyLang(){
  document.documentElement.lang=lang;
  document.querySelectorAll('[data-i18n]').forEach(function(n){var s=t(n.dataset.i18n);if(n.dataset.seconds)s=s.replace('{seconds}',n.dataset.seconds);n.textContent=s});
  document.querySelectorAll('.lang button').forEach(function(b){b.setAttribute('aria-pressed',String(b.dataset.lang===lang))});
  if(result)renderResult();
}
function collect(){
  var checked=document.querySelector('input[name=choice]:checked');
  var ratings={};
  CRITERIA.forEach(function(c){ratings[c]={x:num($('#r-'+c+'-x').value),y:num($('#r-'+c+'-y').value)}});
  return {choice:checked?checked.value:null,ratings:ratings,comment:$('#comment').value.trim()};
}
function saveDraft(){save('draft',collect())}
function restoreDraft(){
  var d=load('draft');if(!d)return;
  if(d.choice){var r=document.querySelector('input[name=choice][value='+d.choice+']');if(r)r.checked=true}
  CRITERIA.forEach(function(c){if(d.ratings&&d.ratings[c]){$('#r-'+c+'-x').value=d.ratings[c].x===null?'':String(d.ratings[c].x);$('#r-'+c+'-y').value=d.ratings[c].y===null?'':String(d.ratings[c].y)}});
  if(typeof d.comment==='string')$('#comment').value=d.comment;
}
function finish(d){
  var m={x:answer.x.version,y:answer.y.version};
  var byVersion={};byVersion[m.x]={};byVersion[m.y]={};
  CRITERIA.forEach(function(c){byVersion[m.x][c]=d.ratings[c].x;byVersion[m.y][c]=d.ratings[c].y});
  result={schema:'__RESULT_SCHEMA__',comparison_id:CID,submitted_at:new Date().toISOString(),language:lang,
    choice:d.choice,preferred_version:d.choice==='none'?'none':m[d.choice],
    preferred_label:d.choice==='none'?null:answer[d.choice].label,
    ratings:d.ratings,ratings_by_version:byVersion,comment:d.comment,mapping:m,
    labels:{x:answer.x.label,y:answer.y.label}};
  save('result',result);
  renderResult();
}
function lockForm(){document.querySelectorAll('#form input,#form select,#form textarea,#form button').forEach(function(n){n.disabled=true})}
function renderResult(){
  var box=$('#result');box.replaceChildren();box.hidden=false;lockForm();
  box.appendChild(el('h2',t('result')));
  var verdict=result.choice==='none'?t('no_preference_recorded'):t('you_preferred')+' '+(result.choice==='x'?t('choice_x'):t('choice_y'))+' ('+result.preferred_label+')';
  box.appendChild(el('p',verdict));
  var ul=el('ul');
  ul.appendChild(el('li',t('x_was')+': '+answer.x.label));
  ul.appendChild(el('li',t('y_was')+': '+answer.y.label));
  box.appendChild(ul);
  box.appendChild(el('h2',t('metrics_title')));
  box.appendChild(el('p',t('metrics_note')));
  var table=el('table','','metrics'),head=el('tr');
  [t('metric'),t('choice_x')+' - '+answer.x.label,t('choice_y')+' - '+answer.y.label].forEach(function(x){head.appendChild(el('th',x))});
  var thead=el('thead');thead.appendChild(head);table.appendChild(thead);
  var tbody=el('tbody');
  answer.metrics.forEach(function(row){
    var tr=el('tr'),label=TEXTS[lang]['metric_'+row.key];
    if(!label&&row.channel){label=TEXTS[lang]['metric_'+row.key.replace(/^ch\d_/,'channel_')].replace('{n}',row.channel)}
    tr.appendChild(el('td',label||row.key));tr.appendChild(el('td',show(row.x)));tr.appendChild(el('td',show(row.y)));tbody.appendChild(tr);
  });
  table.appendChild(tbody);box.appendChild(table);
  box.appendChild(el('h2',t('warnings_title')));
  ['x','y'].forEach(function(side){
    box.appendChild(el('p',t('choice_'+side)+' - '+answer[side].label+':'));
    var list=el('ul');
    if(!answer[side].warnings.length)list.appendChild(el('li',t('no_warnings')));
    answer[side].warnings.forEach(function(w){list.appendChild(el('li',w))});
    box.appendChild(list);
  });
  box.appendChild(el('h2',t('files_title')));
  var files=el('ul');
  ['x','y'].forEach(function(side){
    var li=el('li',t('choice_'+side)+' ('+answer[side].label+'): ');
    [['mod','file_mod'],['wav','file_wav'],['mp3','file_mp3']].forEach(function(pair){
      var href=answer[side].files[pair[0]];if(!href)return;
      var a=el('a',t(pair[1]));a.href=href;a.download='';li.appendChild(a);li.appendChild(document.createTextNode(' '));
    });
    files.appendChild(li);
  });
  box.appendChild(files);
  var actions=el('div','','row-actions');
  var dl=el('button',t('download'),'action primary');dl.type='button';dl.addEventListener('click',download);
  var rs=el('button',t('reset'),'action');rs.type='button';rs.addEventListener('click',function(){drop('result');drop('draft');location.reload()});
  actions.appendChild(dl);actions.appendChild(rs);box.appendChild(actions);
}
function download(){
  var blob=new Blob([JSON.stringify(result,null,2)+'\n'],{type:'application/json'});
  var url=URL.createObjectURL(blob),a=document.createElement('a');
  a.href=url;a.download='chiploom-comparison-result-'+CID+'.json';document.body.appendChild(a);a.click();a.remove();
  setTimeout(function(){URL.revokeObjectURL(url)},1000);
}

var px=$('#player-x'),py=$('#player-y');
px.addEventListener('play',function(){py.pause()});
py.addEventListener('play',function(){px.pause()});
$('#switch').addEventListener('click',function(){
  var from=!px.paused?px:(!py.paused?py:null);if(!from)return;
  var to=from===px?py:px;
  try{to.currentTime=from.currentTime}catch(e){}
  from.pause();to.play().catch(function(){});
});
document.querySelectorAll('.lang button').forEach(function(b){b.addEventListener('click',function(){lang=b.dataset.lang;applyLang()})});
var form=$('#form');
form.addEventListener('input',saveDraft);form.addEventListener('change',saveDraft);
form.addEventListener('submit',function(e){
  e.preventDefault();var d=collect();
  if(!d.choice){$('#error').hidden=false;return}
  $('#error').hidden=true;answer=decode();finish(d);
});
restoreDraft();
var stored=load('result');
if(stored&&stored.schema==='__RESULT_SCHEMA__'){try{answer=decode();result=stored}catch(e){result=null}}
applyLang();
})();
</script></html>'''


def _loader(path: Path) -> Module:
    return project.load(path) if path.suffix.lower() == ".json" else mod.read(path)


def _default_label(path: Path) -> str:
    name = path.name
    for suffix in (".project.json", ".json", ".mod"):
        if name.lower().endswith(suffix):
            return name[:-len(suffix)] or name
    return name


def _check_label(value: object, index: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > MAX_LABEL:
        raise ValidationError(f"labels[{index}]: non-empty text of at most {MAX_LABEL} characters expected.")
    return value.strip()


def _lowest_highest(channels: list[dict]) -> tuple[str | None, str | None]:
    low = [entry["lowest_note"] for entry in channels if entry["lowest_note"]]
    high = [entry["highest_note"] for entry in channels if entry["highest_note"]]
    return (min(low, key=NOTES.index) if low else None, max(high, key=NOTES.index) if high else None)


def _metrics(report: dict, wav: dict) -> dict:
    """Flat, language-neutral measurements for the side-by-side table."""
    timing, overall = report["timing"], report["global"]
    key = overall["key_estimate"]
    lowest, highest = _lowest_highest(report["channels"])
    bpm = (str(timing["bpm_min"]) if timing["bpm_min"] == timing["bpm_max"]
           else f"{timing['bpm_min']}-{timing['bpm_max']}")
    duration = timing["duration_seconds"]
    metrics = {
        "duration_seconds": round(duration, 3), "rows_played": timing["rows_played"],
        "loop_start_seconds": round(timing["loop_start_seconds"], 3), "bpm_range": bpm,
        "note_starts": overall["note_starts"],
        "notes_per_second": round(overall["note_starts"] / duration, 3) if duration else None,
    }
    for entry in report["channels"]:
        metrics[f"ch{entry['channel']}_notes"] = entry["note_ons"]
        metrics[f"ch{entry['channel']}_density"] = round(entry["density"], 3)
    never = report["samples"]["never_played_slots"]
    eight = report["repetition"]["blocks"]["8"]["all_channels"]["repeated_fraction"]
    metrics.update(
        lowest_note=lowest, highest_note=highest,
        estimated_key=key["key"] if key["available"] else None,
        key_margin=key["margin"] if key["available"] else None,
        key_confidence=key["confidence"] if key["available"] else None,
        samples_played=report["samples"]["slots_with_audio"] - len(never), samples_never_played=len(never),
        longest_no_note_seconds=round(overall["rows_without_note_start"]["longest"]["seconds"], 3),
        repeated_8_fraction=round(eight, 3) if eight is not None else None,
        peak_dbfs=wav.get("peak_dbfs"), rms_dbfs=wav.get("rms_dbfs"),
        warning_count=len(report["warnings"]),
    )
    return metrics


def _kept_render(details: dict) -> dict:
    keep = ("engine", "version", "requested_seconds", "source_sha256", "audio")
    return {key: details[key] for key in keep if key in details}


def _text_spans(language: str) -> dict[str, str]:
    return {key: f'<span data-i18n="{key}">{html.escape(value)}</span>' for key, value in TEXTS[language].items()}


def build_page(language: str, comparison_id: str, answer_blob: str, seconds: float | None) -> str:
    spans = _text_spans(language)
    criteria_rows = []
    for name in CRITERIA:
        cells = "".join(
            f'<td><select id="r-{name}-{side}" aria-label="{html.escape(TEXTS[language]["criterion_" + name], quote=True)} {side.upper()}">'
            '<option value="">-</option>' + "".join(f'<option value="{n}">{n}</option>' for n in range(1, 6))
            + "</select></td>" for side in ("x", "y"))
        criteria_rows.append(f"<tr><td>{spans['criterion_' + name]}</td>{cells}</tr>")
    excerpt = ""
    if seconds is not None:
        label = f"{seconds:g}"
        excerpt = (f'<p><span data-i18n="excerpt" data-seconds="{label}">'
                   f'{html.escape(TEXTS[language]["excerpt"].format(seconds=label))}</span></p>')
    texts = json.dumps(TEXTS)
    page = PAGE
    page = re.sub(r"__T:([a-z_]+)__", lambda match: spans[match.group(1)], page)
    for token, value in {"__CRITERIA__": "".join(criteria_rows), "__EXCERPT__": excerpt,
                         "__LANG__": language, "__CID__": comparison_id, "__RESULT_SCHEMA__": RESULT_SCHEMA,
                         "__TEXTS__": texts.replace("<", "\\u003c"), "__ANSWER__": answer_blob}.items():
        page = page.replace(token, value)
    return page


def create_comparison(first: Path, second: Path, output: Path, *, mp3: bool = False, ffmpeg: str | None = None,
                      language: str = "en", seed: int | None = None,
                      labels: tuple[str, str] | None = None, seconds: float | None = None) -> dict:
    """Build a blind A/B bundle from two projects or MODs. Sources are only read."""
    first, second, output = Path(first).resolve(), Path(second).resolve(), Path(output).resolve()
    if language not in LANGUAGES:
        raise ValidationError("Comparison language must be en or fr.")
    if first == second:
        raise ValidationError("Choose two different files to compare.")
    if seconds is not None and (isinstance(seconds, bool) or not isinstance(seconds, (int, float))
                                or not math.isfinite(seconds) or not 0 < seconds <= audio.MAX_RENDER_SECONDS):
        raise ValidationError(f"seconds must be greater than 0 and at most {audio.MAX_RENDER_SECONDS}.")
    if labels is None:
        names = [_default_label(first), _default_label(second)]
        if names[0] == names[1]:
            names = [f"{names[0]} (1)", f"{names[1]} (2)"]
    else:
        if not isinstance(labels, (tuple, list)) or len(labels) != 2:
            raise ValidationError("labels must be a pair of two texts.")
        names = [_check_label(label, index) for index, label in enumerate(labels)]
        if names[0] == names[1]:
            raise ValidationError("The two labels must differ.")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValidationError("Comparison output must be a new or empty directory; choose another name "
                              "to preserve existing files.", "OUTPUT_PATH")
    for source in (first, second):
        if output == source or source.is_relative_to(output):
            raise ValidationError("Comparison output must not contain or replace a source file.")

    modules = [_loader(first), _loader(second)]
    plans = [playback_plan(module) for module in modules]
    if seconds is None:
        for label, plan in zip(names, plans):
            if plan["duration_seconds"] > audio.MAX_RENDER_SECONDS:
                raise ValidationError(
                    f"{label!r} lasts {plan['duration_seconds']:.1f} s per cycle, above the "
                    f"{audio.MAX_RENDER_SECONDS} s render limit. Pass seconds=<N> to compare the first N seconds "
                    "of both versions, or shorten the arrangement.")
    rng = random.Random(seed) if seed is not None else random.SystemRandom()
    swapped = rng.random() < 0.5
    order = ("second", "first") if swapped else ("first", "second")  # (version heard as X, version heard as Y)
    index_of = {"first": 0, "second": 1}
    created = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    comparison_id = secrets.token_hex(6) if seed is None else f"{random.Random(seed).getrandbits(48):012x}"

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".chiploom-compare-", dir=output.parent) as temporary:
        folder = Path(temporary) / "bundle"
        folder.mkdir()
        sides: dict[str, dict] = {}
        for side, version in zip(("x", "y"), order):
            position = index_of[version]
            module = modules[position]
            mod_path, wav_path = folder / f"{side}.mod", folder / f"{side}.wav"
            project.atomic_bytes(mod_path, mod.encode(module))
            details = audio.render(mod_path, wav_path, seconds=seconds, ffmpeg=ffmpeg)
            files = {"mod": f"{side}.mod", "wav": f"{side}.wav", "mp3": None}
            encoded = None
            if mp3:
                encoded = audio.export_mp3(wav_path, folder / f"{side}.mp3", ffmpeg)
                encoded = {key: value for key, value in encoded.items() if key != "output"}
                files["mp3"] = f"{side}.mp3"
            report = analyze(module)
            sides[side] = {
                "version": version, "label": names[position], "title": module.title,
                "source_name": (first, second)[position].name,
                "source_sha256": audio.sha256((first, second)[position]),
                "mod_sha256": audio.sha256(mod_path), "files": files, "render": _kept_render(details),
                "optional_mp3": encoded, "report": report, "metrics": _metrics(report, details["audio"]),
            }
        metric_rows = []
        for key in sides["x"]["metrics"]:
            row = {"key": key, "x": sides["x"]["metrics"][key], "y": sides["y"]["metrics"][key]}
            channel = re.match(r"ch(\d)_", key)
            if channel:
                row["channel"] = int(channel.group(1))
            metric_rows.append(row)
        secret = {
            "schema": COMPARISON_SCHEMA, "id": comparison_id,
            **{side: {"version": sides[side]["version"], "label": sides[side]["label"],
                      "files": sides[side]["files"],
                      "warnings": [item["message"] for item in sides[side]["report"]["warnings"]]}
               for side in ("x", "y")},
            "metrics": metric_rows,
        }
        blob = base64.b64encode(json.dumps(secret, ensure_ascii=False).encode("utf-8")).decode("ascii")
        page = build_page(language, comparison_id, blob, seconds)
        key_file = {
            "schema": COMPARISON_SCHEMA, "id": comparison_id, "version": __version__, "created_at": created,
            "seed": seed, "excerpt_seconds": seconds, "language": language,
            "answer_key": {"x": sides["x"]["version"], "y": sides["y"]["version"]},
            "labels": {"first": names[0], "second": names[1]},
            "versions": {"x": {k: v for k, v in sides["x"].items() if k != "metrics"},
                         "y": {k: v for k, v in sides["y"].items() if k != "metrics"}},
            "note": "This file is the answer key. The page hides the mapping only in base64 until the listener "
                    "submits; this is a casual blind test, not a secure one. Loudness differences between the "
                    "renders are not compensated. Reports are measurements, not quality verdicts.",
        }
        project.write_json(folder / "comparison.json", key_file)
        project.atomic_bytes(folder / "index.html", page.encode("utf-8"))
        if output.exists():
            output.rmdir()  # Verified empty above; os.rename cannot replace a directory on Windows.
        folder.rename(output)
    return {
        "ok": True, "output": str(output), "page": str(output / "index.html"),
        "comparison": str(output / "comparison.json"), "id": comparison_id, "language": language,
        "excerpt_seconds": seconds,
        "answer_key": {"x": sides["x"]["version"], "y": sides["y"]["version"],
                       "labels": {"x": sides["x"]["label"], "y": sides["y"]["label"]}},
        "x": {"mod": str(output / "x.mod"), "wav": str(output / "x.wav"),
              "mp3": str(output / "x.mp3") if mp3 else None},
        "y": {"mod": str(output / "y.mod"), "wav": str(output / "y.wav"),
              "mp3": str(output / "y.mp3") if mp3 else None},
        "scope": "Casual blind test: the answer key is in comparison.json and base64 in index.html.",
    }
