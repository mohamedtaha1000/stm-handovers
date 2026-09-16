/*
 * One explanation mechanism for the whole app.
 *
 * Anything carrying data-tip explains itself on hover AND on keyboard
 * focus. The title attribute does hover only, waits about a second
 * before saying anything, cannot be styled and is invisible to anyone
 * tabbing through - which rules it out, because half the point is that
 * a button explains itself before it is pressed.
 *
 * One delegated listener and one bubble, reused by every element on
 * every page: adding an explanation anywhere is writing data-tip on it
 * and nothing else. The text is set with textContent, never innerHTML,
 * because some of it is built from what people typed.
 */
(function () {
  var tip = null, holder = null, timer = null;
  var GAP = 9;      /* between the bubble and what it explains */
  var EDGE = 8;     /* and between the bubble and the window */

  function bubble() {
    if (tip) return tip;
    tip = document.createElement('div');
    tip.className = 'tip';
    tip.id = 'app-tip';
    tip.setAttribute('role', 'tooltip');
    tip.hidden = true;
    document.body.appendChild(tip);
    return tip;
  }

  /* Measured while invisible, so it never appears at its old position
     first and jumps. Fixed positioning, so the numbers are the same
     ones getBoundingClientRect gives. */
  function place(el) {
    var t = bubble();
    t.style.visibility = 'hidden';
    t.hidden = false;
    var box = el.getBoundingClientRect();
    var wide = t.offsetWidth, tall = t.offsetHeight;
    var left = box.left + box.width / 2 - wide / 2;
    left = Math.max(EDGE, Math.min(left, window.innerWidth - wide - EDGE));
    var top = box.top - tall - GAP;
    var below = top < EDGE;          /* no room above: go under instead */
    if (below) top = box.bottom + GAP;
    t.classList.toggle('below', below);
    t.style.left = Math.round(left) + 'px';
    t.style.top = Math.round(top) + 'px';
    t.style.setProperty('--arrow',
      Math.round(Math.min(Math.max(box.left + box.width / 2 - left, 14), wide - 14)) + 'px');
    t.style.visibility = 'visible';
  }

  function show(el, now) {
    var text = el.getAttribute('data-tip');
    if (!text) return;
    hide();
    holder = el;
    var t = bubble();
    t.textContent = text;
    /* So a screen reader reads the explanation as part of the control
       rather than as a stray paragraph somewhere else on the page. */
    el.setAttribute('aria-describedby', t.id);
    clearTimeout(timer);
    /* A pause on hover so passing the mouse over a row of buttons does
       not flash three bubbles; none on focus, where it was asked for. */
    timer = setTimeout(function () { if (holder === el) place(el); }, now ? 0 : 160);
  }

  function hide() {
    clearTimeout(timer);
    if (holder) holder.removeAttribute('aria-describedby');
    holder = null;
    if (tip) tip.hidden = true;
  }

  function owner(node) {
    return node && node.closest ? node.closest('[data-tip]') : null;
  }

  document.addEventListener('mouseover', function (e) {
    var el = owner(e.target);
    if (el && el !== holder) show(el, false);
  });
  document.addEventListener('mouseout', function (e) {
    if (holder && !holder.contains(e.relatedTarget)) hide();
  });
  document.addEventListener('focusin', function (e) {
    var el = owner(e.target);
    if (el) show(el, true);
  });
  document.addEventListener('focusout', hide);
  /* Anything that moves the page moves the bubble away from what it
     points at, and Escape is what people press to dismiss things. */
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') hide(); });
  window.addEventListener('scroll', hide, true);
  window.addEventListener('resize', hide);
  /* A press is an answer in itself - the explanation has done its job. */
  document.addEventListener('click', hide);
})();
