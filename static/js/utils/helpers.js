// Utilidades compartidas para formateo y helpers de UI

export function getComputedTailwindColor(className) {
  const colorMap = {
    "text-blue-500": "#3B82F6",
    "text-green-500": "#22C55E",
    "text-yellow-500": "#EAB308",
    "text-red-500": "#EF4444",
    "text-orange-400": "#FB923C",
    "text-gray-500": "#6B7280",
  };
  return colorMap[className] || "#6B7280";
}

export function truncate(str, n) {
  return str.length > n ? str.slice(0, n - 1) + "..." : str;
}

export function formatBytes(bytes) {
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex++;
  }
  return `${value.toFixed(2)} ${units[unitIndex]}`;
}
