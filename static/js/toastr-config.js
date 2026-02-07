// ===== GLOBAL TOASTR CONFIGURATION =====
// This file configures the behavior of toastr notifications throughout the application

// Configure toastr as soon as jQuery is available
(function() {
  function initToastr() {
    // Check that jQuery and toastr are available
    if (typeof $ === 'undefined' || typeof toastr === 'undefined') {
      console.warn('jQuery or toastr are not available yet');
      return false;
    }

    // Toastr configuration
    toastr.options = {
      closeButton: true,
      debug: false,
      newestOnTop: false, // false = new notifications appear BELOW
      progressBar: true,
      positionClass: "toast-top-right",
      preventDuplicates: false,
      onclick: null,
      showDuration: 300,
      hideDuration: 1000,
      timeOut: 5000, // 5 seconds
      extendedTimeOut: 1000,
      showEasing: "swing",
      hideEasing: "linear",
      showMethod: "fadeIn",
      hideMethod: "fadeOut",
      tapToDismiss: true
    };
    return true;
  }

  // Try to configure immediately
  if (initToastr()) {
    return; // Already configured
  }

  // If it doesn't work, wait for DOMContentLoaded
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function() {
      setTimeout(initToastr, 100);
    });
  } else {
    setTimeout(initToastr, 100);
  }

  // Also try on window.load just in case
  window.addEventListener('load', function() {
    setTimeout(initToastr, 100);
  });
})();
