/*
 * Any "email someone about this" link, opened as a real Outlook draft.
 *
 * The link itself is a mailto:, and stays one - it is what works
 * without JavaScript, from another machine, and in any other mail
 * client. But a mailto: can only carry plain text, so the details
 * arrive as a list rather than as tables.
 *
 * So the click asks the app first: if it is running next to the Outlook
 * this browser's owner uses, it opens the draft there, tables and all.
 * Anything else - another machine, no pywin32, the new Outlook - and
 * the click falls through to the link it was always going to follow,
 * which is why nothing here breaks when this does not work.
 *
 * Mark a link up with data-draft (where to ask) and data-ids (which
 * documents). Nothing else on the page has to know about any of it.
 */
(function () {
  var links = document.querySelectorAll('[data-draft]');
  if (!links.length) return;

  /* A brief line at the bottom of the window: these buttons sit in
     table rows and on cards with no room for a message beside them. */
  function toast(text, bad) {
    var el = document.createElement('div');
    el.className = 'toast' + (bad ? ' bad' : '');
    el.setAttribute('role', 'status');
    el.textContent = text;
    document.body.appendChild(el);
    /* A confirmation only has to be noticed; a reason has to be read,
       and usually names a setting to go and change. */
    var stay = bad ? 11000 : 3600;
    setTimeout(function () { el.classList.add('going'); }, stay);
    setTimeout(function () { el.remove(); }, stay + 500);
  }

  Array.prototype.forEach.call(links, function (link) {
    link.addEventListener('click', function (e) {
      var href = link.getAttribute('href') || '';
      if (!href || link.dataset.busy) return;
      e.preventDefault();
      link.dataset.busy = '1';

      var body = new URLSearchParams();
      (link.dataset.ids || '').split(',').forEach(function (id) {
        if (id) body.append('id', id);
      });

      fetch(link.dataset.draft, {
        method: 'POST', credentials: 'same-origin', body: body,
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' }
      })
        .then(function (r) { return r.json().catch(function () { return {}; }); })
        .catch(function () { return {}; })
        .then(function (result) {
          delete link.dataset.busy;
          if (result.opened) {
            toast('The draft is open in Outlook, with the details as tables.');
            return;
          }
          /* Couldn't, so do what the link says. One mailto per click is
             the one thing a browser will always honour.
             The reason is shown rather than swallowed: a draft that
             quietly arrives as a plain list instead of tables looks
             like the app ignoring what it was told to do, and there is
             usually one setting standing in the way. */
          if (result.reason) {
            toast('Opened as a plain-text draft instead — ' + result.reason, true);
          }
          window.location.href = href;
        });
    });
  });
})();
