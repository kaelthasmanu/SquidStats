import re
import os

input_file = "/home/manuel/Desktop/squid.conf"

files = {
    "acls.conf": [],
    "delay_pools.conf": [],
    "auth.conf": [],
}

# Patrones por categoría
patterns = {
    "acls.conf": [
        re.compile(r"^\s*acl\b"),
    ],
    "delay_pools.conf": [
        re.compile(r"^\s*delay_(pools|class|parameters|access)\b"),
    ],
    "auth.conf": [
        re.compile(r"^\s*auth_param\b"),
        re.compile(r"^\s*authenticate_ip_ttl\b"),
        re.compile(r"^\s*acl\b.*\bproxy_auth\b"),
    ],
}

def extract_squid_config(input_file):
    if not os.path.exists(input_file):
        print(f"Error: El archivo {input_file} no existe.")
        return
    try:
        with open(input_file) as f:
            lines = f.readlines()
    except PermissionError:
        print(f"Error: No se tienen permisos para leer {input_file}")
        return
    except Exception as e:
        print(f"Error al leer el archivo {input_file}: {e}")
        return
        lines = f.readlines()

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        for file, regex_list in patterns.items():
            if any(regex.search(stripped) for regex in regex_list):
                files[file].append(line)
                break

    for filename, content in files.items():
        with open(filename, "w") as f:
            f.writelines(content)

    print("Extracción completada. Archivos generados:")
    for f in files:
        print(f" - {f}")


if __name__ == "__main__":
    extract_squid_config()
