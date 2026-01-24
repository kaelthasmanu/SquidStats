// ACL Type Information and Examples
const aclTypeInfo = {
    // Network / IP
    'src': {
        description: 'IP de origen del cliente. Puede incluir direcciones IP individuales, rangos CIDR o subredes.',
        example: 'acl localnet src 192.168.1.0/24 10.0.0.0/8',
        icon: 'network-wired',
        color: 'blue',
        slow: false
    },
    'dst': {
        description: 'IP de destino (requiere búsqueda DNS inversa, puede ser lento).',
        example: 'acl servidores dst 10.0.0.5 10.0.0.6',
        icon: 'network-wired',
        color: 'blue',
        slow: true
    },
    'localip': {
        description: 'IP local de la conexión proxy.',
        example: 'acl mipublic localip 203.0.113.45',
        icon: 'network-wired',
        color: 'blue',
        slow: false
    },
    'src_as': {
        description: 'Autonomous System number de origen.',
        example: 'acl mi_as src_as 64512',
        icon: 'network-wired',
        color: 'blue',
        slow: false
    },
    'dst_as': {
        description: 'Autonomous System number de destino.',
        example: 'acl redes_cdn dst_as 16509',
        icon: 'network-wired',
        color: 'blue',
        slow: false
    },
    
    // Domains
    'dstdomain': {
        description: 'Dominio de destino. Soporta comodines con puntos al inicio.',
        example: 'acl sitios_permitidos dstdomain .example.com .google.com',
        icon: 'globe',
        color: 'green',
        slow: false
    },
    'srcdomain': {
        description: 'Dominio de origen del cliente (requiere DNS inverso, lento).',
        example: 'acl red_interna srcdomain .mi-empresa.local',
        icon: 'globe',
        color: 'green',
        slow: true
    },
    'dstdom_regex': {
        description: 'Expresión regular para coincidencia de dominios de destino.',
        example: 'acl redes_sociales dstdom_regex -i (facebook|twitter|instagram)\\.com',
        icon: 'globe',
        color: 'green',
        slow: false
    },
    'srcdom_regex': {
        description: 'Expresión regular para dominios de origen (requiere DNS inverso).',
        example: 'acl externos srcdom_regex -i ^.*\\.external\\.com$',
        icon: 'globe',
        color: 'green',
        slow: true
    },
    
    // Ports
    'port': {
        description: 'Puerto TCP de destino. Puede ser número o rango.',
        example: 'acl Safe_ports port 80 443 8080 21',
        icon: 'plug',
        color: 'cyan',
        slow: false
    },
    'localport': {
        description: 'Puerto local en el que se recibió la conexión.',
        example: 'acl puerto_principal localport 3128',
        icon: 'plug',
        color: 'cyan',
        slow: false
    },
    'myportname': {
        description: 'Nombre del puerto según http_port.',
        example: 'acl transparente myportname proxy_transparente',
        icon: 'plug',
        color: 'cyan',
        slow: false
    },
    
    // Time
    'time': {
        description: 'Día de la semana y hora. Formato: [SMTWHAS][h1:m1-h2:m2]',
        example: 'acl horario_laboral time MTWHF 09:00-18:00',
        icon: 'clock',
        color: 'orange',
        slow: false
    },
    
    // URL
    'url_regex': {
        description: 'Expresión regular que coincide con la URL completa.',
        example: 'acl anuncios url_regex -i \\.gif$ \\.jpg$ banner',
        icon: 'link',
        color: 'indigo',
        slow: false
    },
    'urlpath_regex': {
        description: 'Expresión regular solo para el path de la URL.',
        example: 'acl descarga urlpath_regex -i \\.exe$ \\.zip$ \\.rar$',
        icon: 'link',
        color: 'indigo',
        slow: false
    },
    'urllogin': {
        description: 'Expresión regular para el componente de login de la URL.',
        example: 'acl usuarios_externos urllogin -i ^guest.*',
        icon: 'link',
        color: 'indigo',
        slow: false
    },
    
    // Protocol
    'proto': {
        description: 'Protocolo de la petición (HTTP, FTP, etc.).',
        example: 'acl protocolo_http proto HTTP',
        icon: 'exchange-alt',
        color: 'teal',
        slow: false
    },
    'method': {
        description: 'Método HTTP de la petición.',
        example: 'acl CONNECT method CONNECT',
        icon: 'exchange-alt',
        color: 'teal',
        slow: false
    },
    'http_status': {
        description: 'Código de estado HTTP en la respuesta.',
        example: 'acl errores_server http_status 500 502 503 504',
        icon: 'exchange-alt',
        color: 'teal',
        slow: false
    },
    
    // Authentication
    'proxy_auth': {
        description: 'Usuario autenticado (requiere autenticación configurada).',
        example: 'acl usuarios_premium proxy_auth juan maria pedro',
        icon: 'user-lock',
        color: 'red',
        slow: true
    },
    'proxy_auth_regex': {
        description: 'Expresión regular para nombre de usuario autenticado.',
        example: 'acl admins proxy_auth_regex -i ^admin',
        icon: 'user-lock',
        color: 'red',
        slow: true
    },
    'ext_user': {
        description: 'Usuario provisto por helper externo.',
        example: 'acl usuarios_ldap ext_user juan maria',
        icon: 'user-lock',
        color: 'red',
        slow: true
    },
    'ext_user_regex': {
        description: 'Expresión regular para usuarios de helper externo.',
        example: 'acl grupo_ventas ext_user_regex -i ^ventas_',
        icon: 'user-lock',
        color: 'red',
        slow: true
    },
    
    // Content
    'browser': {
        description: 'Expresión regular para User-Agent del navegador.',
        example: 'acl bots browser -i (bot|crawler|spider)',
        icon: 'file-alt',
        color: 'yellow',
        slow: false
    },
    'referer_regex': {
        description: 'Expresión regular para el header Referer.',
        example: 'acl desde_google referer_regex -i google\\.com',
        icon: 'file-alt',
        color: 'yellow',
        slow: false
    },
    'req_mime_type': {
        description: 'Tipo MIME en el request.',
        example: 'acl upload_imagen req_mime_type image/jpeg image/png',
        icon: 'file-alt',
        color: 'yellow',
        slow: false
    },
    'rep_mime_type': {
        description: 'Tipo MIME en la respuesta.',
        example: 'acl tipo_video rep_mime_type video/mp4 video/mpeg',
        icon: 'file-alt',
        color: 'yellow',
        slow: false
    },
    'req_header': {
        description: 'Header específico del request.',
        example: 'acl api_key req_header X-API-Key',
        icon: 'file-alt',
        color: 'yellow',
        slow: false
    },
    'rep_header': {
        description: 'Header específico de la respuesta.',
        example: 'acl con_cache rep_header Cache-Control',
        icon: 'file-alt',
        color: 'yellow',
        slow: false
    },
    
    // SSL/TLS
    'ssl_error': {
        description: 'Código de error SSL/TLS.',
        example: 'acl ssl_expired ssl_error X509_V_ERR_CERT_HAS_EXPIRED',
        icon: 'lock',
        color: 'emerald',
        slow: false
    },
    'server_cert_fingerprint': {
        description: 'Fingerprint del certificado del servidor.',
        example: 'acl cert_confiable server_cert_fingerprint AA:BB:CC:DD',
        icon: 'lock',
        color: 'emerald',
        slow: false
    },
    'ssl::server_name': {
        description: 'Server Name Indication (SNI) en conexiones TLS.',
        example: 'acl sitio_seguro ssl::server_name .example.com',
        icon: 'lock',
        color: 'emerald',
        slow: false
    },
    'ssl::server_name_regex': {
        description: 'Expresión regular para SNI.',
        example: 'acl bancos ssl::server_name_regex -i banco.*\\.com$',
        icon: 'lock',
        color: 'emerald',
        slow: false
    },
    
    // Connections
    'maxconn': {
        description: 'Límite máximo de conexiones por IP.',
        example: 'acl max_10 maxconn 10',
        icon: 'server',
        color: 'pink',
        slow: false
    },
    'max_user_ip': {
        description: 'Límite máximo de IPs diferentes por usuario.',
        example: 'acl max_3_ips max_user_ip 3',
        icon: 'server',
        color: 'pink',
        slow: false
    },
    
    // Advanced
    'external': {
        description: 'Helper externo personalizado (puede ser muy lento).',
        example: 'acl verificado external checker_script %DST',
        icon: 'cogs',
        color: 'gray',
        slow: true
    },
    'random': {
        description: 'Probabilidad aleatoria (0.0 a 1.0).',
        example: 'acl un_tercio random 0.333',
        icon: 'cogs',
        color: 'gray',
        slow: false
    },
    'note': {
        description: 'Anotación de transacción.',
        example: 'acl tiene_nota note importante',
        icon: 'cogs',
        color: 'gray',
        slow: false
    },
    'any-of': {
        description: 'Grupo de ACLs con lógica OR (coincide si alguna es verdadera).',
        example: 'acl grupo any-of acl1 acl2 acl3',
        icon: 'cogs',
        color: 'gray',
        slow: false
    },
    'all-of': {
        description: 'Grupo de ACLs con lógica AND (coincide si todas son verdaderas).',
        example: 'acl combinado all-of acl1 acl2',
        icon: 'cogs',
        color: 'gray',
        slow: false
    }
};

