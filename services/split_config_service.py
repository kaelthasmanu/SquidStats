import os

from loguru import logger

from services.squid_config_splitter import SquidConfigSplitter


def get_split_view_data():
    splitter = SquidConfigSplitter()
    return {
        "split_info": splitter.get_split_info(),
        "output_exists": splitter.check_output_dir_exists(),
        "files_count": splitter.count_files_in_output_dir(),
        "output_dir": splitter.output_dir,
        "input_file": splitter.input_file,
    }


def split_config(strict=False):
    splitter = SquidConfigSplitter(strict=strict)

    if not os.path.exists(splitter.input_file):
        return {
            "status": "error",
            "message": f"Archivo squid.conf no encontrado en: {splitter.input_file}",
        }, 404

    try:
        results = splitter.split_config()
        return {
            "status": "success",
            "message": f"Configuración dividida exitosamente en {len(results)} archivos",
            "data": {
                "output_dir": splitter.output_dir,
                "files": results,
                "total_files": len(results),
            },
        }, 200
    except FileNotFoundError as e:
        logger.error("Archivo no encontrado: %s", e)
        return {"status": "error", "message": "Archivo requerido no encontrado."}, 404
    except PermissionError as e:
        logger.error("Error de permisos: %s", e)
        return {
            "status": "error",
            "message": "No se tienen permisos suficientes para crear los archivos",
        }, 403
    except RuntimeError as e:
        logger.error("Error de validación: %s", e)
        return {
            "status": "error",
            "message": "Error de validación de la configuración",
        }, 400
    except Exception as e:
        logger.exception("Error al dividir el archivo de configuración")
        return {
            "status": "error",
            "message": "Error interno al dividir la configuración",
            "details": str(e),
        }, 500


def get_split_files_info(output_dir: str):
    return SquidConfigSplitter.get_split_files_info(output_dir)
