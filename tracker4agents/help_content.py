"""The ChipLoom help: short topic cards, in English and French, shown by the window's help (desktop_help).

Each topic is a few (gesture, what it does) pairs that can be read in under a minute. The text lives here, apart from
Qt, so the window and the documentation can share it and a test can check that both languages say the same number of
things. Keep every line short; details belong in docs/USER_GUIDE.md.
"""
from __future__ import annotations

# (id, icon, {lang: title}, [{lang: (gesture, explanation)}])
TOPICS = [
    ("start", "spark", {"en": "Getting started", "fr": "Démarrer"}, [
        {"en": ("Open a song", "File > Open, or drop a MOD, XM or project anywhere on the window."),
         "fr": ("Ouvrir un morceau", "Fichier > Ouvrir, ou dépose un MOD, un XM ou un projet n'importe où sur la fenêtre.")},
        {"en": ("Play", "Space plays and pauses; click a row number to jump there."),
         "fr": ("Écouter", "Espace lance et met en pause ; clique un numéro de ligne pour y aller.")},
        {"en": ("Save and export", "Ctrl+S saves the editable project; File > Export writes the real MOD or XM and an "
                "audio copy."),
         "fr": ("Enregistrer et exporter", "Ctrl+S enregistre le projet modifiable ; Fichier > Exporter écrit le vrai "
                "MOD ou XM et une copie audio.")},
        {"en": ("Start a new song", "File > New, then choose Library or Synthesized in the header."),
         "fr": ("Nouveau morceau", "Fichier > Nouveau, puis choisis Bibliothèque ou Synthé dans l'en-tête.")},
    ]),
    ("notes", "keys", {"en": "Writing notes", "fr": "Écrire des notes"}, [
        {"en": ("Ctrl+E", "Edit mode: the piano keys enter notes. Lower row = base octave, upper row = the next; "
                "F1-F3 change the octave."),
         "fr": ("Ctrl+E", "Mode saisie : les touches de piano écrivent des notes. Rangée basse = octave de base, "
                "rangée haute = la suivante ; F1-F3 changent l'octave.")},
        {"en": ("Hex digits", "Fill the sample, volume (XM) and effect columns; double-click edits a cell."),
         "fr": ("Chiffres hexadécimaux", "Remplissent les colonnes sample, volume (XM) et effet ; double-clic pour "
                "éditer une cellule.")},
        {"en": ("Blocks", "Select, then Ctrl+C / X / V; Alt+arrows move; Ctrl+Up/Down transpose (Shift: octave); "
                "Del clears."),
         "fr": ("Blocs", "Sélectionne, puis Ctrl+C / X / V ; Alt+flèches déplacent ; Ctrl+Haut/Bas transposent "
                "(Maj : octave) ; Suppr efface.")},
        {"en": ("Ctrl+Z", "Undo anything, your edits and the agent's."),
         "fr": ("Ctrl+Z", "Annule tout, tes modifications comme celles de l'agent.")},
    ]),
    ("bank", "bank", {"en": "Samples and bank", "fr": "Samples et banque"}, [
        {"en": ("Click a sample", "It plays at once (Auto-play). The piano keys play the selected sample at any note."),
         "fr": ("Clique un sample", "Il se joue aussitôt (lecture automatique). Les touches de piano jouent le "
                "sample choisi à n'importe quelle note.")},
        {"en": ("Bank menu", "Open or create a bank, build the starter bank (62 sounds in tune), reopen a recent one. "
                "Your agent uses the same bank."),
         "fr": ("Menu Banque", "Ouvre ou crée une banque, construis la banque de départ (62 sons accordés), rouvre une "
                "banque récente. Ton agent utilise la même.")},
        {"en": ("Add to bank", "Right-click a song sample; or drop a MOD/XM on the bank tab and tick the samples you "
                "want; or drop a WAV. Give it a name and a role."),
         "fr": ("Ajouter à la banque", "Clic droit sur un sample du morceau ; ou dépose un MOD/XM sur l'onglet banque "
                "et coche les samples voulus ; ou dépose un WAV. Donne-lui un nom et un rôle.")},
        {"en": ("Use a bank sample", "Drag it onto a slot of Song samples, or select it and press Add to song."),
         "fr": ("Utiliser un sample", "Glisse-le sur un emplacement de Samples du morceau, ou sélectionne-le et "
                "clique Ajouter au morceau.")},
        {"en": ("Palettes", "Sets of samples that go together: listen to them, then Use in song."),
         "fr": ("Palettes", "Des ensembles de samples qui vont ensemble : écoute-les, puis Utiliser dans le morceau.")},
    ]),
    ("tuning", "wave", {"en": "Tuning", "fr": "Accordage"}, [
        {"en": ("Tuning page", "Shows what a sample plays when C is written, measured (e.g. D# +45 cents)."),
         "fr": ("Page Accordage", "Montre ce que joue un sample quand on écrit Do, mesuré (par ex. Ré# +45 cents).")},
        {"en": ("Retune", "XM: -1/+1 semitone, -12/+12 (octave) and fine tune. MOD: fine tune, or move this sample's "
                "notes."),
         "fr": ("Réaccorder", "XM : -1/+1 demi-ton, -12/+12 (octave) et accord fin. MOD : accord fin, ou déplacer les "
                "notes de ce sample.")},
        {"en": ("Save tuning to bank", "The correction is kept in the bank and applied each time you use the sample."),
         "fr": ("Garder dans la banque", "La correction est gardée dans la banque et appliquée à chaque utilisation.")},
        {"en": ("Parts clash?", "Compare the written-C line of each sample first: samples from different songs are "
                "often tuned differently."),
         "fr": ("Ça sonne faux ?", "Compare d'abord la ligne « Do écrit » de chaque sample : des samples de morceaux "
                "différents sont souvent accordés différemment.")},
    ]),
    ("mode", "spark", {"en": "Library or Synthesized", "fr": "Bibliothèque ou Synthé"}, [
        {"en": ("Header switch", "Library: samples from the bank only. Synthesized: sounds made by ChipLoom recipes "
                "only (Create tab). Mixed: both, after a confirmation."),
         "fr": ("Interrupteur de l'en-tête", "Bibliothèque : uniquement des samples de la banque. Synthé : uniquement "
                "des sons créés par les recettes ChipLoom (onglet Créer). Mixte : les deux, après confirmation.")},
        {"en": ("Refused?", "A mode the song breaks is refused, and the message says which slots stand in the way."),
         "fr": ("Refusé ?", "Un mode que le morceau ne respecte pas est refusé, et le message dit quels emplacements "
                "posent problème.")},
    ]),
    ("agent", "bubble", {"en": "Working with your agent", "fr": "Travailler avec ton agent"}, [
        {"en": ("Live collaboration", "Agent menu: turn it on. Your agent finds this window and edits the song with "
                "you; every change can be undone."),
         "fr": ("Collaboration en direct", "Menu Agent : active-la. Ton agent trouve cette fenêtre et modifie le "
                "morceau avec toi ; chaque changement s'annule.")},
        {"en": ("Write to your agent", "Use the box in the Agent tab, or select cells and press Ctrl+M to point at a "
                "place. Its answers appear under your message."),
         "fr": ("Écrire à ton agent", "Utilise la case de l'onglet Agent, ou sélectionne des cellules et appuie sur "
                "Ctrl+M pour montrer un endroit. Ses réponses apparaissent sous ton message.")},
        {"en": ("Proposals and takes", "Preview and listen to a proposal, then Accept or Reject; open a take or compare "
                "it with the song (Ctrl+B)."),
         "fr": ("Propositions et versions", "Prévisualise et écoute une proposition, puis Accepte ou Refuse ; ouvre "
                "une version ou compare-la avec le morceau (Ctrl+B).")},
        {"en": ("What did it do?", "The line at the top of the Agent tab shows its latest action."),
         "fr": ("Qu'a-t-il fait ?", "La ligne en haut de l'onglet Agent montre sa dernière action.")},
    ]),
]


def topics(language: str = "en") -> list[dict]:
    """The topics in one language: id, icon, title and items [(gesture, explanation)]."""
    lang = language if language in ("en", "fr") else "en"
    return [{"id": topic_id, "icon": icon, "title": titles[lang], "items": [item[lang] for item in items]}
            for topic_id, icon, titles, items in TOPICS]


def search(query: str, language: str = "en") -> list[dict]:
    """Topics with only the items matching every word of `query` (title matches keep the whole topic)."""
    words = [word for word in query.lower().split() if word]
    if not words:
        return topics(language)
    found = []
    for topic in topics(language):
        if all(word in topic["title"].lower() for word in words):
            found.append(topic)
            continue
        items = [item for item in topic["items"] if all(word in (item[0] + " " + item[1]).lower() for word in words)]
        if items:
            found.append({**topic, "items": items})
    return found
