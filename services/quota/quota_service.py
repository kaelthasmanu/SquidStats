import os
import re
import shutil
import subprocess  # nosec B404

from loguru import logger

from services.squid.squid_config_splitter import SquidConfigSplitter
from services.system.system_service import reload_squid
from utils.admin import SquidConfigManager

_BLOCKED_USERS_PATH = "/etc/squid/usuarios_bloqueados.txt"


def _ensure_blocked_file(blocked_path: str):
    """Crea el archivo de bloqueados si no existe, tanto local como en Docker."""
    try:
        if not os.path.exists(blocked_path):
            with open(blocked_path, "a", encoding="utf-8"):
                pass
            os.chmod(blocked_path, 0o640)
            logger.info("Creado archivo de usuarios bloqueados: %s", blocked_path)
        else:
            os.chmod(blocked_path, 0o640)
    except Exception as e:
        logger.warning(
            "No se pudo crear/ajustar permisos locales de %s: %s", blocked_path, e
        )

    docker_bin = shutil.which("docker")
    if docker_bin is None:
        logger.debug("Docker no disponible, omitiendo creación en contenedor")
        return

    try:
        subprocess.run(  # nosec B603  # noqa: S603
            [docker_bin, "exec", "squid_proxy", "test", "-f", blocked_path],
            check=True,
            capture_output=True,
            timeout=10,
        )
    except subprocess.CalledProcessError:
        try:
            subprocess.run(  # nosec B603  # noqa: S603
                [docker_bin, "exec", "squid_proxy", "touch", blocked_path],
                check=True,
                capture_output=True,
                timeout=10,
            )
            subprocess.run(  # nosec B603  # noqa: S603
                [docker_bin, "exec", "squid_proxy", "chmod", "640", blocked_path],
                check=True,
                capture_output=True,
                timeout=10,
            )
            logger.info("Creado %s dentro del contenedor squid_proxy", blocked_path)
        except Exception as e:
            logger.warning(
                "No se pudo crear %s en contenedor Docker: %s", blocked_path, e
            )
    except Exception as e:
        logger.debug("Error verificando archivo en contenedor: %s", e)


def _sync_blocked_file_to_docker(blocked_path: str):
    """Copia el archivo de bloqueados al contenedor Docker si está disponible."""
    docker_bin = shutil.which("docker")
    if docker_bin is None:
        return
    try:
        subprocess.run(  # nosec B603  # noqa: S603
            [docker_bin, "cp", blocked_path, f"squid_proxy:{blocked_path}"],
            check=True,
            capture_output=True,
            timeout=10,
        )
    except Exception as e:
        logger.debug("No se pudo sincronizar %s a Docker: %s", blocked_path, e)


def _commit_modular_config(cm: SquidConfigManager, filename: str, lines: list[str]):
    content = "\n".join(line for line in lines if line.strip() != "")
    return cm.save_modular_config(filename, content)


