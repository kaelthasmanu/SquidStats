// Form submit & results rendering (sin cambios funcionales)
(function(){
  let els = {};
  const i18n = window.__AUD_I18N__ || {};
  const defaultResultsHTML = `<div class="bg-white p-6 rounded-lg shadow-lg min-h-[300px] flex items-center justify-center"><div class="text-center text-gray-500 py-10"><i class="fas fa-clipboard-list text-5xl mb-4 text-gray-300"></i><h3 class="text-xl font-semibold">${i18n.selectFilters || 'Seleccione los filtros y genere un reporte'}</h3><p class="mt-2">${i18n.resultsAppear || 'Los resultados de su auditoría aparecerán aquí.'}</p></div></div>`;

  function cacheDom(){
    els.form = document.getElementById('audit-form');
    els.resultsContainer = document.getElementById('audit-results-container');
    els.auditTypeSelect = document.getElementById('audit-type');
    els.usernameSelect = document.getElementById('username-filter');
    els.startDateInput = document.getElementById('start-date');
    els.endDateInput = document.getElementById('end-date');
    els.socialMediaChipsContainer = document.getElementById('social-media-chips');
  }

  function restoreSubmitButton(){
    const submitButton = els.form.querySelector('button[type="submit"]');
    const buttonIcon = submitButton.querySelector('i');
    submitButton.disabled = false;
    submitButton.classList.remove('opacity-50','cursor-not-allowed');
    submitButton.classList.add('hover:bg-blue-700','hover:shadow-xl');
    buttonIcon.className = 'fas fa-play mr-2';
    submitButton.innerHTML = `<i class="fas fa-play mr-2"></i>${i18n.generateReport || 'Generar Reporte'}`;
  }

  function collectFormData(){
    const formData = new FormData(els.form);
    const data = Object.fromEntries(formData.entries());
    const selectedChips = els.socialMediaChipsContainer.querySelectorAll('.social-chip.selected');
    data.social_media_sites = Array.from(selectedChips).map(c=>c.dataset.value);
    return data;
  }

  function validateRequired(data){
    const selectedOption = els.auditTypeSelect.options[els.auditTypeSelect.selectedIndex];
    const requiredInputs = (selectedOption.dataset.requires||'').split(',').filter(Boolean);
    if (requiredInputs.includes('user') && !els.usernameSelect.value){ toastr.error(i18n.selectUser || 'Por favor, seleccione un usuario.', i18n.requiredField || 'Campo requerido'); return false; }
    if (requiredInputs.includes('keyword') && !data.keyword){ toastr.error(i18n.enterKeyword || 'Por favor, ingrese una palabra clave.', i18n.requiredField || 'Campo requerido'); return false; }
    if (requiredInputs.includes('ip') && !data.ip_address){ toastr.error(i18n.enterIp || 'Por favor, ingrese una dirección IP.', i18n.requiredField || 'Campo requerido'); return false; }
    if (requiredInputs.includes('response_code') && !data.response_code){ toastr.error(i18n.selectResponseCode || 'Por favor, seleccione un código de respuesta.', i18n.requiredField || 'Campo requerido'); return false; }
    if (requiredInputs.includes('social_media') && data.social_media_sites.length===0){ toastr.error(i18n.selectSocialMedia || 'Por favor, seleccione al menos una red social.', i18n.requiredField || 'Campo requerido'); return false; }
    return true;
  }

  function buildAuditDownloadUrl(data){
    const query = new URLSearchParams();
    query.set('audit_type', data.audit_type || 'top_users_data');
    if (data.start_date) query.set('start_date', data.start_date);
    if (data.end_date) query.set('end_date', data.end_date);
    if (data.username) query.set('username', data.username);
    if (data.keyword) query.set('keyword', data.keyword);
    if (data.ip_address) query.set('ip_address', data.ip_address);
    if (data.response_code) query.set('response_code', data.response_code);

    if (Array.isArray(data.social_media_sites)) {
      query.set('social_media_sites', data.social_media_sites.join(','));
    } else if (data.social_media_sites) {
      query.set('social_media_sites', data.social_media_sites);
    }

    return `/auditoria/download/pdf?${query.toString()}`;
  }

  function renderResults(auditType, data, formData){
    let html='';
      if (!window.__AUD_RENDERERS__) {
        console.error('[AUDITORIA] __AUD_RENDERERS__ no disponible');
        html = `<div class="bg-white p-6 rounded-lg shadow-lg text-red-600">${i18n.internalError || 'Error interno: Renderers no cargados.'}</div>`;
      } else if (data.error){
      html = `<div class="bg-white p-6 rounded-lg shadow-lg"><div class="text-center text-red-500 py-10"><strong>Error:</strong> ${data.error}</div></div>`;
    } else {
      if (auditType === 'user_summary') html = window.__AUD_RENDERERS__.renderUserSummary(data);
      else if (auditType === 'top_users_data') html = window.__AUD_RENDERERS__.renderTopUsers(data);
      else if (auditType === 'top_urls_data') html = window.__AUD_RENDERERS__.renderTopUrls(data);
  else if (auditType === 'top_users_requests') html = window.__AUD_RENDERERS__.renderTopUsersRequests(data);
  else if (auditType === 'top_ips_data') html = window.__AUD_RENDERERS__.renderTopIpsData(data);
      else if (auditType === 'total_data_consumed') html = window.__AUD_RENDERERS__.renderTotalDataConsumed(data, formData);
      else if (auditType === 'daily_activity') {
        const user = formData.username;
        const date = formData.start_date;
        const title = (i18n.distributionTitle || 'Distribución de Peticiones para {user} el {date}')
            .replace('{user}', `'${user}'`).replace('{date}', date);
        if (data.total_requests>0){
          html = `<div class="bg-white p-6 rounded-lg shadow-lg"><h2 class="text-2xl font-bold mb-2">${title}</h2><p class="text-gray-600 mb-4">${i18n.totalRequestsDay || 'Total de Peticiones en el día:'} <span class="font-bold text-blue-600">${data.total_requests.toLocaleString()}</span></p><canvas id="daily-activity-chart"></canvas></div>`;
        } else {
          html = `<div class="bg-white p-6 rounded-lg shadow-lg"><h2 class="text-2xl font-bold mb-4">${title}</h2><p class="text-gray-500">${i18n.noRequestsFound || 'No se encontraron peticiones para la fecha y usuario seleccionado.'}</p></div>`;
        }
      } else if (['keyword_search','ip_activity','response_code_search','social_media_activity'].includes(auditType)){
        let title='';
        const all = i18n.all || 'Todos';
        if (auditType==='keyword_search'){ const user=formData.username||all; title = (i18n.keywordTitle || 'Resultados para la palabra clave {keyword} para: {user}').replace('{keyword}', formData.keyword).replace('{user}', user); }
        else if (auditType==='ip_activity'){ title = (i18n.ipTitle || 'Resultados de Búsqueda para la IP: {ip}').replace('{ip}', formData.ip_address); }
        else if (auditType==='response_code_search'){ const user=formData.username||all; title = (i18n.responseCodeTitle || 'Resultados por Código de Respuesta {code} para: {user}').replace('{code}', formData.response_code).replace('{user}', user); }
        else if (auditType==='social_media_activity'){ const user=formData.username||all; const sites=formData.social_media_sites.join(', '); title = (i18n.socialMediaTitle || 'Actividad en Redes Sociales ({sites}) para: {user}').replace('{sites}', sites).replace('{user}', user); }
        html = window.__AUD_RENDERERS__.renderNestedAccordionResults(title, data.results);
      } else {
        html = `<div class="bg-white p-6 rounded-lg shadow-lg"><p>${i18n.unknownReportType || 'Tipo de reporte no reconocido.'}</p></div>`;
      }
    }
    els.resultsContainer.innerHTML = html;
    if (window.__AUD_RENDERERS__) {
      const dailyActivityChartCanvas = document.getElementById('daily-activity-chart');
      if (dailyActivityChartCanvas && data.hourly_activity){
        try { window.__AUD_RENDERERS__.renderDailyActivityChart(dailyActivityChartCanvas, data.hourly_activity); }
        catch(e){ console.error('[AUDITORIA] Error renderDailyActivityChart', e); }
      }
      const domainChartCanvas = document.getElementById('domain-chart');
      if (domainChartCanvas && data.top_domains){
        try { window.__AUD_RENDERERS__.renderDomainChart(domainChartCanvas, data.top_domains); }
        catch(e){ console.error('[AUDITORIA] Error renderDomainChart', e); }
      }
      const responseChartCanvas = document.getElementById('response-chart');
      if (responseChartCanvas && data.response_summary){
        try { window.__AUD_RENDERERS__.renderResponseChart(responseChartCanvas, data.response_summary); }
        catch(e){ console.error('[AUDITORIA] Error renderResponseChart', e); }
      }
    }
  }

  function bindForm(){
    els.form.addEventListener('submit', e=>{
      e.preventDefault();
      const data = collectFormData();
      if (!validateRequired(data)) return;
      const submitButton = els.form.querySelector('button[type="submit"]');
      const buttonIcon = submitButton.querySelector('i');
      submitButton.disabled = true;
      submitButton.classList.add('opacity-50','cursor-not-allowed');
      submitButton.classList.remove('hover:bg-blue-700','hover:shadow-xl');
      buttonIcon.className = 'fas fa-spinner fa-spin mr-2';
      submitButton.innerHTML = `<i class="fas fa-spinner fa-spin mr-2"></i>${i18n.generating || 'Generando Reporte...'}`;
      els.resultsContainer.innerHTML = `<div class="bg-white p-6 rounded-lg shadow-lg min-h-[300px] flex items-center justify-center"><div class="text-center text-gray-500 py-10"><i class="fas fa-spinner fa-spin text-5xl mb-4 text-blue-500"></i><h3 class="text-xl font-semibold">${i18n.generating || 'Generando reporte...'}</h3></div></div>`;
      const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');
      fetch('/api/run-audit', { 
        method:'POST', 
        headers:{
          'Content-Type':'application/json',
          'X-CSRFToken': csrfToken
        }, 
        body: JSON.stringify(data) 
      })
        .then(r=>r.json())
        .then(result=>{
          toastr.clear(); restoreSubmitButton();
          if (result.error) { toastr.error(result.error, i18n.auditError || 'Error en la auditoría'); }
          else { toastr.success(i18n.reportGenerated || 'Reporte generado exitosamente', i18n.auditCompleted || 'Auditoría completada'); }
          renderResults(data.audit_type, result, data);
        })
        .catch(err=>{
          toastr.clear(); restoreSubmitButton();
          toastr.error(i18n.connectionError || 'Error de conexión con el servidor', i18n.networkError || 'Error de red');
          els.resultsContainer.innerHTML = `<div class=\"bg-white p-6 rounded-lg shadow-lg\"><div class=\"text-center text-red-500 py-10\"><strong>${i18n.networkServerError || 'Error de red o del servidor:'}</strong> ${err}</div></div>`;
        });
    });
  }

  function bindSocialChips(){
    els.socialMediaChipsContainer.addEventListener('click', e=>{ if (e.target.classList.contains('social-chip')) e.target.classList.toggle('selected'); });
  }

  function bindDownloadButton(){
    const downloadBtn = document.getElementById('audit-export-pdf');
    if (!downloadBtn) return;
    downloadBtn.addEventListener('click', ()=>{
      const data = collectFormData();
      if (!validateRequired(data)) return;
      const url = buildAuditDownloadUrl(data);
      window.open(url, '_blank');
    });
  }

  function initFormAndResults(){
    cacheDom();
    els.resultsContainer.innerHTML = defaultResultsHTML;
    bindForm();
    bindSocialChips();
    bindDownloadButton();
  }

  window.__AUD_FORM__ = { initFormAndResults, defaultResultsHTML };
})();
