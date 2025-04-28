import json
import subprocess
import platform

def updateSquidStats():
    try:
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

        install = subprocess.run(['dpkg', '-i', '--force-overwrite', f'/tmp/{package_name}'])
        if install.returncode != 0:
            print('Error instalando el paquete', 'error')
            subprocess.run(['apt', 'install', '-f', '-y'])

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