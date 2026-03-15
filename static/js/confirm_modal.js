// Confirm Modal Component Logic
let confirmCallback = null;

function showCustomConfirm(message, callback, options = {}) {
    const msgEl = document.getElementById('confirmMessage');
    msgEl.replaceChildren();
    if (message instanceof Node) {
        msgEl.appendChild(message);
    } else {
        msgEl.textContent = message;
    }
    confirmCallback = callback;
    // Polimorfismo visual: solo botón cerrar
    const cancelBtn = document.getElementById('confirmCancelBtn');
    const confirmBtn = document.getElementById('confirmConfirmBtn');
    if (options.onlyClose) {
        cancelBtn.classList.add('hidden');
        confirmBtn.textContent = 'Cerrar';
        confirmBtn.classList.remove('bg-red-500', 'hover:bg-red-600');
        confirmBtn.classList.add('bg-blue-500', 'hover:bg-blue-600');
    } else {
        cancelBtn.classList.remove('hidden');
        confirmBtn.textContent = 'Confirmar';
        confirmBtn.classList.remove('bg-blue-500', 'hover:bg-blue-600');
        confirmBtn.classList.add('bg-red-500', 'hover:bg-red-600');
    }
    document.getElementById('confirmModal').classList.remove('hidden');
}

function hideConfirmModal() {
    document.getElementById('confirmModal').classList.add('hidden');
}

function executeConfirmCallback() {
    if (confirmCallback) {
        confirmCallback();
        confirmCallback = null;
    }
    hideConfirmModal();
}

// Close modal on Escape key
document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !document.getElementById('confirmModal').classList.contains('hidden')) {
        hideConfirmModal();
    }
});