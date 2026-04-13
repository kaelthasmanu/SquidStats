// conexiones.js – Actions for the conexiones partial
// Uses event delegation on document so it works after innerHTML replacements.

var _actionUsername = null;
var _actionIp = null;

// ── CSRF ──────────────────────────────────────────────────────
function _getCsrf() {
  var meta = document.querySelector('meta[name="csrf-token"]');
  return meta ? meta.getAttribute('content') : '';
}

// ── Modal helpers ────────────────────────────────────────────
function closeAllModals() {
  ['modal-block', 'modal-unblock', 'modal-throttle', 'modal-unthrottle'].forEach(function(id) {
    var el = document.getElementById(id);
    if (el) el.classList.add('hidden');
  });
}

function _openModal(modalId, subtitleId, username, ip) {
  _actionUsername = username;
  _actionIp = ip;
  var sub = document.getElementById(subtitleId);
  if (sub) sub.textContent = username + ' · ' + ip;
  var modal = document.getElementById(modalId);
  if (modal) modal.classList.remove('hidden');
}

// ── Delay pools loader ────────────────────────────────────────
function loadDelayPools() {
  var select = document.getElementById('throttle-pool-select');
  if (!select) return;
  select.innerHTML = '<option value="">Cargando...</option>';
  fetch('/api/delay-pools')
    .then(function(r) { return r.json(); })
    .then(function(data) {
      var pools = data.pools || [];
      if (pools.length === 0) {
        select.innerHTML = '<option value="">No hay delay pools configurados</option>';
        return;
      }
      select.innerHTML = '';
      pools.forEach(function(pool) {
        var opt = document.createElement('option');
        opt.value = pool.pool_number;
        opt.textContent = 'Pool #' + pool.pool_number + ' — clase ' + (pool.class || '?') + ' · ' + (pool.parameters || '?');
        select.appendChild(opt);
      });
    })
    .catch(function() {
      var s = document.getElementById('throttle-pool-select');
      if (s) s.innerHTML = '<option value="">Error al cargar los pools</option>';
    });
}

// ── API action ────────────────────────────────────────────────
function _apiAction(url, body) {
  fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': _getCsrf()
    },
    body: JSON.stringify(body)
  })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      showToast(
        data.status === 'success',
        data.message || data.error || (data.status === 'success' ? 'Operación exitosa' : 'Error')
      );
    })
    .catch(function() {
      showToast(false, 'Error de conexión con el servidor');
    });
}

// ── Toast ─────────────────────────────────────────────────────
var _toastTimer = null;
function showToast(success, message) {
  var toast = document.getElementById('action-toast');
  var icon  = document.getElementById('action-toast-icon');
  var msg   = document.getElementById('action-toast-message');
  if (!toast || !icon || !msg) return;

  toast.className = toast.className.replace(/bg-\S+|text-\S+/g, '').trim();
  if (success) {
    toast.classList.add('bg-green-50', 'text-green-800', 'border', 'border-green-200');
    icon.className = 'fas fa-circle-check text-green-500 text-lg';
  } else {
    toast.classList.add('bg-red-50', 'text-red-800', 'border', 'border-red-200');
    icon.className = 'fas fa-circle-exclamation text-red-500 text-lg';
  }
  msg.textContent = message;
  toast.classList.remove('hidden');

  if (_toastTimer) clearTimeout(_toastTimer);
  _toastTimer = setTimeout(function() { toast.classList.add('hidden'); }, 4500);
}

// ── Accordion ─────────────────────────────────────────────────
function restoreAccordionState() {
  var accordionState = JSON.parse(localStorage.getItem('accordion-state') || '{}');
  document.querySelectorAll('[data-accordion-content]').forEach(function(content) {
    var user = JSON.parse(content.getAttribute('data-user'));
    var index = content.id.replace('content-', '');
    var icon = document.getElementById('icon-' + index);
    var isOpen = accordionState[user] !== false;
    content.style.display = isOpen ? '' : 'none';
    if (icon) icon.classList[isOpen ? 'add' : 'remove']('rotate-180');
  });
}

