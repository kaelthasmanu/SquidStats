// Confirm Modal Component Logic
let confirmCallback = null;

function showCustomConfirm(message, callback) {
    document.getElementById('confirmMessage').innerHTML = message;
    confirmCallback = callback;
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