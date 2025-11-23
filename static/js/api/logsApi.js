// Capa de acceso a datos para logs/usuarios

export async function fetchUsersPageApi(selectedDate, page, search) {
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');
  const resp = await fetch("/get-logs-by-date", {
    method: "POST",
    headers: { 
      "Content-Type": "application/json",
      "X-CSRFToken": csrfToken
    },
  body: JSON.stringify({ date: selectedDate, page, search }),
  });
  const data = await resp.json();
  return data;
}
