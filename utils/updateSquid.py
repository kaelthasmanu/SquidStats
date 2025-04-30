import json
import subprocess
import platform
import os

def update_squid():
    try:
        os_info = platform.freedesktop_os_release()
        os_id = os_info.get('ID', '').lower()
        codename = os_info.get('VERSION_CODENAME', os_info.get('UBUNTU_CODENAME', '')).lower()

        if os_id not in ['ubuntu', 'debian'] or not codename:
            print('Sistema operativo no compatible', 'error')
            return False

        version_response = subprocess.run(
            ['curl', '-s', 'https://api.github.com/repos/cuza/squid/releases/latest'],
            capture_output=True, text=True
        )

        if version_response.returncode != 0:
            print('Error obteniendo última versión', 'error')
            return False

        try:
            latest_version = json.loads(version_response.stdout)['tag_name']
        except (json.JSONDecodeError, KeyError):
            print('Error procesando versión', 'error')
            return False

        # Create name package
        package_name = f"squid_{latest_version}-{os_id}-{codename}_amd64.deb"
        download_url = f"https://github.com/cuza/squid/releases/download/{latest_version}/{package_name}"

        check_package = subprocess.run(
            ['wget', '--spider', download_url],
            capture_output=True, text=True
        )

        if check_package.returncode != 0:
            print(f'Paquete no disponible para {os_id.capitalize()} {codename.capitalize()}', 'error')
            return False

        download = subprocess.run(['wget', download_url, '-O', f'/tmp/{package_name}'])
        subprocess.run(['apt', 'update'])

        if download.returncode != 0:
            print('Error descargando el paquete', 'error')
            return False

        install = subprocess.run(['dpkg', '-i', '--force-overwrite', f'/tmp/{package_name}'])
        if install.returncode != 0:
            print('Error instalando el paquete', 'error')
            subprocess.run(['apt', 'install', '-f', '-y'])

        subprocess.run(['cp', f'{os.getcwd()}/./utils/squid', '/etc/init.d/'])
        subprocess.run(['systemctl', 'daemon-reload'])

        subprocess.run(['rm', '-f', f'/tmp/{package_name}'])
        squid_check = subprocess.run(['squid', '-v'], capture_output=True, text=True)

        if squid_check.returncode != 0:
            print('Error en instalación final', 'error')
            return False

        print(f'Actualización a {latest_version} completada exitosamente', 'success')
        return True

    except Exception as e:
        print(f'Error crítico: {str(e)}', 'error')
        return False