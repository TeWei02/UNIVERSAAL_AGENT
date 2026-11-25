#!/usr/bin/env python3
"""UNIVERSAAL_AGENT 文档仓库自检（零依赖，仅 Python 标准库）。

检查项：
  1. 必要文件存在（双语 README / LICENSE / .gitignore）
  2. 中英双语 README 双向互链
  3. Markdown 一级标题存在
  4. Markdown 本地相对链接与图片是否存在（跳过外链与模板占位）
  5. 密钥外泄扫描（高危记 error，可疑硬编码记 warning）
  6. 残留版本冲突标记

退出码：存在 error 时为 1，否则为 0。
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

REPO_NAME = "UNIVERSAAL_AGENT"
ROOT = Path(__file__).resolve().parent.parent

REQUIRED_FILES = ["README.md", "README.en.md", "LICENSE", ".gitignore"]
SKIP_DIRS = {".git", ".github", "node_modules", "__pycache__", ".venv", "venv", ".idea", ".vscode"}
TEXT_SUFFIXES = {
    ".md", ".txt", ".json", ".yml", ".yaml", ".py", ".js", ".ts", ".html", ".css",
    ".toml", ".ini", ".cfg", ".sh", ".bat", ".ps1", ".xml", ".gitignore", "",
}
MAX_SCAN_BYTES = 2 * 1024 * 1024

MD_LINK_RE = re.compile(r"\]\(\s*([^()\s]+(?:\([^()]*\)[^()\s]*)*)\s*\)")
H1_RE = re.compile(r"^#\s+\S", re.MULTILINE)
CONFLICT_RE = re.compile(r"^(<{7}|={7}|>{7})(\s|$)", re.MULTILINE)

SECRET_RULES = [
    ("私钥块", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----"), "error"),
    ("AWS Access Key", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "error"),
    ("GitHub Token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"), "error"),
    ("Google API Key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"), "error"),
    ("Slack Token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"), "error"),
    ("OpenAI 风格密钥", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"), "error"),
]
ASSIGN_RE = re.compile(
    r"(?i)\b(api[_-]?key|apikey|secret|secret[_-]?key|token|access[_-]?token|password|passwd)\b"
    r"\s*[:=]\s*[\"'][^\"'\n]{8,}[\"']"
)
PLACEHOLDERS = (
    "your", "xxx", "placeholder", "example", "sample", "changeme", "change-me",
    "todo", "dummy", "fake", "test", "none", "null", "{{", "${",
)

errors: list[str] = []
warnings: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)


def warn(msg: str) -> None:
    warnings.append(msg)


def iter_files() -> list[Path]:
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            out.append(Path(dirpath) / name)
    return out


def read_text(path: Path) -> str | None:
    try:
        if path.stat().st_size > MAX_SCAN_BYTES:
            return None
        raw = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in raw:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def check_required() -> None:
    for name in REQUIRED_FILES:
        if not (ROOT / name).is_file():
            err(f"缺少必要文件：{name}")


def check_bilingual() -> None:
    zh = ROOT / "README.md"
    en = ROOT / "README.en.md"
    if zh.is_file():
        text = zh.read_text(encoding="utf-8", errors="replace")
        if "README.en.md" not in text:
            err("README.md 未链接英文版 README.en.md")
    if en.is_file():
        text = en.read_text(encoding="utf-8", errors="replace")
        if "README.md" not in text:
            err("README.en.md 未回链中文版 README.md")


def is_skippable_link(target: str) -> bool:
    raw = target.strip()
    if not raw or raw.startswith("#"):
        return True
    if any(token in raw for token in ("{{", "}}", "${", "<%", "%}")):
        return True
    parsed = urlsplit(raw)
    if parsed.scheme or raw.startswith("//"):
        return True
    return False


def check_markdown() -> None:
    for path in iter_files():
        if path.suffix.lower() != ".md":
            continue
        rel = path.relative_to(ROOT).as_posix()
        text = read_text(path)
        if text is None:
            continue
        if path.name in ("README.md", "README.en.md") and not H1_RE.search(text):
            err(f"{rel} 缺少一级标题")
        for match in MD_LINK_RE.finditer(text):
            target = match.group(1).strip()
            if is_skippable_link(target):
                continue
            candidate = target.split("#", 1)[0].split("?", 1)[0]
            if not candidate:
                continue
            candidate = unquote(candidate)
            if candidate.startswith("/"):
                resolved = ROOT / candidate.lstrip("/")
            else:
                resolved = path.parent / candidate
            if not resolved.exists():
                err(f"{rel} 链接指向的文件不存在：{target}")


def check_secrets() -> None:
    for path in iter_files():
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = read_text(path)
        if text is None:
            continue
        rel = path.relative_to(ROOT).as_posix()
        if CONFLICT_RE.search(text):
            err(f"{rel} 含未解决的版本冲突标记")
        for label, pattern, level in SECRET_RULES:
            if pattern.search(text):
                (err if level == "error" else warn)(f"{rel} 疑似{label}外泄")
        for match in ASSIGN_RE.finditer(text):
            quoted = re.search(r"[\"']([^\"']+)[\"']", match.group(0))
            inner = quoted.group(1).strip().lower() if quoted else ""
            if not inner or any(token in inner for token in PLACEHOLDERS):
                continue
            warn(f"{rel} 疑似硬编码凭据赋值：{match.group(1)}")


def main() -> int:
    print(f"== {REPO_NAME} · 文档仓库自检 ==")
    check_required()
    check_bilingual()
    check_markdown()
    check_secrets()

    for item in errors:
        print(f"ERROR  {item}")
    for item in warnings:
        print(f"WARN   {item}")
    print(f"\n结果：{len(errors)} error(s), {len(warnings)} warning(s)")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fp:
            fp.write(f"## {REPO_NAME} 文档自检\n\n")
            fp.write(f"- error: {len(errors)}\n- warning: {len(warnings)}\n")
            for item in errors:
                fp.write(f"- ERROR: {item}\n")
            for item in warnings:
                fp.write(f"- WARN: {item}\n")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
