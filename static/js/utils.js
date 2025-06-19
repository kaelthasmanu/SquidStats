// ======================================================================
// FICHERO: utils.js
// Contiene funciones de utilidad reutilizables en todo el proyecto.
// ======================================================================

/**
 * Agrupa logs por URL para una vista más limpia.
 * @param {Array} logs - Array de logs del usuario.
 * @returns {Array} - Logs agrupados.
 */
function groupLogsByUrl(logs) {
  const groups = {};
  logs.forEach(log => {
    if (!groups[log.url]) {
      groups[log.url] = { url: log.url, responses: {}, total_requests: 0, total_data: 0, entryCount: 0 };
    }
    const group = groups[log.url];
    group.total_requests += log.request_count;
    group.total_data += log.data_transmitted;
    group.entryCount++;
    group.responses[log.response] = (group.responses[log.response] || 0) + 1;
  });

  return Object.values(groups).map(group => {
    let dominantResponse = "0";
    if (Object.keys(group.responses).length > 0) {
        dominantResponse = Object.keys(group.responses).reduce((a, b) => group.responses[a] > group.responses[b] ? a : b);
    }
    return {
      url: group.url,
      response: parseInt(dominantResponse),
      request_count: group.total_requests,
      data_transmitted: group.total_data,
      isGrouped: group.entryCount > 1
    };
  });
}

/**
 * Formatea bytes a una representación legible (KB, MB, GB).
 * @param {number} bytes - Cantidad de bytes.
 * @returns {string} - Representación formateada.
 */
function formatBytes(bytes) {
  if (!bytes || bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${parseFloat((bytes / Math.pow(1024, i)).toFixed(2))} ${units[i]}`;
}

/**
 * Acorta un texto si excede una longitud máxima.
 * @param {string} str - Texto a acortar.
 * @param {number} n - Longitud máxima.
 * @returns {string} - Texto acortado.
 */
function truncate(str, n) {
  if (!str) return '';
  return str.length > n ? str.slice(0, n - 1) + "..." : str;
}

/**
 * Obtiene el valor hexadecimal de un color de Tailwind CSS.
 * @param {string} className - Clase de Tailwind (ej. 'text-blue-500').
 * @returns {string} - Código hexadecimal del color.
 */
function getComputedTailwindColor(className) {
  const colorMap = {
    'text-blue-500': '#3B82F6', 'text-green-500': '#22C55E', 'text-yellow-500': '#EAB308',
    'text-red-500': '#EF4444', 'text-orange-400': '#FB923C', 'text-gray-500': '#6B7280'
  };
  return colorMap[className] || '#6B7280';
}