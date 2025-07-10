import subprocess

def updateSquidStats():
    try:
        script_install = subprocess.run(
            ['wget', '-O' , '/tmp/install.sh', 'https://github.com/kaelthasmanu/SquidStats/releases/download/0.2/install.sh'],
            capture_output=True, text=True
        )

        if script_install.returncode != 0:
            print('Error descargando el script de actualizacion', 'error')
            return False

        subprocess.run(
            ['chmod', '+x', '/tmp/install.sh']
        )
        subprocess.run(['bash' , '/tmp/install.sh', '--update'])
        return True

    except Exception as e:
        print(f'Error crítico: {str(e)}', 'error')
        return False