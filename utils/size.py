def size_to_bytes(size_str):
        # Convierte '123 MB' o '1.2 GB' a bytes
        size_str = str(size_str).strip().upper()
        if size_str.endswith('GB'):
            return int(float(size_str.replace('GB','').strip()) * 1024**3)
        elif size_str.endswith('MB'):
            return int(float(size_str.replace('MB','').strip()) * 1024**2)
        elif size_str.endswith('KB'):
            return int(float(size_str.replace('KB','').strip()) * 1024)
        elif size_str.endswith('BYTES'):
            return int(float(size_str.replace('BYTES','').strip()))
        try:
            return int(size_str)
        except Exception:
            return 0