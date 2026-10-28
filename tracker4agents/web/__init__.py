"""The browser studio: joining, the same-origin web API and the static page of a live session.

`access` holds the joined browsers and their web tokens, `render` makes the WAV the page plays, `api` lists
the browser-safe methods, `gateway` turns an HTTP request into one of them. `index.html`,
`app.js` and `style.css` are the page itself (plain JavaScript, no build step, no external
resources). Everything is standard library only; `live.LiveServer` mounts it under `/web/`.
"""