function _toggleAccordion(index) {
  var content = document.getElementById('content-' + index);
  var icon    = document.getElementById('icon-' + index);
  if (!content) return;
  var user    = JSON.parse(content.getAttribute('data-user'));
  var opening = content.style.display === 'none';
  content.style.display = opening ? '' : 'none';
  if (icon) icon.classList[opening ? 'add' : 'remove']('rotate-180');
  var state = JSON.parse(localStorage.getItem('accordion-state') || '{}');
  state[user] = opening;
  localStorage.setItem('accordion-state', JSON.stringify(state));
}

// ── Actions menu ──────────────────────────────────────────────
function _closeAllActionsMenus() {
  document.querySelectorAll('[data-actions-menu]').forEach(function(m) {
    m.classList.add('hidden');
  });
}

function _toggleActionsMenu(index) {
  var menu = document.querySelector('[data-actions-menu="' + index + '"]');
  if (!menu) return;
  var wasOpen = !menu.classList.contains('hidden');
  _closeAllActionsMenus();
  if (!wasOpen) menu.classList.remove('hidden');
}

// ── Event delegation (single listener on document) ───────────
document.addEventListener('click', function(e) {
  var target = e.target;

  // 1. Accordion toggle
  var accBtn = target.closest('[data-accordion-btn]');
  if (accBtn) {
    e.stopPropagation();
    _toggleAccordion(accBtn.getAttribute('data-accordion-btn'));
    return;
  }

  // 2. Actions menu toggle button
  var actBtn = target.closest('[data-actions-toggle]');
  if (actBtn) {
    e.stopPropagation();
    _toggleActionsMenu(actBtn.getAttribute('data-actions-toggle'));
    return;
  }

  // 3. Action item inside the menu
  var actionItem = target.closest('[data-action]');
  if (actionItem) {
    var action   = actionItem.getAttribute('data-action');
    var user     = actionItem.getAttribute('data-user');
    var ip       = actionItem.getAttribute('data-ip');
    _closeAllActionsMenus();
    if (action === 'block')       { _openModal('modal-block',       'modal-block-subtitle',       user, ip); }
    if (action === 'unblock')     { _openModal('modal-unblock',     'modal-unblock-subtitle',     user, ip); }
    if (action === 'throttle')    { _openModal('modal-throttle',    'modal-throttle-subtitle',    user, ip); loadDelayPools(); }
    if (action === 'unthrottle')  { _openModal('modal-unthrottle',  'modal-unthrottle-subtitle',  user, ip); }
    return;
  }

  // 4. Modal cancel button
  if (target.closest('[data-modal-cancel]')) {
    closeAllModals();
    return;
  }

  // 5. Modal confirm buttons
  var confirmBtn = target.closest('[data-modal-confirm]');
  if (confirmBtn) {
    var type = confirmBtn.getAttribute('data-modal-confirm');
    closeAllModals();
    if (type === 'block')      { _apiAction('/api/connections/block',      { username: _actionUsername, ip: _actionIp }); }
    if (type === 'unblock')    { _apiAction('/api/connections/unblock',    { username: _actionUsername, ip: _actionIp }); }
    if (type === 'unthrottle') { _apiAction('/api/connections/unthrottle', { username: _actionUsername, ip: _actionIp }); }
    if (type === 'throttle') {
      var sel = document.getElementById('throttle-pool-select');
      var poolNum = sel ? parseInt(sel.value) : NaN;
      if (!poolNum) { showToast(false, 'Selecciona un delay pool válido'); return; }
      _apiAction('/api/connections/throttle', { username: _actionUsername, ip: _actionIp, pool_number: poolNum });
    }
    return;
  }

  // 6. Modal backdrop click
  var modalIds = ['modal-block', 'modal-unblock', 'modal-throttle', 'modal-unthrottle'];
  if (modalIds.includes(target.id)) {
    closeAllModals();
    return;
  }

  // 7. Click outside any open actions menu → close all
  if (!target.closest('[data-actions-menu]') && !target.closest('[data-actions-toggle]')) {
    _closeAllActionsMenus();
  }
});
