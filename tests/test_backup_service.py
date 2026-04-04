from unittest.mock import patch

from services.database import backup_service


def test_get_backup_file_path_rejects_path_traversal(tmp_path):
    backup_dir = tmp_path
    valid_file = backup_dir / "squidstats_backup_auto_20240101_000000.sqlite3"
    valid_file.write_text("backup content")

    with patch(
        "services.database.backup_service.load_config",
        return_value={"backup_dir": str(backup_dir)},
    ):
        assert backup_service.get_backup_file_path("../secret.txt") is None
        assert backup_service.get_backup_file_path("..\\secret.txt") is None
        assert backup_service.get_backup_file_path("") is None
        assert backup_service.get_backup_file_path(valid_file.name) == valid_file


def test_delete_backup_rejects_invalid_filename(tmp_path):
    backup_dir = tmp_path
    with patch(
        "services.database.backup_service.load_config",
        return_value={"backup_dir": str(backup_dir)},
    ):
        result = backup_service.delete_backup("../../etc/passwd")
        assert result["status"] == "error"
        assert "inválido" in result["message"].lower()


def test_delete_backup_removes_valid_backup(tmp_path):
    backup_dir = tmp_path
    valid_file = backup_dir / "squidstats_backup_manual_20240101_000000.sqlite3"
    valid_file.write_text("backup content")

    with patch(
        "services.database.backup_service.load_config",
        return_value={"backup_dir": str(backup_dir)},
    ):
        result = backup_service.delete_backup(valid_file.name)
        assert result["status"] == "success"
        assert not valid_file.exists()
