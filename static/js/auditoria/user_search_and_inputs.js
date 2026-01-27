// User search & conditional inputs (sin cambios funcionales)
(function(){
  const conditionalInputs = {};
  let allUsers = [];
  let filteredUsers = [];
  let selectedUserIndex = -1;
  let elements = {};

  function cacheDom(){
    elements.form = document.getElementById('audit-form');
    elements.resultsContainer = document.getElementById('audit-results-container');
    elements.auditTypeSelect = document.getElementById('audit-type');
    elements.usernameSelect = document.getElementById('username-filter');
    elements.startDateInput = document.getElementById('start-date');
    elements.endDateInput = document.getElementById('end-date');
    elements.startDateContainer = document.getElementById('start-date-container');
    elements.endDateContainer = document.getElementById('end-date-container');
    elements.userSearchInput = document.getElementById('user-search-input');
    elements.userDropdown = document.getElementById('user-dropdown');
    elements.userOptionsContainer = document.getElementById('user-options-container');
    conditionalInputs.user = document.getElementById('user-filter-container');
    conditionalInputs.user_optional = document.getElementById('user-filter-container');
    conditionalInputs.keyword = document.getElementById('keyword-input-container');
    conditionalInputs.ip = document.getElementById('ip-input-container');
    conditionalInputs.response_code = document.getElementById('response-code-input-container');
    conditionalInputs.social_media = document.getElementById('social-media-input-container');
  }

  function initDates(){
    const todayString = window.getLocalDateString();
    elements.startDateInput.value = todayString;
    elements.endDateInput.value = todayString;
  }

  function renderUserOptions(users, searchTerm=''){
    elements.userOptionsContainer.innerHTML = '';
    if (!searchTerm){
      const allOption = document.createElement('div');
      allOption.className = 'px-3 py-2 hover:bg-blue-50 dark:hover:bg-slate-700 cursor-pointer text-gray-700 dark:text-gray-300 border-b border-gray-100 dark:border-slate-600';
      allOption.textContent = '-- Todos --';
      allOption.dataset.value = '';
      allOption.addEventListener('click', ()=>selectUser('', '-- Todos --'));
      elements.userOptionsContainer.appendChild(allOption);
    }
    users.forEach((user,index)=>{
      const option = document.createElement('div');
      option.className = 'px-3 py-2 hover:bg-blue-50 dark:hover:bg-slate-700 cursor-pointer text-gray-700 dark:text-gray-300';
      option.textContent = user;
      option.dataset.value = user;
      option.dataset.index = index;
      option.addEventListener('click', ()=>selectUser(user, user));
      if (searchTerm){
        const regex = new RegExp(`(${searchTerm})`, 'gi');
        option.innerHTML = user.replace(regex, '<mark class="bg-yellow-200 dark:bg-yellow-600 dark:text-gray-900">$1</mark>');
      }
      elements.userOptionsContainer.appendChild(option);
    });
    if (users.length===0 && searchTerm){
      const noResults = document.createElement('div');
      noResults.className = 'px-3 py-2 text-gray-500 dark:text-gray-400 italic';
      noResults.textContent = 'No se encontraron usuarios';
      elements.userOptionsContainer.appendChild(noResults);
    }
  }

  function selectUser(value, displayText){
    elements.userSearchInput.value = displayText;
    elements.usernameSelect.value = value;
    elements.userDropdown.classList.add('hidden');
    selectedUserIndex = -1;
  }

  function filterUsers(term){
    if (!term) filteredUsers = [...allUsers];
    else filteredUsers = allUsers.filter(u=>u.toLowerCase().includes(term.toLowerCase()));
    renderUserOptions(filteredUsers, term);
  }

  function updateSelectedOption(options){
    options.forEach((opt,i)=>opt.classList.toggle('bg-blue-100', i===selectedUserIndex));
  }

  function bindUserSearchEvents(){
    const input = elements.userSearchInput;
    input.addEventListener('input', e=>{ filterUsers(e.target.value); elements.userDropdown.classList.remove('hidden'); selectedUserIndex=-1; });
    input.addEventListener('focus', ()=>{ filterUsers(input.value); elements.userDropdown.classList.remove('hidden'); });
    input.addEventListener('keydown', e=>{
      const options = elements.userOptionsContainer.querySelectorAll('[data-value]');
      if (e.key==='ArrowDown'){ e.preventDefault(); selectedUserIndex = Math.min(selectedUserIndex+1, options.length-1); updateSelectedOption(options);} 
      else if (e.key==='ArrowUp'){ e.preventDefault(); selectedUserIndex = Math.max(selectedUserIndex-1, -1); updateSelectedOption(options);} 
      else if (e.key==='Enter'){ e.preventDefault(); if (selectedUserIndex>=0 && options[selectedUserIndex]){ const sel=options[selectedUserIndex]; selectUser(sel.dataset.value, sel.textContent);} } 
      else if (e.key==='Escape'){ elements.userDropdown.classList.add('hidden'); selectedUserIndex=-1; }
    });
    document.addEventListener('click', e=>{ if(!input.contains(e.target) && !elements.userDropdown.contains(e.target)){ elements.userDropdown.classList.add('hidden'); selectedUserIndex=-1; }});
  }

  function fetchUsers(){
    fetch('/api/all-users')
      .then(r=>r.json())
      .then(users=>{
        allUsers = users; filteredUsers=[...users];
        users.forEach(u=>{ const opt=document.createElement('option'); opt.value=u; opt.textContent=u; elements.usernameSelect.appendChild(opt); });
        renderUserOptions(filteredUsers);
      })
      .catch(()=> toastr.error('Error al cargar la lista de usuarios','Error de carga'));
  }

  function toggleConditionalInputs(){
    elements.resultsContainer.innerHTML = window.__AUD_FORM__?.defaultResultsHTML || elements.resultsContainer.innerHTML;
    Object.values(conditionalInputs).forEach(el=>{ if(el) el.style.display='none'; });
    const selectedOption = elements.auditTypeSelect.options[elements.auditTypeSelect.selectedIndex];
    const auditType = selectedOption.value;
    const required = (selectedOption.dataset.requires||'').split(',').filter(Boolean);
    required.forEach(id=>{ if(conditionalInputs[id]) conditionalInputs[id].style.display='block'; });

    if (auditType === 'daily_activity'){
      elements.endDateContainer.style.display='none';
      elements.startDateContainer.querySelector('label').textContent = 'Fecha';
    } else {
      elements.endDateContainer.style.display='block';
      elements.startDateContainer.querySelector('label').textContent = 'Fecha de Inicio';
    }

    if (auditType === 'user_summary' || auditType === 'daily_activity') {
      elements.userSearchInput.placeholder = 'Seleccionar usuario...';
      elements.userSearchInput.value='';
      elements.usernameSelect.value='';
      elements.userSearchInput.disabled=false;
    } else {
      elements.userSearchInput.placeholder = 'Buscar usuario... (Opcional)';
      elements.userSearchInput.value='-- Todos --';
      elements.usernameSelect.value='';
      elements.userSearchInput.disabled=false;
    }
  }

  function initConditionalInputs(){
    elements.auditTypeSelect.addEventListener('change', toggleConditionalInputs);
    toggleConditionalInputs();
  }

  function initUserSearch(){
    bindUserSearchEvents();
    fetchUsers();
  }

  function initUserAndInputs(){
    cacheDom();
    initDates();
    initConditionalInputs();
    initUserSearch();
  }

  window.__AUD_USER_INPUTS__ = { initUserAndInputs };
})();
