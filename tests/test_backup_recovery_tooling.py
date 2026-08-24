import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "scripts" / "OptionBeaconBackup.psm1"
SCRIPT = ROOT / "scripts" / "backup_optionbeacon.ps1"
POWERSHELL = shutil.which("powershell.exe") or shutil.which("powershell")


def _ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def _invoke_module_json(expression):
    if not POWERSHELL:
        pytest.skip("Windows PowerShell is unavailable")
    command = (
        f"Import-Module {_ps_quote(MODULE)} -Force; "
        f"$result = & {{ {expression} }}; $result | ConvertTo-Json -Depth 20 -Compress"
    )
    result = subprocess.run(
        [
            POWERSHELL,
            "-NoLogo",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert not result.stderr, result.stderr
    return json.loads(result.stdout.strip())


def test_configuration_parsing(tmp_path):
    config = tmp_path / "backup.json"
    config.write_text(
        json.dumps(
            {
                "PreferredVolumeLabel": "Samsung_T5",
                "FallbackDriveRoot": "D:\\",
                "DestinationFolder": "OptionBeacon_Backup",
                "DatabaseDumpRequired": False,
                "PgDumpPath": "",
                "ProtectedSecretsSource": "",
                "AdditionalExportPaths": ["exports"],
                "MaximumArtifactSizeMB": 77,
            }
        ),
        encoding="utf-8",
    )
    parsed = _invoke_module_json(
        f"Read-BackupConfiguration -Path {_ps_quote(config)}"
    )
    assert parsed["PreferredVolumeLabel"] == "Samsung_T5"
    assert parsed["DestinationFolder"] == "OptionBeacon_Backup"
    assert parsed["DatabaseDumpRequired"] is False
    assert parsed["MaximumArtifactSizeMB"] == 77


def test_destination_override_requires_explicit_test_permission(tmp_path):
    expression = (
        "$c=[pscustomobject]@{PreferredVolumeLabel='Samsung_T5';"
        "FallbackDriveRoot='D:\\';DestinationFolder='OptionBeacon_Backup'}; "
        f"try {{ Resolve-BackupDestination -Configuration $c "
        f"-DestinationRootOverride {_ps_quote(tmp_path)}; 'unsafe' }} "
        "catch { 'blocked' }"
    )
    assert _invoke_module_json(expression) == "blocked"
    allowed = _invoke_module_json(
        "$c=[pscustomobject]@{PreferredVolumeLabel='Samsung_T5';"
        "FallbackDriveRoot='D:\\';DestinationFolder='OptionBeacon_Backup'}; "
        f"Resolve-BackupDestination -Configuration $c "
        f"-DestinationRootOverride {_ps_quote(tmp_path)} -AllowNonSsdDestination"
    )
    assert allowed["Detection"] == "explicit-test-override"
    assert Path(allowed["BackupRoot"]) == tmp_path


@pytest.mark.parametrize(
    ("relative", "included", "reason"),
    [
        ("research/forensic.json", True, "recovery-or-research-artifact"),
        ("node_modules/pkg/index.js", False, "generated-or-cache-directory"),
        (".streamlit/secrets.toml", False, "secret-or-private-configuration"),
        ("frontend/.env.local", False, "secret-or-private-configuration"),
        ("archive.exe", False, "unsupported-untracked-artifact-type"),
    ],
)
def test_artifact_exclusion_policy(relative, included, reason):
    result = _invoke_module_json(
        f"Test-BackupRelativePath -RelativePath {_ps_quote(relative)} -Length 10"
    )
    assert result["Include"] is included
    assert result["Reason"] == reason


def test_redaction_removes_database_and_token_values():
    source = (
        "DATABASE_URL=postgresql://user:password@host/database "
        "TRADIER_ACCESS_TOKEN=top-secret"
    )
    result = _invoke_module_json(f"Protect-BackupText {_ps_quote(source)}")
    assert "password" not in result
    assert "top-secret" not in result
    assert "REDACTED" in result


def test_success_partial_and_failure_classification():
    states = _invoke_module_json(
        "@("
        "(Get-BackupFinalState -CoreVerified $true -DatabaseRequired $false "
        "-DatabaseSucceeded $false),"
        "(Get-BackupFinalState -CoreVerified $true -DatabaseRequired $true "
        "-DatabaseSucceeded $false),"
        "(Get-BackupFinalState -CoreVerified $false -DatabaseRequired $false "
        "-DatabaseSucceeded $false),"
        "(Get-BackupFinalState -CoreVerified $true -DatabaseRequired $false "
        "-DatabaseSucceeded $false -WarningCount 1))"
    )
    assert states == [
        "BACKUP SUCCESSFUL",
        "BACKUP PARTIAL",
        "BACKUP FAILED",
        "BACKUP SUCCESSFUL WITH WARNINGS",
    ]


def test_git_status_parser_separates_modified_and_untracked():
    status = " M tracked.py\nA  staged.py\n?? local.json"
    result = _invoke_module_json(
        f"ConvertFrom-GitStatusPorcelain {_ps_quote(status)}"
    )
    assert result["ModifiedTracked"] == ["tracked.py", "staged.py"]
    assert result["Untracked"] == ["local.json"]


def test_latest_pointer_is_not_changed_by_partial_backup(tmp_path):
    latest = tmp_path / "LATEST"
    latest.mkdir()
    pointer = latest / "CURRENT_SNAPSHOT.txt"
    pointer.write_text("known-good\n", encoding="utf-8")
    expression = (
        f"$partial=Update-LatestPointer -BackupRoot {_ps_quote(tmp_path)} "
        "-SnapshotName 'partial' -FinalState 'BACKUP PARTIAL'; "
        f"$afterPartial=(Get-Content -Raw {_ps_quote(pointer)}).Trim(); "
        f"$success=Update-LatestPointer -BackupRoot {_ps_quote(tmp_path)} "
        "-SnapshotName 'verified' -FinalState 'BACKUP SUCCESSFUL'; "
        f"$afterSuccess=(Get-Content -Raw {_ps_quote(pointer)}).Trim(); "
        "[pscustomobject]@{partial=$partial;afterPartial=$afterPartial;"
        "success=$success;afterSuccess=$afterSuccess}"
    )
    result = _invoke_module_json(expression)
    assert result == {
        "partial": False,
        "afterPartial": "known-good",
        "success": True,
        "afterSuccess": "verified",
    }


def test_secret_inventory_contains_names_only():
    result = _invoke_module_json(
        f"Get-OptionBeaconSecretInventory -RepositoryPath {_ps_quote(ROOT)}"
    )
    names = {item["name"] for item in result}
    assert {"DATABASE_URL", "TRADIER_ACCESS_TOKEN", "FINNHUB_API_KEY"} <= names
    assert "OB_RISK_PER_TRADE_PCT" in names
    assert "BROAD_DRAWDOWN_HALT_PCT" in names
    encoded = json.dumps(result)
    assert "postgresql://" not in encoded
    assert "token_value" not in encoded


def test_temporary_backup_creates_verified_bundle_manifest_and_latest(tmp_path):
    if not POWERSHELL:
        pytest.skip("Windows PowerShell is unavailable")
    repository = tmp_path / "source"
    destination = tmp_path / "backup-target"
    (repository / "frontend").mkdir(parents=True)
    for relative, content in {
        "README.md": "temporary repository\n",
        "requirements.txt": "fastapi\n",
        "RESTORE_OPTIONBEACON.md": "restore\n",
        "RECOVERY_CHECKLIST.md": "checklist\n",
        "frontend/package.json": '{"packageManager":"pnpm@11.19.0"}\n',
        "frontend/pnpm-lock.yaml": "lockfileVersion: '9.0'\n",
        ".gitignore": ".env\nnode_modules/\n",
    }.items():
        path = repository / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    config = repository / "backup.config.example.json"
    config.write_text(
        json.dumps(
            {
                "PreferredVolumeLabel": "Samsung_T5",
                "FallbackDriveRoot": "D:\\",
                "DestinationFolder": "OptionBeacon_Backup",
                "DatabaseDumpRequired": False,
                "PgDumpPath": "",
                "ProtectedSecretsSource": "",
                "AdditionalExportPaths": [],
                "MaximumArtifactSizeMB": 50,
            }
        ),
        encoding="utf-8",
    )
    subprocess.run(["git", "init", str(repository)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repository), "add", "."], check=True)
    subprocess.run(
        [
            "git", "-C", str(repository), "-c", "user.name=Backup Test",
            "-c", "user.email=backup@example.invalid", "commit", "-m", "fixture",
        ],
        check=True,
        capture_output=True,
    )
    (repository / "README.md").write_text("uncommitted tracked work\n", encoding="utf-8")
    (repository / "forensic.json").write_text('{"research":true}\n', encoding="utf-8")
    (repository / ".env").write_text("DATABASE_URL=do-not-copy\n", encoding="utf-8")

    result = subprocess.run(
        [
            POWERSHELL,
            "-NoLogo",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT),
            "-RepositoryPath",
            str(repository),
            "-ConfigPath",
            str(config),
            "-DestinationRootOverride",
            str(destination),
            "-AllowNonSsdDestination",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    pointer = destination / "LATEST" / "CURRENT_SNAPSHOT.txt"
    snapshot = destination / "SNAPSHOTS" / pointer.read_text(encoding="utf-8").strip()
    manifest = json.loads(
        (snapshot / "manifests" / "backup_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["verification"]["final_state"] == "BACKUP SUCCESSFUL WITH WARNINGS"
    assert manifest["git"]["bundle_status"] == "verified"
    assert manifest["source"]["modified_tracked"] == ["README.md"]
    assert (snapshot / "repository" / "README.md").read_text(encoding="utf-8") == "uncommitted tracked work\n"
    assert (snapshot / "exports" / "forensic.json").exists()
    assert not (snapshot / "exports" / ".env").exists()
    assert (snapshot / "git" / "Option-Beacon-complete.bundle").stat().st_size > 0
