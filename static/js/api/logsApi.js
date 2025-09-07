// Capa de acceso a datos para logs/usuarios

export async function fetchUsersPageApi(selectedDate, page, search) {
  const resp = await fetch("/get-logs-by-date", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ date: selectedDate, page, search }),
  });
  const data = await resp.json();
  return data;
}