let addValueCounter = 0;
let editValueCounter = 0;

// Show Add Modal
function showAddModal() {
    document.getElementById('addModal').classList.remove('hidden');
    document.getElementById('addForm').reset();
    document.getElementById('addValuesList').innerHTML = '';
    document.getElementById('addTypeInfo').classList.add('hidden');
    addValueCounter = 0;
    addValueInput('add'); // Add one value input by default
}

// Close Add Modal
function closeAddModal() {
    document.getElementById('addModal').classList.add('hidden');
}

// Update type information in add modal
function updateAddTypeInfo() {
    const typeSelect = document.getElementById('addType');
    const selectedType = typeSelect.value;
    const infoDiv = document.getElementById('addTypeInfo');
    
    if (!selectedType || !aclTypeInfo[selectedType]) {
        infoDiv.classList.add('hidden');
        return;
    }
    
    const info = aclTypeInfo[selectedType];
    document.getElementById('addTypeDesc').textContent = info.description;
    document.getElementById('addTypeExample').textContent = 'Ejemplo: ' + info.example;
    
    // Change icon color based on slow/fast
    const iconEl = document.getElementById('addTypeIcon');
    if (info.slow) {
        iconEl.className = 'fas fa-hourglass text-orange-600 mt-1 mr-2';
    } else {
        iconEl.className = 'fas fa-bolt text-green-600 mt-1 mr-2';
    }
    
    infoDiv.classList.remove('hidden');
}

