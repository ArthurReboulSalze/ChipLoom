"""Desktop strings. English is the source language; the musical data is never translated."""

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
    "MOD and JSON projects\nDrop a file here to open it.\nF5 reloads changes made by the agent.":
        "MOD et projets JSON\nDépose un fichier ici pour l'ouvrir.\nF5 recharge les changements de l'agent.",
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
    "Modules and projects (*.mod *.MOD *.json);;All files (*)": "Modules et projets (*.mod *.MOD *.json);;Tous les fichiers (*)",
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
    "Edit mode (Ctrl+E): piano keys enter notes, hex digits fill Smp and Effect · Ctrl+C/X/V: blocks · Alt+arrows: move block · Ctrl+↑/↓: transpose · Double-click: edit a cell · Click a row number: seek":
        "Mode saisie (Ctrl+E) : les touches de piano écrivent les notes, les chiffres hexadécimaux remplissent Smp et Effet · Ctrl+C/X/V : blocs · Alt+flèches : déplacer le bloc · Ctrl+↑/↓ : transposer · Double-clic : éditer une cellule · Clic sur un numéro de ligne : déplacer l'écoute",
    "Four-channel MOD tracker.\nDouble-click a cell to edit it, or turn on Edit mode (Ctrl+E) and play notes on the keyboard.\nPiano keys: lower row = base octave, upper row = the next one; F1-F3 or numpad +/- change the octave. In Smp and Effect columns type hexadecimal digits.\nCtrl+C / X / V: copy, cut, paste cells (as grid text) · Del: clear · Alt+arrows: move the block · Ctrl+Up/Down: transpose (Shift: octave).\nThe file reloads by itself when the agent saves it; F5 forces a reload.\nClick a track header to mute or unmute it.\nSpace in patterns: play/pause · Ctrl+Z: undo.\nReal-time playback uses libxmp (ProTracker mode) while exports use libopenmpt, so small differences in sound are expected.\nProTracker M.K. profile; XM and IT are planned.":
        "Tracker MOD à quatre voies.\nDouble-clique une cellule pour l'éditer, ou active le mode saisie (Ctrl+E) et joue les notes au clavier.\nTouches de piano : rangée basse = octave de base, rangée haute = l'octave suivante ; F1-F3 ou pavé numérique +/- changent l'octave. Dans les colonnes Smp et Effet, tape des chiffres hexadécimaux.\nCtrl+C / X / V : copier, couper, coller des cellules (en texte de grille) · Suppr : effacer · Alt+flèches : déplacer le bloc · Ctrl+Haut/Bas : transposer (Maj : octave).\nLe fichier se recharge tout seul quand l'agent l'enregistre ; F5 force un rechargement.\nClique sur l'en-tête d'une voie pour la couper ou la réactiver.\nEspace dans les patterns : lecture/pause · Ctrl+Z : annuler.\nLa lecture en temps réel utilise libxmp (mode ProTracker) et les exports utilisent libopenmpt : de petites différences de son sont normales.\nProfil ProTracker M.K. ; XM et IT sont prévus.",
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
    "Seuls les MOD M.K. à 4 voies sont acceptés dans ce prototype.": "This prototype accepts only four-channel M.K. MOD files.",
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
}

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
    ", ligne ": ", row ", ", voie ": ", track ", ": période ": ": period ", ": effet ": ": effect ",
}


def error_text(language: str, error: object) -> str:
    text = str(error)
    if language == "fr":
        return text
    if text.startswith("Note inconnue "):
        return "Unknown note; use C-1 to B-3 (ProTracker notation)."
    if "utilise du texte ASCII imprimable" in text:
        return "Use printable ASCII characters for MOD titles and sample names."
    text = ERRORS_EN.get(text, text)
    for source, target in ERROR_FRAGMENTS_EN.items():
        text = text.replace(source, target)
    return text
