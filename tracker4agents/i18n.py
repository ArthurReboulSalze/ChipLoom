"""Desktop strings. English is the source language; the musical data is never translated."""

LANGUAGES = ("en", "fr")

FR = {
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
    "Double-click: edit a cell · Click a row number: seek · Samples and effects are hexadecimal":
        "Double-clic : éditer · Clic sur un numéro de ligne : déplacer l'écoute · Samples et effets en hexadécimal",
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
    "Four-channel MOD tracker.\nDouble-click a cell to edit it.\nClick a track header to mute or unmute it.\nSpace in patterns: play/pause.\nCtrl+Z: undo · F5: reload file.\nProTracker M.K. profile; XM and IT are planned.":
        "Tracker MOD à quatre voies.\nDouble-clique une cellule pour l'éditer.\nClique sur l'en-tête d'une voie pour la couper ou la réactiver.\nEspace dans les patterns : lecture/pause.\nCtrl+Z : annuler · F5 : recharger le fichier.\nProfil ProTracker M.K. ; XM et IT sont prévus.",
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
