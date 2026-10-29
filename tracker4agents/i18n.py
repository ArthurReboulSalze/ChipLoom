"""Desktop strings. English is the source language; the musical data is never translated."""

import re

LANGUAGES = ("en", "fr")

FR = {
    "Song samples": "Samples du morceau", "Sample library": "Bibliothèque",
    "Search samples…": "Rechercher un sample…", "All types": "Tous les types",
    "Cyclic waves": "Ondes cycliques", "Percussion": "Percussions", "Textures": "Textures",
    "Effects": "Effets", "Unclassified": "Non classés", "Silent": "Silencieux",
    "All roles": "Tous les rôles", "Bass": "Basse", "Lead": "Mélodie", "Arpeggio": "Arpège",
    "MOD compatible": "Compatibles MOD", "Folder…": "Dossier…", "Refresh": "Actualiser",
    "Select a library sample": "Sélectionne un sample de la bibliothèque", "Listen": "Écouter",
    "Slot": "Emplacement", "Replace": "Remplacer", "Adapt copy": "Adapter la copie",
    "Add to song": "Ajouter au morceau", "New / free slot": "Emplacement libre", "Empty": "Vide",
    "Choose a sample library folder": "Choisir le dossier de bibliothèque de samples",
    "Loading…": "Chargement…", "{count} samples": "{count} samples",
    "Sample library unavailable": "Bibliothèque indisponible",
    "Choose a folder containing library.json.": "Choisis un dossier contenant library.json.",
    "No matching samples": "Aucun sample correspondant",
    "{size} bytes · {loop} · fine tune {tune} · volume {volume}":
        "{size} octets · {loop} · accord fin {tune} · volume {volume}",
    "Existing notes using this slot will use the replacement.":
        "Les notes utilisant cet emplacement joueront le nouveau sample.",
    "Prepare a compatible copy for MOD; keep the library original.":
        "Préparer une copie compatible MOD en conservant l'original de la bibliothèque.",
    "This sample needs a compatible copy before adding.": "Ce sample nécessite une copie adaptée avant l'ajout.",
    "No free slot. Select an existing slot to replace.": "Aucun emplacement libre. Choisis un emplacement à remplacer.",
    "Check Replace to use this occupied slot.": "Coche Remplacer pour utiliser cet emplacement occupé.",
    "Library sample unavailable: {detail}": "Sample de bibliothèque indisponible : {detail}",
    "Cannot add library sample: {detail}": "Ajout du sample impossible : {detail}",
    "Added {name} to slot {slot} · Ctrl+Z to undo": "{name} ajouté à l'emplacement {slot} · Ctrl+Z pour annuler",
    "File": "Fichier", "Edit": "Édition", "Help": "Aide",
    "Open a MOD or project…": "Ouvrir un MOD ou un projet…",
    "Save project…": "Enregistrer le projet…", "Save project as…": "Enregistrer le projet sous…",
    "Reload file": "Recharger le fichier", "Export MOD…": "Exporter le MOD…",
    "Export WAV…": "Exporter WAV…", "Export MP3…": "Exporter MP3…",
    "Quit": "Quitter", "Undo": "Annuler", "Redo": "Rétablir", "About": "À propos",
    "Open…": "Ouvrir…", "MOD · 4 CHANNELS · PAL": "MOD · 4 VOIES · PAL",
    "Open a module to get started": "Ouvre un module pour commencer",
    "Play": "Écouter", "Pause": "Pause", "Stop": "Stop", "Loop": "Boucle", "Volume": "Volume",
    "LIBRARY": "BIBLIOTHÈQUE", "SAMPLES": "SAMPLES",
    "MOD, XM and JSON projects\nDrop a file here to open it.\nF5 reloads changes made by the agent.":
        "Projets MOD, XM et JSON\nDépose un fichier ici pour l'ouvrir.\nF5 recharge les changements de l'agent.",
    "Order": "Ordre", "Follow playback": "Suivre la lecture",
    "− 1 semitone": "− 1 demi-ton", "+ 1 semitone": "+ 1 demi-ton",
    "Track {number}": "Voie {number}", "Track {number} · MUTED": "Voie {number} · MUET",
    "Click to mute track {number}": "Clique pour couper la voie {number}",
    "Click to unmute track {number}": "Clique pour réactiver la voie {number}",
    "Solo": "Solo", "Solo track {number}": "Écouter seulement la voie {number}",
    "Select a sample": "Sélectionne un sample", "Play sample": "Écouter",
    "Fine tune": "Accord fin", "Apply": "Appliquer", "Title": "Titre", "Tempo": "Tempo",
    "Ticks / row": "Ticks / ligne", "Apply at start": "Appliquer au départ",
    "Ready": "Prêt", "Compositions": "Compositions", "Recent files": "Fichiers récents",
    "Unsaved changes": "Modifications non enregistrées",
    "Save the project changes before continuing?": "Enregistrer les modifications du projet avant de continuer ?",
    "Save": "Enregistrer", "Discard": "Ignorer", "Cancel": "Annuler",
    "Open a module or project": "Ouvrir un module ou un projet",
    "Modules and projects (*.mod *.MOD *.xm *.XM *.json);;All files (*)":
        "Modules et projets (*.mod *.MOD *.xm *.XM *.json);;Tous les fichiers (*)",
    "Cannot open: {detail}": "Ouverture impossible : {detail}",
    "Session could not be saved: {detail}": "Session non enregistrée : {detail}",
    "Untitled": "Sans titre", "New project": "Nouveau projet",
    "{bpm} BPM  ·  {orders} orders  ·  {samples} samples  ·  {seconds:.2f} s":
        "{bpm} BPM  ·  {orders} ordres  ·  {samples} samples  ·  {seconds:.2f} s",
    "Preparing…": "Préparation…", "Preparing playback…": "Préparation de l'écoute…",
    "Audio unavailable: {detail}": "Écoute indisponible : {detail}",
    "Ready to play": "Prêt à écouter", "Playback failed: {detail}": "Lecture impossible : {detail}",
    "Sample: {detail}": "Sample : {detail}",
    "This order is not reached in the module's playback cycle.": "Cet ordre n'est pas atteint dans le cycle de lecture du module.",
    "loop {start} → {end}": "boucle {start} → {end}", "no loop": "sans boucle",
    "{size} bytes · mono 8-bit · {loop} · C-2 preview": "{size} octets · mono 8 bits · {loop} · aperçu C-2",
    "Change applied · Ctrl+Z to undo": "Modification appliquée · Ctrl+Z pour annuler",
    "Select a cell in the track you want to transpose.": "Sélectionne une cellule dans la voie à transposer.",
    "File {suffix} (*{suffix})": "Fichier {suffix} (*{suffix})",
    "Save an editable project": "Enregistrer un projet éditable", "Project saved": "Projet enregistré",
    "Export MOD module": "Exporter le module MOD", "MOD exported: {name}": "MOD exporté : {name}",
    "Export audible mix as {format}": "Exporter le mix audible en {format}",
    "Exporting audio…": "Export audio en cours…", "Audio exported: {name}": "Audio exporté : {name}",
    "Note": "Note", "Smp": "Smp", "Effect": "Effet",
    "Double-click to edit. Notes C-1..B-3; sample and effect in hexadecimal.":
        "Double-clique pour modifier. Notes C-1..B-3 ; sample et effet en hexadécimal.",
    "Theme": "Thème", "Language": "Langue", "Midnight": "Nuit", "Amber": "Ambre",
    "Violet": "Violet", "Light": "Clair", "LEVEL": "NIVEAU",
    "Stereo audio level: average level and peak, after the volume control.":
        "Niveau audio stéréo : niveau moyen et crête, après le réglage du volume.",
    "PROPOSALS": "PROPOSITIONS", "DETAILS": "DÉTAILS", "TAKES": "VERSIONS", "Agent": "Agent",
    "Proposals from the agent appear here. Select one to preview it on the pattern.":
        "Les propositions de l'agent apparaissent ici. Sélectionnes-en une pour la voir sur le pattern.",
    "Accept": "Accepter", "Reject": "Refuser", "Listen to proposal": "Écouter la proposition",
    "Clear preview": "Effacer l'aperçu", "Open take": "Ouvrir la version",
    "{id} · {label} · {author} · {cells} cells": "{id} · {label} · {author} · {cells} cellules",
    "outdated": "périmée",
    "{id} · {label} · {author} · {seconds:.1f} s": "{id} · {label} · {author} · {seconds:.1f} s",
    "This proposal can no longer be applied: {detail}": "Cette proposition ne peut plus être appliquée : {detail}",
    "The score changed in these cells since the proposal: accepting may ask to overwrite.":
        "La partition a changé dans ces cellules depuis la proposition : l'accepter peut demander d'écraser.",
    "Conflicting edits": "Modifications en conflit",
    "These parts changed since the agent proposed this:": "Ces éléments ont changé depuis la proposition de l'agent :",
    "Accept anyway and overwrite them?": "Accepter quand même et les écraser ?",
    "Proposal cannot be applied: {detail}": "Proposition inapplicable : {detail}",
    "Accepted: {label} · Ctrl+Z to undo": "Acceptée : {label} · Ctrl+Z pour annuler",
    "Rejected: {label}": "Refusée : {label}",
    "Rendering the proposal…": "Préparation de la proposition…",
    "Listening to proposal {id}": "Écoute de la proposition {id}",
    "Live collaboration": "Collaboration en direct",
    "Accept proposal\tCtrl+Enter": "Accepter la proposition\tCtrl+Entrée",
    "Reject proposal": "Refuser la proposition", "Show the Agent tab": "Afficher l'onglet Agent",
    "Live: off": "Direct : désactivé", "Live: listening": "Direct : à l'écoute",
    "Live: agent connected": "Direct : agent connecté",
    "Live collaboration is off (Agent menu).": "La collaboration en direct est désactivée (menu Agent).",
    "Waiting for an agent: it finds this window with `chiploom live`.":
        "En attente d'un agent : il trouve cette fenêtre avec `chiploom live`.",
    "An agent worked on this window in the last two minutes.": "Un agent a travaillé sur cette fenêtre ces deux dernières minutes.",
    "Agent proposal: {label} ({author}) · see the Agent tab": "Proposition de l'agent : {label} ({author}) · voir l'onglet Agent",
    "New take: {label}": "Nouvelle version : {label}",
    "Live collaboration unavailable: {detail}": "Collaboration en direct indisponible : {detail}",
    "{author}: {label} · {summary}": "{author} : {label} · {summary}",
    "Playback": "Lecture", "Real-time playback": "Lecture en temps réel",
    "Audio buffer": "Tampon audio", "Low · 80 ms": "Faible · 80 ms", "Normal · 150 ms": "Normal · 150 ms",
    "High · 300 ms": "Élevé · 300 ms", "Very high · 600 ms": "Très élevé · 600 ms",
    "Audio latency about {ms} ms. A larger buffer rides out window moves and heavy redraws without crackling, but sound reacts a little later to edits.":
        "Latence audio d'environ {ms} ms. Un tampon plus grand supporte les déplacements de fenêtre et les gros réaffichages sans craquements, mais le son réagit un peu plus tard aux modifications.",
    "Real-time playback (libxmp) · audio buffer {ms} ms": "Lecture en temps réel (libxmp) · tampon audio {ms} ms",
    "Real-time playback needs libxmp (not found): playing rendered audio instead. Run `python tools/setup_reference.py`, install libxmp or set CHIPLOOM_LIBXMP.":
        "La lecture en temps réel demande libxmp (introuvable) : lecture de l'audio rendu à la place. Lance `python tools/setup_reference.py`, installe libxmp ou définis CHIPLOOM_LIBXMP.",
    "Real-time playback needs an audio output device: playing rendered audio instead.":
        "La lecture en temps réel demande une sortie audio : lecture de l'audio rendu à la place.",
    "Real-time playback failed: {detail}": "Lecture en temps réel impossible : {detail}",
    "Real-time playback failed ({detail}): playing rendered audio instead.":
        "Lecture en temps réel impossible ({detail}) : lecture de l'audio rendu à la place.",
    "Edit mode": "Mode saisie", "Step": "Pas", "Octave": "Octave", "Keyboard": "Clavier", "Auto": "Auto",
    "Cut cells\tCtrl+X": "Couper les cellules\tCtrl+X", "Copy cells\tCtrl+C": "Copier les cellules\tCtrl+C",
    "Paste cells\tCtrl+V": "Coller les cellules\tCtrl+V", "Clear cells\tDel": "Effacer les cellules\tSuppr",
    "Type notes with the piano keys (Ctrl+E)": "Saisir des notes avec les touches de piano (Ctrl+E)",
    "Rows to advance after each entry": "Lignes à avancer après chaque saisie",
    "Base octave of the lower key row (F1-F3, numpad + and -)":
        "Octave de base de la rangée basse (F1-F3, pavé numérique + et -)",
    "Edit mode on: piano keys enter notes": "Mode saisie activé : les touches de piano écrivent des notes",
    "Edit mode off": "Mode saisie désactivé",
    "Copied {rows} × {channels} cells": "{rows} × {channels} cellules copiées",
    "Nothing to paste.": "Rien à coller.",
    "The block is already at the edge of the pattern.": "Le bloc est déjà au bord du pattern.",
    "That key is outside the C-1..B-3 range at this octave.": "Cette touche sort de C-1..B-3 à cette octave.",
    "Insert": "Insérer", "New": "Nouveau", "Duplicate": "Dupliquer", "Remove": "Retirer", "Rename…": "Renommer…",
    "Insert the current pattern after this order": "Insérer le pattern courant après cet ordre",
    "Insert a new empty pattern after this order": "Insérer un nouveau pattern vide après cet ordre",
    "Insert a copy of the current pattern after this order": "Insérer une copie du pattern courant après cet ordre",
    "Remove this order (the pattern stays in the song)": "Retirer cet ordre (le pattern reste dans le morceau)",
    "Move this order up": "Monter cet ordre", "Move this order down": "Descendre cet ordre",
    "Rename the current pattern": "Renommer le pattern courant",
    "Rename pattern": "Renommer le pattern", "Name of pattern {number}": "Nom du pattern {number}",
    "A song keeps at least one order.": "Un morceau garde au moins un ordre.",
    "Order removed; pattern {number} was no longer used and was removed too · Ctrl+Z to undo":
        "Ordre retiré ; le pattern {number} n'était plus utilisé et a été retiré aussi · Ctrl+Z pour annuler",
    "Cannot reload the changed file: {detail}": "Rechargement impossible du fichier modifié : {detail}",
    "Agent changes merged with yours · {count} conflicts, agent version kept: {where}":
        "Changements de l'agent fusionnés avec les tiens · {count} conflits, version de l'agent conservée : {where}",
    "Agent changes merged with your edits · Ctrl+Z to undo":
        "Changements de l'agent fusionnés avec tes modifications · Ctrl+Z pour annuler",
    "Reloaded the agent's changes · Ctrl+Z to undo": "Changements de l'agent rechargés · Ctrl+Z pour annuler",
    "+ Copy": "+ Copie", "Move": "Déplacer",
    "Octave {octave} · Keyboard {layout}": "Octave {octave} · Clavier {layout}",
    "The piano keys play notes: the lower row from octave {octave}, the upper rows from octave {next}. F1-F3 or numpad + and - change the octave.":
        "Les touches de piano jouent des notes : la rangée basse à partir de l'octave {octave}, les rangées hautes à partir de l'octave {next}. F1-F3 ou pavé numérique + et - changent l'octave.",
    # --- sound workshop: sample editor and levels
    "Trim": "Couper", "Gain": "Gain", "Fade": "Fondu", "Preview": "Aperçu", "Levels": "Niveaux",
    "Loop = selection": "Boucle = sélection", "No loop": "Sans boucle", "Whole sample": "Tout le sample",
    "Set loop": "Régler la boucle", "Trim sample": "Couper le sample", "Change gain": "Changer le gain",
    "Fade sample": "Fondu du sample",
    "two zero bytes added at the start": "deux octets nuls ajoutés au début", "loop shortened": "boucle raccourcie",
    "loop removed": "boucle retirée",
    "start ": "début ", "length ": "longueur ", "from ": "de ", "to ": "à ", "in ": "entrée ", "out ": "sortie ",
    "Loop start in bytes (even). Drag the amber handles on the waveform.":
        "Début de la boucle en octets (pair). Glisse les poignées ambrées sur la forme d'onde.",
    "Loop length in bytes (even, at least 4); 0 means no loop.": "Longueur de la boucle en octets (paire, 4 au moins) ; 0 = pas de boucle.",
    "First byte kept. Drag in the waveform to select a range.": "Premier octet conservé. Glisse dans la forme d'onde pour choisir une plage.",
    "End of the kept range, in bytes (even).": "Fin de la plage conservée, en octets (pair).",
    "Gain in decibels. A gain that would clip is refused, with the clean headroom.":
        "Gain en décibels. Un gain qui saturerait est refusé, avec la marge propre.",
    "Bytes faded in from silence at the start.": "Octets en fondu depuis le silence au début.",
    "Bytes faded out to silence at the end.": "Octets en fondu vers le silence à la fin.",
    "Hear the edited copy and read what would change. The song is not touched.":
        "Écoute la copie modifiée et lis ce qui changerait. Le morceau n'est pas touché.",
    "Apply as one undoable change (Ctrl+Z).": "Appliquer en une seule modification annulable (Ctrl+Z).",
    "Pick a sample in the list to edit its loop, trim, fades and gain.":
        "Choisis un sample dans la liste pour modifier sa boucle, sa coupe, ses fondus et son gain.",
    "This song has no samples yet: add one from the Sample library or the Create tab.":
        "Ce morceau n'a pas encore de sample : ajoute-en un depuis la Bibliothèque ou l'onglet Créer.",
    "headroom {db:+.1f} dB": "marge {db:+.1f} dB", "fine tune ": "finetune ",
    "Drag across the waveform to select the part that should loop.":
        "Glisse sur la forme d'onde pour choisir la partie à boucler.",
    "No loop afterwards: the sample plays once.": "Plus de boucle ensuite : le sample se joue une fois.",
    "Loop {start} → {end} ({length} bytes) · jump at the seam {jump}":
        "Boucle {start} → {end} ({length} octets) · saut à la jonction {jump}",
    "Keeps bytes {start} → {end}: {before} → {after} bytes": "Garde les octets {start} → {end} : {before} → {after} octets",
    "{db:+.1f} dB · peak {before} → {after} · {changed} bytes change · clipped {clipped}":
        "{db:+.1f} dB · crête {before} → {after} · {changed} octets modifiés · saturés {clipped}",
    "Fade in {fade_in} · out {fade_out} bytes · {changed} bytes change":
        "Fondu d'entrée {fade_in} · de sortie {fade_out} octets · {changed} octets modifiés",
    "Nothing changed: the sample already is like that.": "Rien n'a changé : le sample est déjà ainsi.",
    "applied, Ctrl+Z to undo": "appliqué, Ctrl+Z pour annuler", "{what} · Ctrl+Z to undo": "{what} · Ctrl+Z pour annuler",
    "Nothing was changed.": "Rien n'a été modifié.", "This edit needs a choice": "Cette modification demande un choix",
    "This project only allows samples from its declared source, so the sound cannot be edited this way.":
        "Ce projet n'accepte que les samples de sa source déclarée : le son ne peut pas être modifié ainsi.",
    "A gain of {db:+.1f} dB would push loud bytes past the 8-bit limit.":
        "Un gain de {db:+.1f} dB ferait dépasser la limite 8 bits aux octets forts.",
    "The largest clean gain is {room:+.1f} dB.": "Le plus grand gain propre est {room:+.1f} dB.",
    "Apply it anyway and flatten (clip) the loudest bytes": "L'appliquer quand même et écrêter les octets les plus forts",
    "The kept range cuts into the loop.": "La plage conservée coupe la boucle.",
    "Keep only the part of the loop inside the range": "Garder seulement la partie de la boucle dans la plage",
    "This fade reaches into the loop, so every repeat would dip.": "Ce fondu entre dans la boucle : chaque répétition baisserait.",
    "Fade inside the loop anyway": "Faire le fondu dans la boucle quand même",
    "A sample without a loop must start with two silent bytes (the replayer's no-loop marker).":
        "Un sample sans boucle doit commencer par deux octets silencieux (le marqueur « sans boucle » du lecteur).",
    "Add two zero bytes in front; the sound itself stays exactly the same":
        "Ajouter deux octets nuls devant ; le son lui-même reste exactement le même",
    "Match": "Égaliser", "Match all": "Tout égaliser", "Sample": "Sample", "Level": "Niveau", "Target": "Cible",
    "Difference": "Écart", "Match level": "Égaliser le niveau", "Match all levels": "Égaliser tous les niveaux",
    "Open a song with samples to see how loud each one is.": "Ouvre un morceau avec des samples pour voir leur niveau.",
    "Differences above {limit} dB are flagged. Levels are the samples' own loudness at their volume, not a measurement of the mix.":
        "Les écarts de plus de {limit} dB sont signalés. Les niveaux sont ceux des samples à leur volume, pas une mesure du mix.",
    "Targets from the sample bank at {path}": "Cibles issues de la banque de samples dans {path}",
    "Targets: built-in reference levels (no sample bank found; pick one in the Sample library tab)":
        "Cibles : niveaux de référence intégrés (aucune banque trouvée ; choisis-en une dans l'onglet Bibliothèque)",
    "More than {limit} dB from the target: use Match.": "À plus de {limit} dB de la cible : utilise Égaliser.",
    "Set this sample's volume to its role's target level.": "Règle le volume de ce sample sur le niveau cible de son rôle.",
    "Cannot match the level: {detail}": "Égalisation impossible : {detail}",
    "Matched {count} sample levels · Ctrl+Z to undo": "{count} niveaux de samples égalisés · Ctrl+Z pour annuler",
    "Kick": "Grosse caisse", "Snare": "Caisse claire", "Hat": "Charleston", "Chord": "Accord", "Texture": "Texture",
    "Automatic": "Automatique",
    # --- sound workshop: the Create tab
    "Create": "Créer", "Instruments": "Instruments", "RECIPE": "RECETTE", "SOUND": "SON", "ADD TO SONG": "AJOUTER AU MORCEAU",
    "Sine": "Sinus", "Triangle": "Triangle", "Saw": "Dent de scie", "Square": "Carré", "Clear": "Effacer",
    "Pulse": "Impulsion", "Noise": "Bruit", "Wave": "Onde", "Pluck": "Pincé", "Draw": "Dessin", "Kick hat": "Grosse caisse + charley",
    "Snare hat": "Caisse claire + charley",
    "Number of points along one cycle": "Nombre de points sur un cycle",
    "Listen after each change": "Écouter après chaque changement",
    "Match the volume to the role's level": "Régler le volume sur le niveau du rôle",
    "Keep the drawing as plain sample data instead of a recipe": "Garder le dessin comme données de sample brutes plutôt que comme recette",
    "Name": "Nom", "Role": "Rôle", "First free slot": "Premier emplacement libre", "free": "libre", "auto": "auto",
    "Start a synthesized song…": "Démarrer un morceau synthétisé…",
    "Open a new song holding the starter palette of created samples (kick, snare, hat, bass, leads, noise), volumes matched to their roles.":
        "Ouvre un nouveau morceau avec la palette de départ de samples créés (grosse caisse, caisse claire, charley, basses, mélodies, bruit), volumes réglés selon leurs rôles.",
    "Synth Palette": "Palette synthé", "Open a song first.": "Ouvre d'abord un morceau.",
    "Replace this sample?": "Remplacer ce sample ?", "Slot {slot} holds {name!r}. Replace it with the new sound?":
        "L'emplacement {slot} contient {name!r}. Le remplacer par le nouveau son ?",
    "Added to slot {slot} · Ctrl+Z to undo": "Ajouté à l'emplacement {slot} · Ctrl+Z pour annuler",
    "This song only allows samples from its declared source, so this sound cannot be added.":
        "Ce morceau n'accepte que les samples de sa source déclarée : ce son ne peut pas être ajouté.",
    "That sample slot cannot be used: {detail}": "Cet emplacement de sample est inutilisable : {detail}",
    "This sound cannot be added: {detail}": "Ce son ne peut pas être ajouté : {detail}",
    "Cannot start a synthesized song: {detail}": "Impossible de démarrer un morceau synthétisé : {detail}",
    "Started a synthesized song with {count} created samples": "Morceau synthétisé démarré avec {count} samples créés",
    "This recipe cannot be built: {detail}": "Cette recette ne peut pas être construite : {detail}",
    "{bytes} bytes · {kind} · plays {rate:.0f} Hz at {note}": "{bytes} octets · {kind} · joue à {rate:.0f} Hz sur {note}",
    "looped": "bouclé", "one-shot": "joué une fois", "tuning off by {cents:+.1f} cents": "désaccord de {cents:+.1f} cents",
    "Loudness {db:.1f} dB (role {role}, bank reference {reference:.1f} dB)":
        "Niveau {db:.1f} dB (rôle {role}, référence de la banque {reference:.1f} dB)",
    "Peak {peak} dBFS · RMS {rms} dBFS · clipped {clipped}": "Crête {peak} dBFS · RMS {rms} dBFS · saturés {clipped}",
    "Shape": "Forme", "Frequency (Hz)": "Fréquence (Hz)", "Cycles": "Cycles", "Pulse width": "Largeur d'impulsion",
    "Length (bytes)": "Longueur (octets)", "Smoothing": "Lissage", "1-bit noise": "Bruit 1 bit", "Seed": "Graine",
    "Peak": "Crête", "Duration (s)": "Durée (s)", "Drive": "Saturation", "Points": "Points",
    "Clean looped chip wave (pulse, triangle, saw, sine) tuned so note C-2 plays the stated frequency; or a looped noise buffer for texture.":
        "Onde chip bouclée propre (impulsion, triangle, dent de scie, sinus) accordée pour que la note C-2 joue la fréquence indiquée ; ou un bruit bouclé pour la texture.",
    "Low pitch-dropping thump with a click.": "Coup grave à hauteur descendante, avec un clic.",
    "Noise burst over a short tone.": "Rafale de bruit sur une courte tonalité.",
    "Very short high noise tick.": "Tic de bruit aigu très court.",
    "Kick with a hat tick on top: one note, two drums.": "Grosse caisse avec un tic de charley dessus : une note, deux percussions.",
    "Snare with a hat tick on top.": "Caisse claire avec un tic de charley dessus.",
    "One-shot plucked tone with a baked decay (bass or lead); play it at C-2 for its stated pitch.":
        "Son pincé joué une fois, à décroissance intégrée (basse ou mélodie) ; joue-le en C-2 pour sa hauteur indiquée.",
    "Your own looped wave from 4 to 256 points between -1 and 1 (hand-drawn timbres).":
        "Ta propre onde bouclée de 4 à 256 points entre -1 et 1 (timbres dessinés à la main).",
    "Waveform. Noise takes seed/length/smooth; the others take frequency/cycles.":
        "Forme d'onde. Le bruit prend graine/longueur/lissage ; les autres fréquence/cycles.",
    "Pitch in Hz heard when the sample plays at tracker note C-2.": "Hauteur en Hz entendue quand le sample joue la note C-2.",
    "Cycles in the loop. Omit for the fewest cycles that land within 2 cents.":
        "Cycles dans la boucle. Absent : le moins de cycles qui tombent à 2 cents près.",
    "Cycles in the loop.": "Cycles dans la boucle.",
    "Pulse width: 0.125, 0.25 and 0.5 are the classic ones.": "Largeur d'impulsion : 0,125, 0,25 et 0,5 sont les classiques.",
    "Pulse width of the underlying tone.": "Largeur d'impulsion de la tonalité sous-jacente.",
    "Loop length in bytes (even).": "Longueur de la boucle en octets (paire).",
    "Low-pass amount: 0 is bright white noise, 0.9 is dark rumble.": "Filtre passe-bas : 0 = bruit blanc clair, 0,9 = grondement sombre.",
    "1-bit noise (every byte at full height): the loudest, harshest texture.": "Bruit 1 bit (chaque octet à pleine hauteur) : la texture la plus forte et la plus dure.",
    "Seed of the noise generator; the same seed gives the same bytes.": "Graine du générateur de bruit ; la même graine donne les mêmes octets.",
    "Fraction of full 8-bit scale used by the loudest byte.": "Part de l'échelle 8 bits pleine utilisée par l'octet le plus fort.",
    "Length in seconds.": "Durée en secondes.",
    "Soft saturation that evens out loud head and quiet tail: a denser, louder-in-RMS hit. 0 leaves the original sound; 0.3 suits matching a sample bank.":
        "Saturation douce qui égalise l'attaque forte et la queue faible : un coup plus dense, plus fort en RMS. 0 laisse le son d'origine ; 0,3 convient pour s'accorder à une banque.",
    "4 to 256 values along one cycle.": "De 4 à 256 valeurs sur un cycle.",
    # --- sound workshop: instruments
    "INSTRUMENTS": "INSTRUMENTS", "SAVE THE SELECTED SAMPLE": "ENREGISTRER LE SAMPLE CHOISI",
    "APPLY AT THE CURSOR": "APPLIQUER AU CURSEUR", "Search instruments…": "Rechercher un instrument…",
    "Delete": "Supprimer", "Save instrument": "Enregistrer l'instrument", "Apply at cursor": "Appliquer au curseur",
    "Replace effects already in the way": "Remplacer les effets déjà présents",
    "Phrase: one effect per row after the note (000 = nothing)": "Phrase : un effet par ligne après la note (000 = rien)",
    "+ Row": "+ Ligne", "− Row": "− Ligne", "row {number}": "ligne {number}",
    "Choose an instrument folder": "Choisir le dossier d'instruments",
    "Delete this instrument?": "Supprimer cet instrument ?",
    "Delete {id}? The file is removed from the folder.": "Supprimer {id} ? Le fichier est retiré du dossier.",
    "{id} · {name} · {role} · {rows} phrase rows": "{id} · {name} · {role} · {rows} lignes de phrase",
    "Select a sample in Song samples first.": "Choisis d'abord un sample dans Samples du morceau.",
    "The instrument was not saved: {detail}": "L'instrument n'a pas été enregistré : {detail}",
    "Select an instrument and a pattern cell first.": "Choisis d'abord un instrument et une cellule du pattern.",
    "The instrument was not applied: {detail}": "L'instrument n'a pas été appliqué : {detail}",
    "The instrument folder cannot be read: {detail}": "Le dossier d'instruments est illisible : {detail}",
    "No instruments here yet. Select a sample in Song samples, write a phrase and press Save instrument.":
        "Aucun instrument ici pour l'instant. Choisis un sample dans Samples du morceau, écris une phrase et appuie sur Enregistrer l'instrument.",
    "No instrument matches.": "Aucun instrument ne correspond.",
    "{count} instrument files could not be read.": "{count} fichiers d'instrument illisibles.",
    "Saved {id} · {name}": "{id} · {name} enregistré",
    "{name}: {count} rows written at row {row}": "{name} : {count} lignes écrites à partir de la ligne {row}",
    "{count} effects kept because something was already there": "{count} effets conservés car la place était prise",
    "Apply instrument at cursor\tCtrl+I": "Appliquer l'instrument au curseur\tCtrl+I",
    # --- open in a browser
    "Open in a browser…": "Ouvrir dans un navigateur…", "Open in a browser": "Ouvrir dans un navigateur",
    "Open this address in a browser to listen to this song and edit it with the agent, as \"human-web\". No code is needed. The agent keeps its own access.":
        "Ouvre cette adresse dans un navigateur pour écouter ce morceau et le modifier avec l'agent, sous le nom « human-web ». Aucun code n'est nécessaire. L'agent garde son propre accès.",
    "Address": "Adresse", "Copy": "Copier", "Open": "Ouvrir", "Close": "Fermer",
    "Address copied": "Adresse copiée", "This computer only": "Cet ordinateur seulement",
    "Allow devices on my local network": "Autoriser les appareils de mon réseau local",
    "Opens the studio (and only the studio) to this computer's private network addresses.":
        "Ouvre le studio (et lui seul) aux adresses du réseau privé de cet ordinateur.",
    "The local network could not be opened: {detail}": "Le réseau local n'a pas pu être ouvert : {detail}",
    "Anyone on that network who knows the address can listen and edit, and the traffic is plain HTTP. Turn it on only on a network you trust.":
        "Quiconque est sur ce réseau et connaît l'adresse peut écouter et modifier, et le trafic est en HTTP simple. Ne l'active que sur un réseau de confiance.",
    "LAN listeners are not running yet.": "Le réseau local n'est pas encore ouvert.",
    "CONNECTED BROWSERS": "NAVIGATEURS CONNECTÉS", "Device": "Appareil", "Browser": "Navigateur", "Network": "Réseau",
    "Last seen": "Dernière activité", "local network": "réseau local", "this computer": "cet ordinateur",
    "No browser is connected yet.": "Aucun navigateur n'est encore connecté.",
    "Live collaboration is off: turn it on in the Agent menu to open the song in a browser.":
        "La collaboration en direct est désactivée : active-la dans le menu Agent pour ouvrir le morceau dans un navigateur.",
    "Browsers: {count}": "Navigateurs : {count}",
    "Browsers connected to this song (Agent menu, Open in a browser…)": "Navigateurs connectés à ce morceau (menu Agent, Ouvrir dans un navigateur…)",
    "Edit from a browser ({author}): {label} · {summary}": "Modification depuis un navigateur ({author}) : {label} · {summary}",
    "Last agent activity: {seconds} s ago": "Dernière activité de l'agent : il y a {seconds} s",
    "The agent asks to open {name}: answer the save prompt":
        "L'agent demande d'ouvrir {name} : réponds à la question d'enregistrement",
    "Compare with current": "Comparer avec l'actuel", "End comparison": "Terminer la comparaison",
    "Compare a take with the current song": "Comparer une version avec le morceau actuel",
    "Select a take to compare with the current song.": "Sélectionne une version à comparer avec le morceau actuel.",
    "Comparing: {listening}": "Comparaison : {listening}",
    "take {id} · {label} (B)": "version {id} · {label} (B)", "current song (A)": "morceau actuel (A)",
    "Listening to {listening}": "Écoute de {listening}",
    "Ctrl+B: hear the take, then switch between it and the current song at the same position":
        "Ctrl+B : écouter la version, puis basculer entre elle et le morceau actuel à la même position",
    "Listen to current song (A)": "Écouter le morceau actuel (A)", "Listen to take (B)": "Écouter la version (B)",
    "listening to a take": "écoute d'une version",
    "Ins": "Ins", "Vol": "Vol",
    "Double-click to edit. Notes C-0..B-7, === is key off; instrument, volume and effect in hexadecimal (effect letters 0-9 then A-Z).":
        "Double-clique pour modifier. Notes C-0..B-7, === coupe la note ; instrument, volume et effet en hexadécimal (lettres d'effet : 0-9 puis A-Z).",
    "That key is outside the C-0..B-7 range at this octave.": "Cette touche sort de C-0..B-7 à cette octave.",
    "Cells copied from a {copied} module cannot be pasted into a {open} module.":
        "Les cellules copiées d'un module {copied} ne se collent pas dans un module {open}.",
    "{format} · {channels} CHANNELS": "{format} · {channels} VOIES",
    "Export XM…": "Exporter le XM…", "Export XM module": "Exporter le module XM", "XM exported: {name}": "XM exporté : {name}",
    "XM: Vol is the volume byte in hex (40 = full), effects run 0-9 then A-Z · key 1 enters key off (===)":
        "XM : Vol est l'octet de volume en hexadécimal (40 = plein), les effets vont de 0-9 puis A-Z · la touche 1 écrit la fin de note (key off, ===)",
    "{size} bytes · mono {bits}-bit · {loop} ({mode}) · panning {panning} · relative note {note:+d} · C-4 preview":
        "{size} octets · mono {bits} bits · {loop} ({mode}) · panoramique {panning} · note relative {note:+d} · aperçu C-4",
    "forward": "aller", "pingpong": "aller-retour",
    "This edits 8-bit MOD samples and is not available on an XM module.":
        "Cette action modifie des samples MOD 8 bits : elle n'est pas disponible dans un module XM.",
    "Levels are measured on 8-bit MOD samples: there is nothing to match in an XM module.":
        "Les niveaux se mesurent sur des samples MOD 8 bits : il n'y a rien à égaliser dans un module XM.",
    "Piano keys play the current instrument · Ctrl+E: Edit mode · Ctrl+C/X/V: blocks · Alt+arrows: move · Double-click: edit":
        "Les touches de piano jouent l'instrument courant · Ctrl+E : mode saisie · Ctrl+C/X/V : blocs · Alt+flèches : déplacer · Double-clic : éditer",
    "Keyboard shortcuts of the grid": "Raccourcis clavier de la grille",
    "Piano keys": "Touches de piano", "Double-click": "Double-clic", "Row number": "Numéro de ligne",
    "Del": "Suppr", "Space": "Espace", "Alt+arrows": "Alt+flèches",
    "Play the current instrument; in Edit mode they enter notes":
        "Jouent l'instrument courant ; en mode saisie, elles écrivent les notes",
    "Edit mode: hex digits also fill Smp and Effect": "Mode saisie : les chiffres hexadécimaux remplissent aussi Smp et Effet",
    "Copy, cut and paste a block of cells (as grid text)": "Copier, couper et coller un bloc de cellules (en texte de grille)",
    "Clear the selected cells": "Effacer les cellules sélectionnées",
    "Move the selected block (drag it too; Ctrl copies)": "Déplacer le bloc sélectionné (ou le glisser ; Ctrl copie)",
    "Transpose the selection (Shift: an octave)": "Transposer la sélection (Maj : une octave)",
    "Edit a cell": "Éditer une cellule", "Click to seek there": "Cliquer pour y placer l'écoute",
    "Play / pause": "Lecture / pause",
    "Ctrl+wheel": "Ctrl+molette",
    "Widen or narrow the track columns, to see more or fewer channels":
        "Élargir ou resserrer les colonnes des voies, pour en voir plus ou moins à la fois",
    "Ctrl+click Mute / Solo": "Ctrl+clic Voie / Solo",
    "Make every track audible again (clears all mutes and solos)":
        "Réentendre toutes les voies (annule toutes les coupures et tous les solos)",
    "Ctrl+click: every track audible again": "Ctrl+clic : toutes les voies de nouveau audibles",
    "Every track is audible again": "Toutes les voies sont de nouveau audibles",
    "Takes the agent saves appear here.": "Les versions de l'agent apparaissent ici.",
    "Takes the agent saves appear here. Open one to work from it, or compare it with the current song.":
        "Les versions enregistrées par l'agent apparaissent ici. Ouvre-en une pour partir de celle-ci, ou compare-la au morceau courant.",
    "MOD and XM tracker.\nDouble-click a cell to edit it, or turn on Edit mode (Ctrl+E) and play notes on the keyboard.\nPiano keys: lower row = base octave, upper row = the next one; F1-F3 or numpad +/- change the octave. In Smp and Effect columns type hexadecimal digits.\nThe piano keys also play what they type: the current instrument with Edit mode off, the selected sound in Song samples, Sample library, Create and Instruments. Space still plays and pauses.\nCtrl+C / X / V: copy, cut, paste cells (as grid text) · Del: clear · Alt+arrows: move the block · Ctrl+Up/Down: transpose (Shift: octave).\nThe file reloads by itself when the agent saves it; F5 forces a reload.\nClick a track header to mute or unmute it, Ctrl+click Mute or Solo to hear every track again; the grid scrolls sideways when the channels do not fit and Ctrl+wheel widens or narrows the tracks.\nAn XM adds a volume column and key off (key 1, the key before 2, in Edit mode; === in a cell).\nSpace in patterns: play/pause · Ctrl+Z: undo.\nReal-time playback uses libxmp (ProTracker mode) while exports use libopenmpt, so small differences in sound are expected.\nFour-channel ProTracker MOD, MOD with 2 to 32 channels and the FastTracker II XM profile; IT is planned.":
        "Tracker MOD et XM.\nDouble-clique une cellule pour l'éditer, ou active le mode saisie (Ctrl+E) et joue les notes au clavier.\nTouches de piano : rangée basse = octave de base, rangée haute = l'octave suivante ; F1-F3 ou pavé numérique +/- changent l'octave. Dans les colonnes Smp et Effet, tape des chiffres hexadécimaux.\nLes touches de piano jouent aussi ce qu'elles écrivent : l'instrument courant quand le mode saisie est désactivé, le son choisi dans Samples du morceau, Bibliothèque, Créer et Instruments. Espace lance toujours la lecture et la pause.\nCtrl+C / X / V : copier, couper, coller des cellules (en texte de grille) · Suppr : effacer · Alt+flèches : déplacer le bloc · Ctrl+Haut/Bas : transposer (Maj : octave).\nLe fichier se recharge tout seul quand l'agent l'enregistre ; F5 force un rechargement.\nClique sur l'en-tête d'une voie pour la couper ou la réactiver, Ctrl+clic sur Voie ou Solo pour réentendre toutes les voies ; la grille défile sur le côté quand les voies ne tiennent pas et Ctrl+molette élargit ou resserre les voies.\nUn XM ajoute une colonne de volume et la fin de note (touche 1, celle d'avant le 2, en mode saisie ; === dans une cellule).\nEspace dans les patterns : lecture/pause · Ctrl+Z : annuler.\nLa lecture en temps réel utilise libxmp (mode ProTracker) et les exports utilisent libopenmpt : de petites différences de son sont normales.\nMOD ProTracker à quatre voies, MOD de 2 à 32 voies et profil XM de FastTracker II ; IT est prévu.",
}


