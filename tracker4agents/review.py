"""An offline listening sheet for the prototype, not a full tracker editor."""

from __future__ import annotations

import html
import json
from pathlib import Path
import re

from .model import Module, mod_signature, playback_plan
from .project import atomic_bytes


def write_preview(module: Module, output: Path, wav_name: str, report_name: str, mp3_name: str | None = None,
                  language: str = "en") -> None:
    plan = playback_plan(module)
    stem = Path(wav_name).stem
    sample_count = sum(bool(sample.pcm) for sample in module.samples)
    bpm = plan["timeline"][0]["bpm"]
    title = html.escape(module.title)
    channels, xm = module.channels, module.format == "xm"
    if channels == 4 and not xm:
        default_description = "A four-channel MOD composition." if language == "en" else "Une composition MOD à quatre voies."
    else:
        kind = "XM" if xm else "MOD"
        default_description = (f"A {channels}-channel {kind} composition." if language == "en"
                               else f"Une composition {kind} à {channels} voies.")
    description = html.escape(str(module.metadata.get("display_description", default_description)))
    arrangement = html.escape(str(module.metadata.get("arrangement", "Patterns and samples are embedded in the MOD." if language == "en" else "Partition et sons intégrés dans le module MOD.")))
    duration = f"{plan['duration_seconds']:.2f}"
    names = module.metadata.get("channel_names", [f"Track {index + 1}" if language == "en" else f"Voie {index + 1}" for index in range(channels)])
    data = {
        "patterns": [[[pattern.get(row, channel).text() for channel in range(channels)]
                      for row in range(pattern.rows)] for pattern in module.patterns],
        "timeline": plan["timeline"], "orders": module.orders, "loop_start_seconds": plan["loop_start_seconds"],
    }
    sample_cards = []
    colors = ("#8fd8e8", "#f6bc7a", "#bbd996", "#c4a5ef")
    cell_colors = "".join(f"td:nth-child({index + 2}){{color:{colors[index % 4]}}}" for index in range(channels))
    badge = "FASTTRACKER 2 / XM" if xm else f"PROTRACKER / PAL / {mod_signature(module)}"
    for index, sample in enumerate(module.samples, 1):
        if not sample.pcm:
            continue
        count = min(360, len(sample.pcm))
        # Display two cycles for drawn waves, the whole duration for one-shots.
        length = len(sample.pcm)
        if sample.recipe and sample.recipe.get("type") == "draw":
            length = min(length, max(4, round(length / sample.recipe.get("cycles", 16) * 2)))
        points = " ".join(
            f"{point * 360 / max(1, count - 1):.2f},{38 - sample.pcm[min(length - 1, point * length // max(1, count))] * 30 / (1 << (sample.bits - 1)):.2f}"
            for point in range(count)
        )
        kind = ("looped PCM" if sample.loop_length else "one-shot PCM") if language == "en" else ("PCM bouclé" if sample.loop_length else "PCM sans boucle")
        name = sample.name[3:] if sample.name.startswith(f"{index:02X} ") else sample.name
        wave_label = "Waveform" if language == "en" else "Forme d’onde"
        unit = "bytes" if language == "en" else "octets"
        sample_cards.append(f'''<article class="sample"><div class="sample-name"><span>{index:02X}</span> {html.escape(name)}</div>
<svg viewBox="0 0 360 76" role="img" aria-label="{wave_label}: {html.escape(sample.name, quote=True)}"><path d="M0 38H360" stroke="#303b4c"/><polyline points="{points}" fill="none" stroke="{colors[(index - 1) % 4]}" stroke-width="1.5"/></svg>
<div class="sample-meta">{kind} · {len(sample.pcm)} {unit}</div><audio controls preload="none" src="samples/{index:02d}.wav"></audio></article>''')
    options = "".join(f'<option value="{index}">{index:02X} · {html.escape(pattern.name)}</option>'
                      for index, pattern in enumerate(module.patterns))
    headers = "".join(f"<th>{html.escape(str(name))}</th>" for name in names)
    encoded_data = json.dumps(data, separators=(",", ":")).replace("<", "\\u003c")
    page = '''<!doctype html>
<html lang="fr"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__ · ChipLoom</title><link rel="icon" href="data:,">
<style>
:root{color-scheme:dark;--bg:#0d131d;--panel:#151e2b;--line:#2a3547;--text:#e7edf5;--muted:#a3b0c2;--accent:#8fd8e8}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.55 system-ui,sans-serif}main{max-width:1200px;margin:auto;padding:44px 30px 65px}a{color:var(--accent)}
.topline{font-size:12px;letter-spacing:.18em;text-transform:uppercase;color:var(--accent)}h1{font-size:46px;line-height:1.1;margin:14px 0}h2{font-size:21px;margin:0 0 18px}p{color:var(--muted);max-width:750px}header{display:flex;justify-content:space-between;gap:20px;align-items:flex-start}.badge{font:12px ui-monospace,monospace;border:1px solid var(--line);padding:9px 13px;border-radius:24px;white-space:nowrap}
.player{display:grid;grid-template-columns:1.15fr 1fr;gap:26px;align-items:center;padding:24px;background:var(--panel);border:1px solid var(--line);border-radius:14px;margin:28px 0 35px}audio{display:block;width:100%;height:38px}.facts{display:flex;gap:28px;margin-top:12px;font-size:13px;color:var(--muted)}.facts strong{color:var(--text)}.links{font-size:13px;margin-top:14px;display:flex;flex-wrap:wrap;gap:18px}
.pattern-top{display:flex;align-items:center;justify-content:space-between;gap:15px;margin-bottom:15px}.pattern-top h2{margin:0}select{background:#1b2839;color:var(--text);border:1px solid #40536c;padding:9px;border-radius:7px;font:inherit}.pattern-panel{border:1px solid var(--line);border-radius:10px;overflow:hidden}.scroll{max-height:480px;overflow:auto}table{width:100%;border-collapse:collapse;white-space:nowrap;font:13px/1.3 ui-monospace,Consolas,monospace}th{background:#1c293a;position:sticky;top:0;text-align:left;padding:13px 16px;z-index:1}td{padding:7px 16px;border-bottom:1px solid #1b2636}td:first-child{width:65px;color:#8494ab}__CELLCOLORS__tr.beat{background:#172233}tr.active{background:#314159;outline:1px solid #6c8aab;outline-offset:-1px}tr{cursor:pointer}.hint{font-size:13px;margin:12px 0 30px}
.samples{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px}.sample{border:1px solid var(--line);border-radius:10px;background:var(--panel);padding:16px}.sample-name{font-weight:600;font-size:14px}.sample-name span{font:12px ui-monospace,monospace;color:var(--muted);margin-right:7px}.sample svg{display:block;width:100%;margin:10px 0}.sample-meta{color:var(--muted);font-size:11px;margin-bottom:13px}.sample audio{height:30px}footer{margin-top:32px;color:var(--muted);font-size:12px}
@media(max-width:850px){.samples{grid-template-columns:repeat(2,minmax(0,1fr))}.player{grid-template-columns:1fr}header{display:block}.badge{display:inline-block;margin-top:12px}main{padding:25px 18px}h1{font-size:38px}td,th{padding-left:9px;padding-right:9px}.pattern-top{align-items:flex-start;flex-direction:column}}
</style><main><header><div><div class="topline">tracker4agents · compositions MOD</div><h1>__TITLE__</h1><p>__DESCRIPTION__</p></div><div class="badge">__BADGE__</div></header>
<section class="player" aria-label="Écouter le morceau"><div><h2>Écoute le morceau</h2><audio id="song" controls preload="metadata" loop src="__WAV__"></audio><div class="links"><a href="__MOD__" download>Télécharger le MOD</a>__MP3__<a href="__PROJECT__" download>Projet éditable</a><a href="__REPORT__">Contrôles techniques</a></div></div><div><div class="facts"><div><strong>__CHANNELS__</strong><br>voies</div><div><strong>__COUNT__</strong><br>samples</div><div><strong>__BPM__</strong><br>BPM</div><div><strong>__DURATION__ s</strong><br>par boucle</div></div><p class="hint">__ARRANGEMENT__</p></div></section>
<section aria-label="Patterns"><div class="pattern-top"><h2>La partition du module</h2><label>Pattern <select id="pattern">__OPTIONS__</select></label></div><div class="pattern-panel"><div class="scroll"><table><thead><tr><th>Ligne</th>__HEADERS__</tr></thead><tbody id="rows"></tbody></table></div></div><p class="hint">Clique une ligne pour déplacer l’écoute. Notes en notation ProTracker ; samples et effets en hexadécimal. Cette vue permet d’inspecter la démo ; l’édition passe par le projet JSON.</p></section>
<section aria-label="Samples"><h2>La palette sonore créée par l’agent</h2><div class="samples">__SAMPLES__</div></section><footer>Rendu du fichier MOD exporté avec libopenmpt via FFmpeg. Les sons se trouvent dans le MOD ; aucun plugin externe n’est nécessaire pour le relire. Le rapport précise les vérifications effectuées.</footer></main>
<script id="score-data" type="application/json">__DATA__</script><script>
const score=JSON.parse(document.getElementById('score-data').textContent);
const audio=document.getElementById('song'),select=document.getElementById('pattern'),body=document.getElementById('rows');
let shown=-1,lastRow=-1;
function show(index){shown=index;lastRow=-1;body.replaceChildren();score.patterns[index].forEach((cells,row)=>{const tr=document.createElement('tr');tr.dataset.row=row;if(row%4===0)tr.classList.add('beat');[row.toString(16).toUpperCase().padStart(2,'0'),...cells].forEach(text=>{const td=document.createElement('td');td.textContent=text;tr.appendChild(td)});tr.addEventListener('click',()=>{const point=score.timeline.find(x=>x.pattern===index&&x.row===row);if(point)audio.currentTime=point.seconds});body.appendChild(tr)});select.value=index}
select.addEventListener('change',()=>{const index=Number(select.value);show(index);const point=score.timeline.find(x=>x.pattern===index);if(point)audio.currentTime=point.seconds});
audio.addEventListener('timeupdate',()=>{let point=score.timeline[0];for(const item of score.timeline){if(item.seconds>audio.currentTime)break;point=item}if(point.pattern!==shown)show(point.pattern);if(point.row!==lastRow){body.querySelector('.active')?.classList.remove('active');const tr=body.children[point.row];tr?.classList.add('active');if(!audio.paused&&tr){const box=body.closest('.scroll');const y=tr.offsetTop-box.querySelector('thead').offsetHeight;if(y<box.scrollTop||y>box.scrollTop+box.clientHeight-80)box.scrollTop=Math.max(0,y-120)}lastRow=point.row}});show(0);
document.querySelectorAll('audio').forEach(player=>player.addEventListener('play',()=>document.querySelectorAll('audio').forEach(other=>{if(other!==player)other.pause()})));
</script></html>'''
    page = page.replace("tracker4agents · compositions MOD", "ChipLoom · compositions MOD")
    page = page.replace("La palette sonore créée par l’agent", "Les samples du module")
    page = page.replace("Cette vue permet d’inspecter la démo", "Cette vue permet d’inspecter le morceau")
    page = page.replace('preload="metadata" loop', 'preload="metadata"')
    page = page.replace("document.querySelectorAll('audio').forEach", "audio.addEventListener('ended',()=>{audio.currentTime=score.loop_start_seconds;audio.play().catch(()=>{})});\ndocument.querySelectorAll('audio').forEach", 1)
    if language == "en":
        texts = {
            'lang="fr"': 'lang="en"', 'compositions MOD': 'MOD compositions',
            'Écouter le morceau': 'Listen to the song', 'Écoute le morceau': 'Listen to the song',
            'Télécharger le MOD': 'Download MOD', 'Projet éditable': 'Editable project',
            'Contrôles techniques': 'Technical checks', '<br>voies': '<br>channels', '<br>par boucle': '<br>per cycle',
            'La partition du module': 'Module patterns', '>Ligne<': '>Row<', 'Les samples du module': 'Module samples',
            'Clique une ligne pour déplacer l’écoute. Notes en notation ProTracker ; samples et effets en hexadécimal. Cette vue permet d’inspecter le morceau ; l’édition passe par le projet JSON.':
                'Click a row to seek. Notes use ProTracker notation; samples and effects are hexadecimal. This page is for inspection; edit the JSON project or use the desktop window.',
            'Rendu du fichier MOD exporté avec libopenmpt via FFmpeg. Les sons se trouvent dans le MOD ; aucun plugin externe n’est nécessaire pour le relire. Le rapport précise les vérifications effectuées.':
                'Audio rendered from the exported MOD with libopenmpt via FFmpeg. Samples are embedded in the MOD. The report describes the checks performed.',
        }
        for french, english in texts.items():
            page = page.replace(french, english)
    if xm:  # the page says MOD in its fixed texts; name the real format (placeholders keep their underscores)
        page = re.sub(r"(?<![_A-Z])MOD(?![_A-Z])", "XM", page)
    mp3_label = "MP3 copy" if language == "en" else "Copie MP3"
    mp3_link = f'<a href="{html.escape(mp3_name, quote=True)}" download>{mp3_label}</a>' if mp3_name else ""
    replacements = {"__TITLE__": title, "__DESCRIPTION__": description, "__ARRANGEMENT__": arrangement,
                    "__COUNT__": f"{sample_count:02d}", "__BPM__": str(bpm), "__DURATION__": duration,
                    "__MOD__": html.escape(f"{stem}{'.xm' if xm else '.mod'}", quote=True),
                    "__CELLCOLORS__": cell_colors, "__BADGE__": html.escape(badge), "__CHANNELS__": f"{channels:02d}",
                    "__PROJECT__": html.escape(f"{stem}.project.json", quote=True),
                    "__WAV__": html.escape(wav_name, quote=True), "__MP3__": mp3_link, "__REPORT__": html.escape(report_name, quote=True),
                    "__OPTIONS__": options, "__HEADERS__": headers, "__SAMPLES__": "".join(sample_cards), "__DATA__": encoded_data}
    for token, value in replacements.items():
        page = page.replace(token, value)
    atomic_bytes(output, page.encode("utf-8"))
