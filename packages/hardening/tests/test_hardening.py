"""Hardening (ADR-0023): an insecure project gets its findings (a secret, a vulnerable dependency in a simulated OSV,
insecure patterns and a slow test) and the generated reference project gets none of the patterns. The secret of the
fixture is built at run time, so no secret is ever committed. Sandbox tests skip without the image."""

import asyncio
import json
import subprocess
from pathlib import Path

import httpx
import pytest
import respx

from nexti_hardening import IMAGE, Report, harden, patterns
from nexti_hardening.dependencies import dependencies
from nexti_sandbox import DockerSandbox

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / "packs/target/spring_boot/tests/fixtures/pago_orden"
OSV = "https://osv.test"
AWS_KEY = "AKIA" + "Q3EGRIMXYZ7PLNS4"  # built here, never written whole in the repository


def insecure() -> dict[str, str]:
    return {
        "pom.xml": """<project xmlns="http://maven.apache.org/POM/4.0.0"><properties><log4j.version>2.14.1</log4j.version>
<lombok.version>1.18.30</lombok.version></properties><dependencies>
<dependency><groupId>org.apache.logging.log4j</groupId><artifactId>log4j-core</artifactId><version>${log4j.version}</version></dependency>
<dependency><groupId>org.projectlombok</groupId><artifactId>lombok</artifactId><version>${lombok.version}</version></dependency>
</dependencies></project>""",
        "src/main/java/app/Repo.java": (
            'class Repo { void f(String id) { stmt.executeQuery("SELECT * FROM t WHERE id=" + id); }\n'
            '  String password = "Sup3rS3cret!"; }\n'
        ),
        "src/main/java/app/Web.java": '@CrossOrigin("*") class Web {}\n',
        "src/main/resources/application.properties": "spring.datasource.password=hunter22\ndebug=true\n",
        "src/main/resources/aws.properties": f"aws.key.id={AWS_KEY}\n",
        "src/test/java/app/RepoTest.java": 'class RepoTest { String password = "only-in-tests"; }\n',
        "package.json": json.dumps({"dependencies": {"axios": "^1.7.0"}}),
    }


JUNIT = """<testsuite><testcase classname="app.RepoTest" name="fast" time="0.2"/>
<testcase classname="app.RepoTest" name="slow" time="5.5"/></testsuite>"""


def test_the_build_files_give_the_dependencies() -> None:
    found = {(d.ecosystem, d.name, d.version) for d in dependencies(insecure())}
    assert found == {("Maven", "org.apache.logging.log4j:log4j-core", "2.14.1"),
                     ("Maven", "org.projectlombok:lombok", "1.18.30"), ("npm", "axios", "1.7.0")}  # fmt: skip


def test_insecure_patterns_are_found_and_tests_are_not_scanned() -> None:
    found = {(f.rule, f.file) for f in patterns.scan(insecure())}
    assert found == {
        ("sql-concatenation", "src/main/java/app/Repo.java"),
        ("credential-in-code", "src/main/java/app/Repo.java"),
        ("cors-any-origin", "src/main/java/app/Web.java"),
        ("credential-in-config", "src/main/resources/application.properties"),
        ("debug-enabled", "src/main/resources/application.properties"),
    }


def test_the_generated_reference_project_has_no_insecure_pattern() -> None:
    files = {p.relative_to(REFERENCE).as_posix(): p.read_text(encoding="utf-8") for p in REFERENCE.rglob("*.java")}
    assert files
    assert patterns.scan(files) == []


@respx.mock
def test_the_report_puts_vulnerabilities_first_and_says_what_was_not_checked() -> None:
    respx.post(f"{OSV}/v1/querybatch").mock(return_value=httpx.Response(200, json={"results": [
        {"vulns": [{"id": "GHSA-jfh8-c2jp-5v3q"}]}, {}, {}]}))  # fmt: skip
    respx.get(f"{OSV}/v1/vulns/GHSA-jfh8-c2jp-5v3q").mock(return_value=httpx.Response(200, json={
        "id": "GHSA-jfh8-c2jp-5v3q", "summary": "Remote code injection in Log4j",
        "database_specific": {"severity": "CRITICAL"}}))  # fmt: skip

    async def run() -> Report:
        async with httpx.AsyncClient() as http:
            return await harden(insecure(), sandbox=None, http=http, junit_xml=JUNIT, osv_url=OSV)

    report: Report = asyncio.run(run())
    first = report.findings[0]
    assert (first.kind, first.severity, first.rule) == ("dependencies", "critical", "GHSA-jfh8-c2jp-5v3q")
    statuses = {c.kind: c.status for c in report.checks}
    assert statuses == {"secrets": "not_checked", "dependencies": "checked", "patterns": "checked",
                        "performance": "checked"}  # fmt: skip
    assert any(f.rule == "slow-test" and "slow took 5.5 s" in f.message for f in report.findings)
    markdown = report.to_markdown()
    assert "| critical | dependencies | GHSA-jfh8-c2jp-5v3q |" in markdown
    assert "hunter22" not in markdown
    assert "Sup3rS3cret!" not in markdown


def test_without_osv_the_dependencies_are_not_checked() -> None:
    report = asyncio.run(harden(insecure(), sandbox=None, http=None, junit_xml=None))
    checks = {c.kind: (c.status, c.detail) for c in report.checks}
    assert checks["dependencies"] == ("not_checked", "3 dependencies; OSV is turned off")
    assert checks["performance"][0] == "not_checked"


def _image_available() -> bool:
    try:
        found = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, check=False, timeout=30)  # noqa: S603, S607
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return found.returncode == 0


def test_gitleaks_finds_the_secret_without_keeping_it() -> None:
    box = DockerSandbox(image=IMAGE)
    if not asyncio.run(box.available()) or not _image_available():
        pytest.skip(f"Docker or the image {IMAGE} is not available")
    report = asyncio.run(harden(insecure(), sandbox=box, http=None, junit_xml=None))
    leaks = [f for f in report.findings if f.kind == "secrets"]
    assert any(f.file == "src/main/resources/aws.properties" and f.line == 1 for f in leaks), leaks
    assert AWS_KEY not in json.dumps(report.to_dict())
    assert {c.kind: c.status for c in report.checks}["secrets"] == "checked"
