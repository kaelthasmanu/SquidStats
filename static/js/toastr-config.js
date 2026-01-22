// ===== CONFIGURACIÓN GLOBAL DE TOASTR =====
// Este archivo configura el comportamiento de las notificaciones toastr en toda la aplicación

// Configurar toastr tan pronto como jQuery esté disponible
(function() {
  function initToastr() {
    // Verificar que jQuery y toastr estén disponibles
    if (typeof $ === 'undefined' || typeof toastr === 'undefined') {
      console.warn('jQuery o toastr no están disponibles aún');
      return false;
    }

    // Configuración de toastr
    toastr.options = {
      closeButton: true,
      debug: false,
      newestOnTop: false, // false = las nuevas notificaciones aparecen DEBAJO
      progressBar: true,
      positionClass: "toast-top-right",
      preventDuplicates: false,
      onclick: null,
      showDuration: 300,
      hideDuration: 1000,
      timeOut: 5000, // 5 segundos
      extendedTimeOut: 1000,
      showEasing: "swing",
      hideEasing: "linear",
      showMethod: "fadeIn",
      hideMethod: "fadeOut",
      tapToDismiss: true
    };

    console.log('✅ Toastr configurado correctamente');
    return true;
  }

  // Intentar configurar inmediatamente
  if (initToastr()) {
    return; // Ya está configurado
  }

  // Si no funciona, esperar al DOMContentLoaded
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function() {
      setTimeout(initToastr, 100);
    });
  } else {
    setTimeout(initToastr, 100);
  }

  // También intentar en window.load por si acaso
  window.addEventListener('load', function() {
    setTimeout(initToastr, 100);
  });
})();