def _sync_quota_squid_rules(enabled: bool):
    """Sync `usuarios_bloqueados` ACL/http_access in Squid config."""
    cm = SquidConfigManager()
    logger.debug(
        "sync_quota_squid_rules: enabled={}, config_path={}, config_dir={}, is_modular={}, is_valid={}",
        enabled,
        cm.config_path,
        cm.config_dir,
        cm.is_modular,
        cm.is_valid,
    )
    if not cm.is_valid:
        logger.warning(
            "SquidConfigManager no válido: no se puede sincronizar reglas de cuota. Errores: {}",
            "; ".join(cm.errors) if cm.errors else "sin detalles",
        )
        return

    blocked_path = _BLOCKED_USERS_PATH
    logger.debug(
        "_sync_quota_squid_rules: blocked_path={}, enabled={}", blocked_path, enabled
    )
    _ensure_blocked_file(blocked_path)

    def _normalize_line(line: str) -> str:
        return line.strip().split("#")[0].strip()

    def _is_acl_line(line: str) -> bool:
        text = _normalize_line(line)
        return text.startswith("acl usuarios_bloqueados")

    def _is_http_line(line: str) -> bool:
        text = _normalize_line(line)
        return text.startswith("http_access deny usuarios_bloqueados")

    def _is_include_line(line: str) -> bool:
        return _normalize_line(line) == f"include {blocked_path}"

    def _build_acl_line(use_src: bool) -> str:
        if use_src:
            return f"include {blocked_path}"
        return f"acl usuarios_bloqueados proxy_auth -i {blocked_path}"

    auth_configured = bool(
        re.search(r"^\s*auth_param\b", cm.config_content, re.MULTILINE)
        and re.search(r"^\s*acl\s+auth\b", cm.config_content, re.MULTILINE)
    )

    use_src = not auth_configured
    acl_line = _build_acl_line(use_src)
    http_line = "http_access deny usuarios_bloqueados"

    def _apply_changes(acl_line: str, http_line: str, use_src: bool) -> bool:
        previous_main_content = cm.config_content or ""
        previous_acls_content = ""
        previous_http_content = ""
        config_changed = False

        def _matches_acl_entry(line: str) -> bool:
            """Coincide con la ACL o include según el modo."""
            return _is_include_line(line) if use_src else _is_acl_line(line)
        try:
            if cm.is_modular:
                previous_acls_content = cm.read_modular_config("100_acls.conf") or ""
                previous_http_content = (
                    cm.read_modular_config("120_http_access.conf") or ""
                )

                acls_content = previous_acls_content
                acl_lines = [
                    line for line in acls_content.split("\n") if line.strip() != ""
                ]
                original_acl_lines = acl_lines.copy()

                if enabled:
                    if not any(_matches_acl_entry(line) for line in acl_lines):
                        if use_src:
                            acl_lines.insert(0, acl_line)
                        else:
                            inserted = False
                            for i, line in enumerate(acl_lines):
                                if line.strip().startswith("acl "):
                                    acl_lines.insert(i, acl_line)
                                    inserted = True
                                    break
                            if not inserted:
                                acl_lines.append(acl_line)
                else:
                    acl_lines = [
                        line for line in acl_lines if not _matches_acl_entry(line)
                    ]

                if acl_lines != original_acl_lines:
                    config_changed = True

                if not _commit_modular_config(cm, "100_acls.conf", acl_lines):
                    raise RuntimeError("No se pudieron guardar 100_acls.conf")

                http_content = previous_http_content
                http_lines = [
                    line for line in http_content.split("\n") if line.strip() != ""
                ]
                original_http_lines = http_lines.copy()

                if enabled:
                    if not any(_is_http_line(line) for line in http_lines):
                        inserted = False
                        for i, line in enumerate(http_lines):
                            if line.strip().startswith("http_access "):
                                http_lines.insert(i, http_line)
                                inserted = True
                                break
                        if not inserted:
                            http_lines.append(http_line)
                else:
                    http_lines = [
                        line for line in http_lines if not _is_http_line(line)
                    ]

                if http_lines != original_http_lines:
                    config_changed = True

                if not _commit_modular_config(cm, "120_http_access.conf", http_lines):
                    raise RuntimeError("No se pudieron guardar 120_http_access.conf")

            else:
                if not cm.config_content and enabled:
                    logger.error(
                        "config_content está vacío (posible fallo de carga). "
                        "Se cancela la modificación de squid.conf para evitar pérdida de datos."
                    )
                    return False
                lines = cm.config_content.split("\n") if cm.config_content else []
                original_lines = lines.copy()

                if enabled:
                    if not any(_matches_acl_entry(line) for line in lines):
                        if use_src:
                            insert_idx = 0
                            for i, line in enumerate(lines):
                                if line.strip() and not line.strip().startswith("#"):
                                    insert_idx = i
                                    break
                            # logger.debug(
                            #     "_apply_changes: insertando ACL src en squid.conf: {}",
                            #     acl_line,
                            # )
                            lines.insert(insert_idx, acl_line)
                        else:
                            inserted = False
                            for i, line in enumerate(lines):
                                if line.strip().startswith("acl "):
                                    lines.insert(i, acl_line)
                                    inserted = True
                                    break
                            if not inserted:
                                lines.append(acl_line)

                    if not any(_is_http_line(line) for line in lines):
                        inserted = False
                        for i, line in enumerate(lines):
                            if line.strip().startswith("http_access "):
                                lines.insert(i, http_line)
                                inserted = True
                                break
                        if not inserted:
                            lines.append(http_line)
                else:
                    lines = [
                        line
                        for line in lines
                        if not (_matches_acl_entry(line) or _is_http_line(line))
                    ]

                if lines != original_lines:
                    config_changed = True

                if not cm.save_config("\n".join(lines)):
                    raise RuntimeError("No se pudo guardar squid.conf")

            if not config_changed:
                return True

            splitter = SquidConfigSplitter(
                input_file=cm.config_path,
                output_dir=cm.config_dir,
            )
            validation = splitter._validate_squid_config()

            if not validation.get("success"):
                logger.error(
                    "Validación de Squid falló al sincronizar reglas de cuota | output={} | error_message={}",
                    validation.get("output") or "<sin output>",
                    validation.get("error_message") or "<sin error_message>",
                )
                # rollback
                if cm.is_modular:
                    cm.save_modular_config("100_acls.conf", previous_acls_content)
                    cm.save_modular_config(
                        "120_http_access.conf", previous_http_content
                    )
                if previous_main_content:
                    cm.save_config(previous_main_content)
                return False

            reload_success, reload_msg, _ = reload_squid()
            if not reload_success:
                logger.warning(
                    "Squid no se pudo recargar después de actualizar reglas de cuota: %s",
                    reload_msg,
                )
            else:
                logger.info("Squid recargado correctamente")

            return True

        except Exception:
            logger.exception("Error aplicando reglas de cuota")
            if cm.is_modular:
                cm.save_modular_config("100_acls.conf", previous_acls_content)
                cm.save_modular_config("120_http_access.conf", previous_http_content)
            if previous_main_content:
                cm.save_config(previous_main_content)
            return False

    # First try
    ok = _apply_changes(acl_line, http_line, use_src)

    # Si falla y no es src, fallback a src (evita vida de proxy_auth mal configurada)
    if not ok and not use_src:
        logger.warning(
            "Fallo con proxy_auth, reiniciando con ACL src para compatibilidad"
        )
        acl_line = _build_acl_line(True)
        ok = _apply_changes(acl_line, http_line, True)

    if not ok:
        logger.error(
            "No se pudo sincronizar las reglas de cuota después de reintentos. use_src={}, acl_line={}, http_line={}",
            use_src,
            acl_line,
            http_line,
        )