def translate(language: str, source: str, **values) -> str:
    text = FR.get(source, source) if language == "fr" else source
    return text.format(**values) if values else text


# Core/decoder diagnostics keep their original text in the CLI. Localize common
# actionable diagnostics at the UI boundary; external backend details stay verbatim.
ERRORS_EN = {
    "Taille MOD invalide pour le profil v1.": "Invalid MOD size for the v1 profile.",
    "Sélectionne une cellule contenant une note.": "Select a cell containing a note.",
    "La transposition sortirait des notes C-1 à B-3 ; aucune note n'a été modifiée.":
        "Transposition would exceed C-1 to B-3; no notes were changed.",
    "Il faut deux colonnes d'effet libres ou Fxx sur la première ligne pour fixer tempo et vitesse sans effacer d'autres effets.":
        "Two empty or Fxx effect columns are needed on the first row to set tempo and speed without removing other effects.",
    "Un projet éditable doit avoir une extension .json.": "An editable project must use the .json extension.",
    "L'export du module doit avoir une extension .mod.": "A module export must use the .mod extension.",
    "Cet emplacement de sample est vide.": "This sample slot is empty.",
    "FFmpeg avec libopenmpt est requis pour ce moteur de rendu.": "FFmpeg with libopenmpt is required for audio rendering.",
    "FFmpeg est requis pour la copie MP3 optionnelle.": "FFmpeg is required for the optional MP3 copy.",
    "Le rendu a dépassé sa limite de temps et a été interrompu.": "Audio rendering timed out and was stopped.",
    "L'écoute de cette version est limitée aux cycles de 120 secondes ; le module reste consultable et éditable.":
        "Playback is limited to 120-second cycles in this version; the module can still be viewed and edited.",
    "Un effet doit contenir trois chiffres hexadécimaux, par exemple 037 ou C20.":
        "An effect must contain three hexadecimal digits, for example 037 or C20.",
    "Longueur de liste d'ordres MOD invalide.": "Invalid MOD order list length.",
    "Ce MOD utilise un octet restart/tempo hors du profil ProTracker v1.": "This MOD uses a restart/tempo byte outside the ProTracker v1 profile.",
    "Ordres inactifs non nuls : variante MOD non prise en charge sans perte.": "Nonzero inactive orders: this MOD variant cannot be imported without loss.",
    "Ce fichier dépasse les 64 patterns du profil M.K. v1.": "This file exceeds the M.K. v1 profile's 64-pattern limit.",
    "Texte MOD hors ASCII imprimable du profil v1.": "MOD text is not printable ASCII as required by the v1 profile.",
    "Fichier trop grand pour le profil MOD v1.": "File too large for the MOD v1 profile.",
    "Le profil accepte de 1 à 31 emplacements de samples.": "The profile accepts 1 to 31 sample slots.",
    "Le profil M.K. accepte de 1 à 64 patterns.": "The M.K. profile accepts 1 to 64 patterns.",
    "La liste d'ordres doit contenir de 1 à 128 entrées.": "The order list must contain 1 to 128 entries.",
    "Le dernier pattern stocké doit apparaître dans la liste d'ordres.": "The last stored pattern must appear in the order list.",
    "Projet JSON trop grand pour le prototype.": "JSON project too large for this prototype.",
    "Une recette définit son PCM et sa boucle ; ne les duplique pas.": "A recipe defines its PCM and loop; do not specify them twice.",
    "Déroulement trop long pour le prototype (250000 lignes maximum).": "Playback plan too long for this prototype (250000 rows maximum).",
    # Rendering (audio.py) and the CLI around it.
    "Un rendu doit durer plus de zéro et au maximum 120 secondes.":
        "A render must last more than 0 and at most 120 seconds; render a section with --seconds "
        "(and optionally --from-order).",
    "Cet ordre n'est pas atteint pendant le premier cycle de lecture.":
        "This order is not reached during the first playback cycle.",
    "La fréquence de rendu doit être comprise entre 8000 et 96000 Hz.":
        "The render sample rate must be between 8000 and 96000 Hz.",
    "Le rendu principal doit avoir une extension .wav ; utilise l'option MP3 pour une copie d'écoute.":
        "The main render must have a .wav extension; use the MP3 option for a listening copy.",
    "Le rendu audio doit avoir un chemin distinct du module source.":
        "The audio render must have a path distinct from the source module.",
    "libxmp n'est pas prêt. Exécute python tools/setup_reference.py, ou indique --xmp-library.":
        "libxmp is not ready. Run python tools/setup_reference.py, or pass --xmp-library.",
    "L'analyse attend du PCM signé 16 bits.": "The analysis expects signed 16-bit PCM.",
    "Le lecteur a produit un fichier audio vide.": "The player produced an empty audio file.",
    "Le moteur a produit trop peu de données audio.": "The engine produced too little audio data.",
    "La copie d'écoute doit avoir un chemin .mp3 distinct du WAV.":
        "The listening copy must have a .mp3 path distinct from the WAV.",
    "La copie MP3 est limitée à 120 secondes dans le prototype.": "The MP3 copy is limited to 120 seconds.",
    "L'export MP3 a dépassé sa limite de temps.": "The MP3 export timed out.",
    "La sortie doit être distincte du fichier source.": "The output must differ from the source file.",
    "--mp3 et --with-xmp nécessitent les rendus audio ; retire --no-audio.":
        "--mp3 and --with-xmp need the audio renders; remove --no-audio.",
    "L'interface demande PySide6. Exécute python -m pip install -e '.[desktop]' dans un environnement virtuel.":
        "The window needs PySide6. Run python -m pip install -e '.[desktop]' in a virtual environment.",
}

