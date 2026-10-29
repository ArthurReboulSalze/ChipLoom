# Compose with the owner through a live session

A live session is the song the owner has open in the ChipLoom window (or a headless
`chiploom live serve SONG.json`). Your edits appear in the window immediately and can be
undone there. A journal records who changed what. The server listens on localhost only and
needs a token that `live` reads from the discovery file under `CHIPLOOM_HOME` (default
`%LOCALAPPDATA%\ChipLoom`, or `~/.local/state/chiploom`); you never handle the token.

All commands are `python -m tracker4agents live <command>`; add `--session PID_OR_URL` if
`live sessions` shows several.

The owner may also have the song open in a browser (the studio, no code needed). Its edits are
journaled as `human-web` and count as the owner's. `live web` prints the studio address and
`live web --status` lists the connected browsers; you never need either to compose.

## Procedure

1. **Discover.** `live sessions` (empty means no session: use the ordinary file workflow).
   `live status` returns `revision`, `path`, `title`, `window` (true when a window is
   attached), `pending_proposals` and, from a window, the owner's cursor and selection.
2. **Read.** `live score` (overview), `live score --pattern N [--row R --rows K]` (grid
   lines), `live changes --since 0` (what the owner and any agent did). Remember the
   `revision` you read.
3. **Patch small, with a base.**
   `live patch --base REV --label "Fill before chorus" --op '{...}'` (same operations as
   `patch`; see patch.md). The result has the new `revision`, `diff` and `summary`.
   Keep the returned revision for your next patch. Without `--base` no conflict check
   runs: always pass it when the owner may be editing.
4. **Handle `LIVE_CONFLICT`.** Exit 2 and nothing applied. The JSON on stderr has
   `conflicts` (each: `unit`, `author`, `revision`, `label`, and for cells `pattern`,
   `row`, `channel`, `current`, `yours`) and the current `revision`. The owner's edit
   wins: read `live changes --since REV`, keep what they did, adapt or drop your part,
   resubmit with the new revision. Edits that touch other cells are not conflicts.
5. **Propose big changes.** For a rewrite of a part ("redo the bass", "new drums"),
   `live patch --propose --label "..." --ops FILE` (do not give `--base`). The song is
   unchanged until the owner previews and accepts it in the window; you cannot accept it
   and you cannot act as `human`. `live proposals` shows status and `stale` (others
   edited the same cells since); `live withdraw ID` retracts it. After a rejection, ask
   what they want instead of resubmitting the same thing.
6. **Announce versions.** Write an alternative with `patch` to its own file, then
   `live take FILE --label "Brighter lead"`. The owner opens it from the window; `live
   takes` lists them. `live open --take t1` asks the window to open one.
   With unsaved changes in the window the reply is `handled: "pending"` (the owner is being
   asked to save or discard): do not resend. Read `pending_request` in `live status` and the
   `kind: "request"` entry in `live changes` (`outcome`: `opened`, `declined`, `failed`).
7. **Show and play.** `live select --pattern N --row R --channel C [--rows K --channels K]`
   points at a passage; `live play [--order N]` and `live stop` drive playback and fail
   with `LIVE_NO_WINDOW` on a headless session. `open` and `select` without a window
   return `handled: false`.
8. **Save.** `live save` writes the session's own project file. `live save --output PATH`
   writes a copy (`"copy": true`); the session and the owner's window keep their file.

## Comments from the owner

The owner can attach a comment to a block in the window or the browser studio. Read them
with `live comments` (or the `kind: "comment"` entries of `live changes`): `place` gives the
pattern, rows and channels (null: the whole song), `cells` the block as it was when written.
Work where it points, then `live resolve ID --text "what I changed"`; ask with
`live reply ID TEXT` first when the remark is unclear. Never resolve a comment you did not
address. Your own comments (`live comment TEXT --pattern ...`) can point the owner at a
passage to listen to.

## Syncing a regenerated song

When a script rewrites the whole project while the window is open, send it with
`live sync PROJECT.json` (`--dry-run` first). It plans the differences, simulates them with
the session's checks, then sends samples, structure and one patch per changed pattern, each
with the revision it read as base: a newer owner edit stops it with `LIVE_CONFLICT` and the
error lists what was applied. Read `verified` and `not_synced` (non-recipe PCM, XM envelopes,
metadata), and reload the file with `live open` only for those.

## Rules of thumb

- The owner's edits win; never repeat a refused patch unchanged.
- Give each agent its own `--author` name (letters, digits, space, `_ . -`, at most 32).
  Edits by the same author name never conflict with each other.
- The author `human` is reserved for the window (`LIVE_AUTHOR`).
- Stay out of the region the owner is selecting unless asked.
- Labels (1-80 characters) appear in their undo history and your journal; make them say
  what the edit is for.
- Report what changed from `summary`, and distinguish measurements (`report`) from your
  musical judgment.

## Headless practice

```sh
CHIPLOOM_HOME=/tmp/chiploom python -m tracker4agents live serve exports/song/project.json &
# prints {"ok": true, "event": "listening", "pid": ..., "url": ...}
python -m tracker4agents live status
```

Ctrl+C or killing that one `pid` stops it; unsaved edits are not written, so `live save`
first. Never kill other ChipLoom processes.

## Errors you may meet

`LIVE_NOT_RUNNING` (no session answers), `LIVE_CONFLICT`, `LIVE_BASE` (a `--base` that is
not an integer between 0 and the current revision), `LIVE_PROPOSAL` (unknown, closed or
empty proposal), `LIVE_NO_WINDOW`, `LIVE_AUTHOR`, `LIVE_LABEL`, `LIVE_TAKE` (a take is an
existing `.json` or `.mod`), plus the `PATCH_*` and score codes from patch.md. The full
list is in `docs/CLI.md`.
