// Render functions (sin cambios funcionales)
(function(){
  function renderNestedAccordionResults(title, results) {
    if (!results || results.length === 0) {
      return `<div class="bg-white p-6 rounded-lg shadow-lg"><h2 class="text-2xl font-bold mb-4">${title}</h2><p class="text-gray-500">No se encontraron registros.</p></div>`;
    }
    const usersData = {};
    results.forEach((item) => {
      if (!usersData[item.username]) usersData[item.username] = {};
      const dateStr = `${item.log_date.substring(0,4)}-${item.log_date.substring(4,6)}-${item.log_date.substring(6,8)}`;
      if (!usersData[item.username][dateStr]) {
        usersData[item.username][dateStr] = { daily_requests: 0, daily_data: 0, activities: [] };
      }
      const dateGroup = usersData[item.username][dateStr];
      dateGroup.activities.push(item);
      dateGroup.daily_requests += Number(item.access_count) || 0;
      dateGroup.daily_data += Number(item.total_data) || 0;
    });
    let html = `<h2 class="text-2xl font-bold mb-4">${title}</h2>`;
    for (const username in usersData) {
      const userDataByDate = usersData[username];
      html += `<div class="border rounded-lg mb-3 shadow-md bg-white"><div class="bg-gray-100 p-3 flex justify-between items-center cursor-pointer hover:bg-gray-200" onclick="toggleDetails(this)"><h3 class="font-bold text-gray-800 flex items-center"><i class="fas fa-user mr-3 text-blue-600"></i>${username}</h3><i class="fas fa-chevron-down toggle-icon transition-transform"></i></div><div class="user-card-details border-t border-gray-200" style="display: none;">`;
      const sortedDates = Object.keys(userDataByDate).sort().reverse();
      for (const date of sortedDates) {
        const dateData = userDataByDate[date];
        html += `<div class="border-b last:border-b-0"><div class="bg-blue-50 p-2 pl-6 flex justify-between items-center cursor-pointer hover:bg-blue-100" onclick="toggleDetails(this)"><h4 class="font-semibold text-blue-800"><i class="fas fa-calendar-alt mr-2"></i>${date}</h4><div class="flex items-center space-x-4 text-sm"><span class="font-medium text-blue-700"><i class="fas fa-hashtag mr-1"></i>${dateData.daily_requests.toLocaleString()} Peticiones</span><span class="font-medium text-green-700"><i class="fas fa-database mr-1"></i>${formatBytes(dateData.daily_data)}</span><i class="fas fa-chevron-down toggle-icon transition-transform text-xs"></i></div></div><div class="date-details p-3" style="display: none;"><table class="w-full text-left text-sm mt-2"><thead class="border-b-2 border-gray-300"><tr><th class="py-1 px-2 text-center">Hora (Últ. Acceso)</th><th class="py-1 px-2">URL</th><th class="py-1 px-2 text-center">Intentos</th><th class="py-1 px-2">Datos</th></tr></thead><tbody class="divide-y divide-gray-100">`;
        const ensureProtocol = (url) => (url.startsWith('http') ? url : `http://${url}`);
        dateData.activities.forEach((activity) => {
          html += `<tr class="hover:bg-gray-50"><td class="py-1 px-2 text-center font-mono text-xs">${formatTime(activity.last_seen)}</td><td class="py-1 px-2 truncate"><a href="${ensureProtocol(activity.url)}" target="_blank" class="text-blue-600 hover:underline" title="${activity.url}">${activity.url}</a></td><td class="py-1 px-2 text-center">${activity.access_count}</td><td class="py-1 px-2">${formatBytes(activity.total_data)}</td></tr>`;
        });
        html += `</tbody></table></div></div>`;
      }
      html += `</div></div>`;
    }
    return html;
  }

  function renderUserSummary(data) {
    const topDomainsHtml = data.top_domains.map(d => `<li>${d.domain} <span class="font-bold">(${d.count} reqs)</span></li>`).join('');
    const responseSummaryHtml = data.response_summary.slice(0,5).map(r => `<li>${r.code}: <span class="font-bold">${r.count.toLocaleString()}</span></li>`).join('');
    return `<div class="bg-white p-6 rounded-lg shadow-lg"><h2 class="text-2xl font-bold mb-4">Resumen de Actividad</h2><div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6"><div class="bg-blue-100 p-4 rounded-lg text-center"><div class="text-3xl font-bold">${data.total_requests.toLocaleString()}</div><div class="text-sm">Peticiones Totales</div></div><div class="bg-green-100 p-4 rounded-lg text-center"><div class="text-3xl font-bold">${data.total_data_gb}</div><div class="text-sm">GB Consumidos</div></div><div class="bg-gray-100 p-4 rounded-lg"><h4 class="font-semibold text-sm mb-1 text-center">Resumen de Respuestas</h4><ul class="text-xs space-y-1">${responseSummaryHtml}</ul></div></div><div class="grid grid-cols-1 md:grid-cols-2 gap-6"><div><h3 class="text-xl font-semibold mb-2">Top 15 Dominios Visitados</h3><canvas id="domain-chart"></canvas></div><div><h3 class="text-xl font-semibold mb-2">Distribución de Respuestas HTTP</h3><canvas id="response-chart"></canvas></div></div></div>`;
  }

  function renderTopUsers(data){
    const rows = data.top_users.map((user,i)=>`<tr class="hover:bg-gray-50"><td class="p-3">${i+1}</td><td class="p-3 font-medium">${user.username}</td><td class="p-3 font-mono">${user.total_data_gb.toFixed(2)} GB</td></tr>`).join('');
    return `<div class="bg-white p-6 rounded-lg shadow-lg"><h2 class="text-2xl font-bold mb-4">Top 10 Usuarios por Consumo de Datos</h2><table class="w-full text-left"><thead class="bg-gray-100"><tr><th class="p-3">#</th><th class="p-3">Usuario</th><th class="p-3">Datos Consumidos</th></tr></thead><tbody class="divide-y">${rows}</tbody></table></div>`;
  }

  function renderTopUrls(data){
    const rows = data.top_urls.map((url,i)=>`<tr class="hover:bg-gray-50"><td class="p-3">${i+1}</td><td class="p-3 font-medium"><a href="${url.url.startsWith('http')?url.url:'http://'+url.url}" target="_blank" class="text-blue-600 hover:underline break-all" title="${url.url}">${url.url.length>60?url.url.substring(0,60)+'...':url.url}</a></td><td class="p-3 font-mono">${url.total_data_gb.toFixed(2)} GB</td></tr>`).join('');
    return `<div class="bg-white p-6 rounded-lg shadow-lg"><h2 class="text-2xl font-bold mb-4">Top 15 URLs por Consumo de Datos</h2><table class="w-full text-left"><thead class="bg-gray-100"><tr><th class="p-3">#</th><th class="p-3">URL</th><th class="p-3">Datos Consumidos</th></tr></thead><tbody class="divide-y">${rows}</tbody></table></div>`;
  }

  function renderTopUsersRequests(data){
    const rows = data.top_users_requests.map((user,i)=>`<tr class="hover:bg-gray-50"><td class="p-3">${i+1}</td><td class="p-3 font-medium">${user.username}</td><td class="p-3 font-mono">${user.total_requests.toLocaleString()}</td></tr>`).join('');
    return `<div class="bg-white p-6 rounded-lg shadow-lg"><h2 class="text-2xl font-bold mb-4">Top 10 Usuarios por Peticiones</h2><table class="w-full text-left"><thead class="bg-gray-100"><tr><th class="p-3">#</th><th class="p-3">Usuario</th><th class="p-3">Peticiones</th></tr></thead><tbody class="divide-y">${rows}</tbody></table></div>`;
  }

  function renderTopIpsData(data){
    const rows = data.top_ips.map((ip,i)=>`<tr class="hover:bg-gray-50"><td class="p-3">${i+1}</td><td class="p-3 font-mono">${ip.ip}</td><td class="p-3 font-mono">${ip.total_data_gb.toFixed(2)} GB</td></tr>`).join('');
    return `<div class="bg-white p-6 rounded-lg shadow-lg"><h2 class="text-2xl font-bold mb-4">Top 10 IPs por Consumo de Datos</h2><table class="w-full text-left"><thead class="bg-gray-100"><tr><th class="p-3">#</th><th class="p-3">IP</th><th class="p-3">Datos Consumidos</th></tr></thead><tbody class="divide-y">${rows}</tbody></table></div>`;
  }

  function renderDailyActivityChart(canvas, hourlyData){
    const labels = Array.from({length:24},(_,i)=>{ const hour = i % 12 === 0 ? 12 : i % 12; const ampm = i < 12 ? 'AM' : 'PM'; return `${hour} ${ampm}`; });
    new Chart(canvas, {
      type:'bar',
      data:{
        labels,
        datasets:[{
          label:'Peticiones por Hora',
          data:hourlyData,
          backgroundColor:'rgba(59, 130, 246, 0.5)',
          borderColor:'rgba(37, 99, 235, 1)',
          borderWidth:1
        }]
      },
      options:{
        responsive:true,
        scales:{
          x:{ grid:{display:false}, title:{display:true,text:'Hora del Día'} },
          y:{ beginAtZero:true, title:{display:true,text:'Número de Peticiones'} }
        },
        plugins:{ legend:{ display:false } }
      }
    });
  }

  function renderDomainChart(canvas, domains){
    const generateColors = (count)=>Array.from({length:count},(_,i)=>`hsl(${((i*360)/count)%360},70%,50%)`);
    const config = {
      type:'pie',
      data:{
        labels:domains.map(d=>d.domain),
        datasets:[{
          label:'Requests',
          data:domains.map(d=>d.count),
          backgroundColor:generateColors(domains.length)
        }]
      },
      options:{
        responsive:true,
        plugins:{
          legend:{
            position:'right',
            labels:{
              boxWidth:12,
              font:{size:10},
              generateLabels:(chart)=>{
                const {labels,datasets}=chart.data;
                if(!labels.length||!datasets.length) return [];
                return labels.map((label,i)=>({
                  text:`${label} (${datasets[0].data[i]})`,
                  fillStyle:datasets[0].backgroundColor[i],
                  strokeStyle:datasets[0].backgroundColor[i],
                  lineWidth:0,
                  index:i
                }));
              }
            }
          },
          tooltip:{
            callbacks:{
              label:(context)=>{
                const label=context.label||'';
                const value=context.raw||0;
                const total=context.dataset.data.reduce((a,b)=>a+b,0);
                const percentage=Math.round((value/total)*100);
                return `${label}: ${value} (${percentage}%)`;
              }
            }
          }
        }
      }
    };
    return new Chart(canvas, config);
  }

  function renderResponseChart(canvas,responses){
    const getResponseColor = (code)=>{ if(code>=500) return '#DC2626'; if(code>=400) return '#F59E0B'; if(code>=300) return '#3B82F6'; if(code>=200) return '#10B981'; return '#6B7280'; };
    const config = {
      type:'pie',
      data:{
        labels:responses.map(r=>`HTTP ${r.code}`),
        datasets:[{
          label:'Respuestas',
            data:responses.map(r=>r.count),
            backgroundColor:responses.map(r=>getResponseColor(r.code)),
            borderWidth:1
        }]
      },
      options:{
        responsive:true,
        maintainAspectRatio:true,
        plugins:{
          legend:{
            position:'right',
            labels:{
              font:{size:12},
              padding:10,
              usePointStyle:true,
              pointStyle:'circle'
            }
          },
          tooltip:{
            callbacks:{
              label:(context)=>{
                const label=context.label.replace('HTTP ','')||'';
                const value=context.raw||0;
                const total=context.dataset.data.reduce((a,b)=>a+b,0);
                const percentage=Math.round((value/total)*100);
                return `${label}: ${value} (${percentage}%)`;
              }
            }
          }
        }
      }
    };
    return new Chart(canvas, config);
  }

  window.__AUD_RENDERERS__ = {
    renderNestedAccordionResults,
    renderUserSummary,
    renderTopUsers,
    renderTopUrls,
  renderTopUsersRequests,
  renderTopIpsData,
    renderDailyActivityChart,
    renderDomainChart,
    renderResponseChart
  };
  console.log('[AUDITORIA] Renderers cargados:', Object.keys(window.__AUD_RENDERERS__));
})();
