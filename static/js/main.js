/*
 * PTCGL Deck Optimizer - Front-end behaviour
 *   - Debounced (300ms) card search hitting /api/search
 *   - Copy-to-clipboard for export buttons
 *   - Live label update for the iteration input
 */
(function () {
  'use strict';

  // ---------------------------------------------------------------
  // Card search with 300ms debounce
  // ---------------------------------------------------------------
  var searchInput = document.getElementById('card-search');
  var resultsList = document.getElementById('search-results');

  if (searchInput && resultsList) {
    var debounceTimer = null;

    function renderResults(cards) {
      resultsList.innerHTML = '';
      if (!cards || cards.length === 0) {
        var empty = document.createElement('li');
        empty.className = 'muted';
        empty.textContent = 'No matches.';
        resultsList.appendChild(empty);
        return;
      }
      cards.forEach(function (card) {
        var li = document.createElement('li');
        var name = card.name || '(unnamed)';
        var type = card.type || '';
        var hp = card.hp ? (' ' + card.hp + ' HP') : '';
        li.textContent = name + ' - ' + type + hp;
        li.dataset.name = name;
        li.dataset.slug = card._slug || '';
        resultsList.appendChild(li);
      });
    }

    searchInput.addEventListener('keyup', function () {
      var query = searchInput.value;
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(function () {
        var q = query.trim();
        if (!q) {
          resultsList.innerHTML = '';
          return;
        }
        fetch('/api/search', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ query: q })
        })
          .then(function (r) {
            return r.json();
          })
          .then(function (cards) {
            renderResults(cards);
          })
          .catch(function () {
            resultsList.innerHTML = '';
            var err = document.createElement('li');
            err.className = 'muted';
            err.textContent = 'Search failed.';
            resultsList.appendChild(err);
          });
      }, 300);
    });
  }

  // ---------------------------------------------------------------
  // Copy-to-clipboard for export buttons
  // ---------------------------------------------------------------
  document.querySelectorAll('.copy-btn').forEach(function (btn) {
    btn.addEventListener('click', function (ev) {
      ev.preventDefault();
      var text = '';
      var targetSel = btn.getAttribute('data-copy-target');
      if (targetSel) {
        var el = document.querySelector(targetSel);
        if (el) text = el.textContent || '';
      }
      if (!text) {
        var pre = btn.parentElement
          ? btn.parentElement.querySelector('pre')
          : null;
        if (pre) text = pre.textContent || '';
      }

      var original = btn.textContent;
      function flashCopied() {
        btn.textContent = 'Copied!';
        setTimeout(function () {
          btn.textContent = original;
        }, 2000);
      }

      if (
        navigator.clipboard &&
        typeof navigator.clipboard.writeText === 'function'
      ) {
        navigator.clipboard.writeText(text).then(flashCopied, fallback);
      } else {
        fallback();
      }

      function fallback() {
        try {
          var ta = document.createElement('textarea');
          ta.value = text;
          ta.setAttribute('readonly', '');
          ta.style.position = 'absolute';
          ta.style.left = '-9999px';
          document.body.appendChild(ta);
          ta.select();
          document.execCommand('copy');
          document.body.removeChild(ta);
          flashCopied();
        } catch (e) {
          btn.textContent = 'Copy failed';
          setTimeout(function () {
            btn.textContent = original;
          }, 2000);
        }
      }
    });
  });

  // ---------------------------------------------------------------
  // Iteration input live label
  // ---------------------------------------------------------------
  var iterInput = document.getElementById('iterations');
  var iterLabel = document.getElementById('iterations-label');
  if (iterInput && iterLabel) {
    iterInput.addEventListener('input', function () {
      iterLabel.textContent = iterInput.value;
    });
  }
})();
