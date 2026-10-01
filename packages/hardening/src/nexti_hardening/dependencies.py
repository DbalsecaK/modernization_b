"""The dependencies of the generated project and their known vulnerabilities in OSV (ADR-0023). Only the names and
versions of public libraries leave the platform, never code. Without OSV (offline, or turned off) the check says it
was not done."""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import httpx

from nexti_hardening.report import Check, Finding, Severity

OSV_URL = "https://api.osv.dev"


@dataclass(frozen=True)
class Dependency:
    ecosystem: str  # OSV ecosystems: Maven, NuGet, npm
    name: str
    version: str
    file: str


def _maven(path: str, content: str) -> list[Dependency]:
    try:
        root = ET.fromstring(content)  # noqa: S314 - generated pom, no DTD
    except ET.ParseError:
        return []
    ns = {"m": root.tag.split("}")[0].strip("{")} if root.tag.startswith("{") else {}
    prefix = "m:" if ns else ""
    properties = {child.tag.split("}")[-1]: (child.text or "").strip()
                  for child in root.findall(f"{prefix}properties/*", ns)}  # fmt: skip
    found = []
    for dep in root.findall(f".//{prefix}dependency", ns):
        group, artifact, version = (dep.findtext(f"{prefix}{tag}", "", ns).strip()
                                    for tag in ("groupId", "artifactId", "version"))  # fmt: skip
        if version.startswith("${"):
            version = properties.get(version[2:-1], "")
        if group and artifact and version and re.match(r"^[0-9]", version):
            found.append(Dependency("Maven", f"{group}:{artifact}", version, path))
    return found


def _nuget(path: str, content: str) -> list[Dependency]:
    return [Dependency("NuGet", m.group(1), m.group(2), path) for m in
            re.finditer(r'<PackageReference\s+Include="([^"]+)"\s+Version="([0-9][^"]*)"', content)]  # fmt: skip


def _npm(path: str, content: str) -> list[Dependency]:
    import json

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return []
    found = []
    for section in ("dependencies", "devDependencies"):
        for name, spec in (data.get(section) or {}).items():
            version = re.sub(r"^[\^~=v]", "", str(spec))
            if re.match(r"^[0-9]+\.[0-9]+\.[0-9]+", version):
                found.append(Dependency("npm", name, version.split(" ")[0], path))
    return found


def dependencies(files: dict[str, str]) -> list[Dependency]:
    found: list[Dependency] = []
    for path, content in sorted(files.items()):
        name = path.rsplit("/", 1)[-1]
        if name == "pom.xml":
            found += _maven(path, content)
        elif name.endswith(".csproj"):
            found += _nuget(path, content)
        elif name == "package.json":
            found += _npm(path, content)
    return found


def _severity(vuln: dict[str, object]) -> Severity:
    specific = vuln.get("database_specific")
    text = str(specific.get("severity", "") if isinstance(specific, dict) else "").lower()
    if text in ("critical", "high", "medium", "low"):
        return text  # type: ignore[return-value]
    return "medium" if "moderate" in text else "high"


async def scan(http: httpx.AsyncClient | None, files: dict[str, str],
               osv_url: str | None = OSV_URL) -> tuple[list[Finding], Check]:  # fmt: skip
    deps = dependencies(files)
    if not deps:
        return [], Check("dependencies", "checked", "no declared dependencies")
    if http is None or not osv_url:
        return [], Check("dependencies", "not_checked", f"{len(deps)} dependencies; OSV is turned off")
    try:
        res = await http.post(f"{osv_url}/v1/querybatch", timeout=30, json={"queries": [
            {"package": {"ecosystem": d.ecosystem, "name": d.name}, "version": d.version} for d in deps]})  # fmt: skip
        res.raise_for_status()
        results = res.json().get("results", [])
        findings: list[Finding] = []
        details: dict[str, dict[str, object]] = {}
        for dep, result in zip(deps, results, strict=False):
            for vuln in (result or {}).get("vulns", []) or []:
                vid = str(vuln.get("id"))
                if vid not in details:
                    detail = await http.get(f"{osv_url}/v1/vulns/{vid}", timeout=30)
                    details[vid] = detail.json() if detail.status_code == 200 else {}
                info = details[vid]
                summary = str(info.get("summary") or "known vulnerability")[:200]
                findings.append(Finding("dependencies", _severity(info), vid, dep.file, None,
                                        f"{dep.name} {dep.version}: {summary}"))  # fmt: skip
    except (httpx.HTTPError, ValueError) as exc:
        return [], Check("dependencies", "not_checked", f"OSV did not answer ({type(exc).__name__})")
    return findings, Check("dependencies", "checked", f"{len(deps)} dependencies in OSV")