# Messages with a value in the middle: (regular expression, English replacement), applied anywhere in the text.
ERROR_PATTERNS_EN = (
    (re.compile(r"Note inconnue (.+?); utilise C-1 à B-3, dièses sans tiret \(exemples : C-3, G#3, A#2 ; "
                r"notation ProTracker\)\."),
     r"Unknown note \1; use C-1 to B-3, sharps without a dash (examples: C-3, G#3, A#2; ProTracker notation)."),
    (re.compile(r"Note inconnue (\S+)"), r"Unknown note \1"),
    (re.compile(r"Le début de l'extrait dépasse la limite de prélecture de (\d+) secondes\."),
     r"The excerpt starts after the \1-second preroll limit; choose an earlier --from-order."),
    (re.compile(r"Moteur audio inconnu : (.+?)\.$"), r"Unknown audio engine: \1."),
    (re.compile(r"^Processus libxmp \(code (-?\d+)\) : "), r"libxmp process (code \1): "),
    (re.compile(r"^FFmpeg/libopenmpt : "), "FFmpeg/libopenmpt: "),
    (re.compile(r"^Export MP3 : "), "MP3 export: "),
    (re.compile(r"Un contrôle a échoué : consulte (.+)\.$"), r"A check failed: see \1."),
)

ERROR_FRAGMENTS_EN = {
    "Titre MOD": "MOD title", "En-tête du sample ": "Sample header ",
    "MOD tronqué ou données supplémentaires : ": "Truncated MOD or extra data: ",
    " octets attendus, ": " bytes expected, ", " reçus.": " received.",
    "Schéma attendu : ": "Expected schema: ", ", profil : ": ", profile: ",
    " entier attendu dans ": " expected integer in ", " texte attendu.": " expected text.",
    " caractères maximum (aucune troncature implicite).": " characters maximum (no implicit truncation).",
    " longueur paire, de 4 à 65534 octets, ou sample vide.": " even length from 4 to 65534 bytes, or an empty sample.",
    " valeurs PCM signées 8 bits attendues (-128 à 127).": " expected signed 8-bit PCM (-128 to 127).",
    " les points de boucle doivent être alignés sur deux octets.": " loop points must be aligned to two bytes.",
    " boucle trop courte ou en dehors du sample.": " loop too short or outside the sample.",
    " un son sans boucle doit commencer par deux octets nuls.": " a non-looping sample must begin with two zero bytes.",
    " hors des 36 notes du profil.": " outside the profile's 36 notes.",
    " non pris en charge par le profil v1.": " not supported by the v1 profile.",
    " hors du profil ProTracker v1.": " outside the ProTracker v1 profile.",
    " hors du profil v1.": " outside the v1 profile.",
    " seul E00/E01 est accepté pour le filtre.": " the filter only accepts E00/E01.",
    " volume Cxx supérieur à 40 hexadécimal.": " Cxx volume exceeds hexadecimal 40.",
    " Bxx pointe en dehors de la liste d'ordres.": " Bxx points outside the order list.",
    " Dxx attend une ligne décimale codée BCD de 00 à 63.": " Dxx expects a BCD row from 00 to 63.",
    " F00 et F20 ont un comportement ambigu et sont exclus.": " F00 and F20 are ambiguous and excluded.",
    " objet JSON attendu.": " expected a JSON object.", " champs inconnus ": " unknown fields ",
    " tableau de 1 à 31 emplacements attendu.": " expected an array of 1 to 31 slots.",
    " tableau de 1 à 64 patterns attendu.": " expected an array of 1 to 64 patterns.",
    " tableau attendu.": " expected an array.", " liste PCM manquante ou trop longue.": " missing or oversized PCM list.",
    " liste d'événements invalide (256 maximum).": " invalid event list (256 maximum).",
    " nom textuel attendu.": " expected a text name.", " cellule ": " cell ", " définie deux fois.": " defined twice.",
    ", ligne ": ", row ", ", voie ": ", channel ", ": période ": ": period ", ": effet ": ": effect ",
    " période:": " period:", " paramètre:": " parameter:",
}


def error_text(language: str, error: object) -> str:
    text = str(error)
    if language == "fr":
        return text
    if "utilise du texte ASCII imprimable" in text:
        return "Use printable ASCII characters for MOD titles and sample names."
    text = ERRORS_EN.get(text, text)
    for pattern, replacement in ERROR_PATTERNS_EN:
        text = pattern.sub(replacement, text)
    for source, target in ERROR_FRAGMENTS_EN.items():
        text = text.replace(source, target)
    return text