// Add value input field
function addValueInput(mode) {
    const listId = mode === 'add' ? 'addValuesList' : 'editValuesList';
    const list = document.getElementById(listId);
    
    if (mode === 'add') {
        addValueCounter++;
    } else {
        editValueCounter++;
    }
    
    const counter = mode === 'add' ? addValueCounter : editValueCounter;
    
    const div = document.createElement('div');
    div.className = 'flex items-center space-x-2';
    div.id = `${mode}Value${counter}`;
    
    div.innerHTML = `
        <input type="text" name="values[]" required 
               placeholder="Ingresa un valor (ej: 192.168.1.0/24, .example.com, 80)"
               class="flex-1 px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent text-sm">
        <button type="button" onclick="removeValueInput('${mode}', ${counter})" 
                class="px-3 py-2 bg-red-500 hover:bg-red-600 text-white rounded-lg transition-colors">
            <i class="fas fa-trash"></i>
        </button>
    `;
    
    list.appendChild(div);
}

// Remove value input field
function removeValueInput(mode, counter) {
    const div = document.getElementById(`${mode}Value${counter}`);
    if (div) {
        div.remove();
    }
}

// Edit ACL
function editAcl(id, name, type, valueList, options, comment) {
    document.getElementById('editModal').classList.remove('hidden');
    document.getElementById('editId').value = id;
    document.getElementById('editName').value = name;
    document.getElementById('editType').value = type;
    document.getElementById('editTypeDisplay').value = type;
    document.getElementById('editComment').value = comment || '';
    
    // Set options checkboxes
    document.getElementById('editOptI').checked = options.includes('-i');
    document.getElementById('editOptN').checked = options.includes('-n');
    document.getElementById('editOptM').checked = options.includes('-m');
    
    // Clear and populate values
    const valuesList = document.getElementById('editValuesList');
    valuesList.innerHTML = '';
    editValueCounter = 0;
    
    if (valueList && valueList.length > 0) {
        valueList.forEach(value => {
            editValueCounter++;
            const div = document.createElement('div');
            div.className = 'flex items-center space-x-2';
            div.id = `editValue${editValueCounter}`;
            
            div.innerHTML = `
                <input type="text" name="values[]" required value="${value}"
                       class="flex-1 px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent text-sm">
                <button type="button" onclick="removeValueInput('edit', ${editValueCounter})" 
                        class="px-3 py-2 bg-red-500 hover:bg-red-600 text-white rounded-lg transition-colors">
                    <i class="fas fa-trash"></i>
                </button>
            `;
            
            valuesList.appendChild(div);
        });
    } else {
        addValueInput('edit');
    }
}

// Close Edit Modal
function closeEditModal() {
    document.getElementById('editModal').classList.add('hidden');
}

// Delete ACL
function deleteAcl(id, name) {
    if (!confirm(`¿Estás seguro de que deseas eliminar la ACL "${name}"?\n\nEsto puede afectar las reglas de http_access y delay_pools que la utilicen.`)) {
        return;
    }
    
    const form = document.createElement('form');
    form.method = 'POST';
    form.action = '/admin/acls/delete';
    
    // CSRF token
    const csrfInput = document.createElement('input');
    csrfInput.type = 'hidden';
    csrfInput.name = 'csrf_token';
    csrfInput.value = document.querySelector('input[name="csrf_token"]').value;
    form.appendChild(csrfInput);
    
    // ACL ID
    const idInput = document.createElement('input');
    idInput.type = 'hidden';
    idInput.name = 'id';
    idInput.value = id;
    form.appendChild(idInput);
    
    document.body.appendChild(form);
    form.submit();
}

// Close modals on ESC key
document.addEventListener('keydown', function(event) {
    if (event.key === 'Escape') {
        closeAddModal();
        closeEditModal();
    }
});

// Close modals when clicking outside
document.getElementById('addModal')?.addEventListener('click', function(event) {
    if (event.target === this) {
        closeAddModal();
    }
});

document.getElementById('editModal')?.addEventListener('click', function(event) {
    if (event.target === this) {
        closeEditModal();
    }
});
