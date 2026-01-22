// Config & utilidades auditoría (sin cambios funcionales)
(function(){
  function toggleDetails(header) {
    const details = header.nextElementSibling;
    const icon = header.querySelector('.toggle-icon');
    if (details.style.display === 'block') {
      details.style.display = 'none';
      icon && icon.classList.remove('rotate-180');
    } else {
      details.style.display = 'block';
      icon && icon.classList.add('rotate-180');
    }
  }

  function getLocalDateString(){
    const today = new Date();
    const year = today.getFullYear();
    const month = String(today.getMonth() + 1).padStart(2, '0');
    const day = String(today.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  }

  function formatBytes(bytes, decimals = 2) {
    if (!+bytes) return '0 Bytes';
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(dm))} ${sizes[i]}`;
  }

  function formatTime(datetimeString){
    if (!datetimeString || typeof datetimeString !== 'string') return '--';
    try {
      const parts = datetimeString.split(' ');
      if (parts.length < 5) return '--';
      const timePart = parts[4];
      const [hoursStr, minutesStr, secondsStr] = timePart.split(':');
      let hour = parseInt(hoursStr, 10);
      if (isNaN(hour)) return '--';
      const ampm = hour >= 12 ? 'PM' : 'AM';
      hour = hour % 12;
      hour = hour || 12;
      const formattedHour = String(hour).padStart(2, '0');
      return `${formattedHour}:${minutesStr}:${secondsStr} ${ampm}`;
    } catch(e){
      console.error('Error crítico al formatear la hora:', e, 'Input was:', datetimeString);
      return '--';
    }
  }

  // Exponer
  window.toggleDetails = toggleDetails;
  window.getLocalDateString = getLocalDateString;
  window.formatBytes = formatBytes;
  window.formatTime = formatTime;
})();
