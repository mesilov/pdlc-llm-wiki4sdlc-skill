"""Opt-in, read-only forge diagnostics. Never publish client/API error output."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import quote, urlsplit


CHECKS = ("target", "cli", "auth", "repository", "issues", "pull_requests", "permissions", "write")
PUBLIC_PROVIDERS = {"github.com": "github", "gitlab.com": "gitlab"}
SAFE_NAME = re.compile(r"[A-Za-z0-9_.-]+")
SAFE_REMOTE = re.compile(r"[A-Za-z0-9_./-]+")
SAFE_HOST = re.compile(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?")
HTTP_ERROR = re.compile(
    r"\b(?:HTTP(?:/[0-9.]+)?[ :]+|status(?: code)?[ :]+)(401|403|404)\b|"
    r"\b(401|403|404)[ :]+(?:Unauthorized|Forbidden|Not Found)\b", re.IGNORECASE)
NETWORK_ERROR = re.compile(r"connection|network|no such host|resolve host|TLS|certificate|dial tcp|DNS|proxy", re.IGNORECASE)
FAILURES = {
    "timeout": "Таймаут вызова клиента",
    "unusable_client": "Клиент не удалось запустить",
    "unauthorized": "API вернул HTTP 401: авторизация не подтверждена",
    "forbidden": "API вернул HTTP 403: доступ запрещён",
    "not_found": "API вернул HTTP 404: ресурс недоступен или отсутствует",
    "network_error": "Сетевая ошибка клиента",
    "client_error": "Клиент завершился с ошибкой",
    "invalid_json": "Ответ API не является корректным JSON",
    "invalid_response": "Ответ API имеет неподходящий тип или структуру",
    "identity_mismatch": "Ответ API не соответствует выбранному хосту или репозиторию",
    "feature_disabled": "Функция отключена в выбранном репозитории",
}


def diagnostic_environment():
    """Keep auth tokens, discard target routing, prompts, logging and pager overrides."""
    discarded = {
        "GH_HOST", "GH_REPO", "GH_DEBUG", "GH_PAGER", "GH_BROWSER", "GH_EDITOR", "GH_FORCE_TTY",
        "GLAB_HOST", "GLAB_REPO", "GLAB_DEBUG", "GLAB_DEBUG_HTTP", "GLAB_PAGER", "GLAB_BROWSER", "GLAB_EDITOR",
        "GITLAB_HOST", "GITLAB_API_HOST", "GITLAB_REPO", "GITLAB_URI", "GITLAB_SUBFOLDER",
        "GLAB_API_PROTOCOL", "API_PROTOCOL", "GL_HOST", "DEBUG", "HTTP_DEBUG",
        "PAGER", "EDITOR", "VISUAL", "BROWSER", "CLICOLOR_FORCE",
    }
    env = {key: value for key, value in os.environ.items()
           if key not in discarded and not key.startswith("GIT_")}
    env.update({"GH_PROMPT_DISABLED": "1", "GLAB_PROMPT_DISABLED": "1", "CI": "1",
                "GH_NO_UPDATE_NOTIFIER": "1", "GLAB_CHECK_UPDATE": "false", "GLAB_ENABLE_CI_AUTOLOGIN": "false",
                "NO_COLOR": "1",
                "TERM": "dumb", "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0",
                "GIT_CONFIG_NOSYSTEM": "1"})
    return env


def resolve_client(name):
    executable = shutil.which(name)
    # PATH is relative to the caller, not the project's cwd used by subprocess.run.
    return str(Path(executable).absolute()) if executable else None


def invoke(executable, arguments, root, timeout, env, *, empty_config_ok=False):
    try:
        result = subprocess.run([executable, *arguments], cwd=root, env=env,
                                stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except OSError:
        return None, "unusable_client"
    if empty_config_ok and result.returncode == 1 and not result.stdout and not result.stderr:
        return "", None
    if result.returncode:
        # Inspect only known markers; output and exception text never enter checks.
        output = result.stderr + "\n" + result.stdout
        match = HTTP_ERROR.search(output)
        if match:
            return None, {"401": "unauthorized", "403": "forbidden", "404": "not_found"}[match[1] or match[2]]
        return None, "network_error" if NETWORK_ERROR.search(output) else "client_error"
    return result.stdout, None


def parse_remote(value):
    """Accept HTTPS/SSH transport syntax; reject credential-bearing or unsafe URLs."""
    if not value or any(character.isspace() or ord(character) < 32 for character in value):
        return None
    try:
        if "://" in value:
            parsed = urlsplit(value)
            if parsed.scheme not in ("https", "ssh") or parsed.query or parsed.fragment or parsed.password:
                return None
            if parsed.scheme == "https" and parsed.username is not None:
                return None
            host, path = parsed.hostname, parsed.path
            transport_port = parsed.port  # Validate SSH ports, but use HTTPS ports for API routing.
            if transport_port == 0:
                return None
            port = transport_port if parsed.scheme == "https" else None
        else:
            match = re.fullmatch(r"(?:[A-Za-z0-9_.-]+@)?([A-Za-z0-9.-]+):(.+)", value)
            if not match:
                return None
            host, path = match.groups()
            port = None
        if not host or not SAFE_HOST.fullmatch(host.lower()):
            return None
        path = path.removeprefix("/").removesuffix(".git")
        parts = path.split("/")
        if len(parts) < 2 or any(not SAFE_NAME.fullmatch(part) or part in (".", "..") for part in parts):
            return None
        if port is not None and port != 443:
            host += ":" + str(port)
        return host.lower(), path
    except ValueError:
        return None


def select_target(root, remote, provider, timeout, env):
    if not (root / ".git").exists():
        return None, "no_checkout", "У проекта нет собственной границы Git (.git)"
    git = resolve_client("git")
    if not git:
        return None, "missing_git", "Git не найден в PATH"
    output, error = invoke(git, ["rev-parse", "--show-toplevel"], root, timeout, env)
    if error:
        return None, error, "Не удалось проверить Git checkout целевого проекта"
    try:
        same_root = Path(output.strip()).resolve() == root.resolve()
    except (OSError, RuntimeError, ValueError):
        same_root = False
    if not same_root:
        return None, "wrong_checkout", "Git checkout не совпадает с корнем целевого проекта"
    output, error = invoke(git, ["config", "--null", "--show-scope", "--get-regexp", r"^remote\..*\.url$"],
                           root, timeout, env, empty_config_ok=True)
    if error:
        return None, error, "Не удалось прочитать fetch remotes целевого Git checkout"
    # Ignore global/system remotes; include worktree-scoped URLs without resolving
    # insteadOf rules that could silently redirect the selected API target.
    remotes = {}
    fields = output.split("\0")[:-1] if output.endswith("\0") else []
    if output and (not output.endswith("\0") or len(fields) % 2):
        return None, "invalid_remote", "Git remote имеет неподходящую структуру"
    for index in range(0, len(fields), 2):
        scope, item = fields[index:index + 2]
        if scope not in ("local", "worktree"):
            continue
        key, separator, value = item.partition("\n")
        if not separator:
            return None, "invalid_remote", "Git remote имеет неподходящую структуру"
        name = key.removeprefix("remote.").removesuffix(".url")
        if not SAFE_REMOTE.fullmatch(name):
            return None, "invalid_remote", "Git remote имеет небезопасное имя"
        remotes.setdefault(name, []).append(value)
    if remote is None:
        if len(remotes) != 1:
            return None, "ambiguous_remotes" if remotes else "no_remote", "Нужен один Git remote или явный --forge-remote NAME"
        remote = next(iter(remotes))
    elif remote not in remotes:
        return None, "missing_remote", "Указанный Git remote не найден в целевом checkout"
    urls = remotes[remote]
    if len(urls) != 1:
        return None, "ambiguous_urls", "У выбранного remote несколько fetch URLs; выберите однозначный remote"
    parsed = parse_remote(urls[0])
    if parsed is None:
        return None, "invalid_url", "Fetch URL не поддерживается или содержит небезопасные компоненты"
    host, repository = parsed
    automatic = PUBLIC_PROVIDERS.get(host.split(":", 1)[0])
    if provider is None:
        provider = automatic
    elif automatic and automatic != provider:
        return None, "provider_mismatch", "Указанный provider не соответствует публичному хосту"
    if provider is None:
        return None, "unknown_provider", "Для корпоративного хоста укажите --forge-provider github|gitlab"
    if provider == "github" and len(repository.split("/")) != 2:
        return None, "invalid_repository", "GitHub remote должен указывать owner/repository"
    return {"remote": remote, "provider": provider, "host": host, "repository": repository}, None, None


def client_version(output, provider):
    lines = output.splitlines()
    if not lines:
        return None
    prefix = r"gh version" if provider == "github" else r"glab(?: version)?"
    # Distribution build metadata may contain spaces; never return its contents.
    match = re.fullmatch(prefix + r" v?([0-9]+\.[0-9]+\.[0-9]+)(?: \([^()\r\n]+\))?", lines[0].strip())
    return match[1] if match else None


def web_identity(value, host, repository=None, *, case_insensitive=False):
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
        expected = urlsplit("https://" + host)
        port = parsed.port if parsed.port not in (None, 443 if parsed.scheme == "https" else 80) else None
        if (parsed.scheme not in ("https", "http") or parsed.hostname != expected.hostname or
                parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment or
                port != expected.port):
            return False
        path = parsed.path.rstrip("/")
        if case_insensitive:
            path = path.lower()
            repository = repository.lower() if repository is not None else None
        return repository is None or path == "/" + repository
    except ValueError:
        return False


def api(executable, endpoint, target, root, timeout, env):
    output, error = invoke(executable, ["api", "--hostname", target["host"], "--method", "GET", endpoint],
                           root, timeout, env)
    if error:
        return None, error
    try:
        return json.loads(output), None
    except (ValueError, RecursionError):
        return None, "invalid_json"


def permissions_claims(value, provider):
    if not isinstance(value, dict):
        return {}
    if provider == "github":
        return {name: value[name] for name in ("admin", "maintain", "push", "triage", "pull")
                if type(value.get(name)) is bool}
    claims = {}
    for name in ("project_access", "group_access"):
        access = value.get(name)
        level = access.get("access_level") if isinstance(access, dict) else None
        if type(level) is int and level in (0, 5, 10, 15, 20, 30, 40, 50, 60):
            claims[name] = level
    return claims


def feature_enabled(repository, provider, name):
    if provider == "github":
        if name == "pull_requests":
            return True
        return repository.get("has_issues") if type(repository.get("has_issues")) is bool else None
    prefix = "issues" if name == "issues" else "merge_requests"
    if repository.get(prefix + "_access_level") == "disabled":
        return False
    value = repository.get(prefix + "_enabled")
    if type(value) is bool:
        return value
    access = repository.get(prefix + "_access_level")
    return True if access in ("enabled", "private") else None


def valid_list(values, provider):
    if not isinstance(values, list):
        return False
    number = "number" if provider == "github" else "iid"
    return all(isinstance(value, dict) and
               all(type(value.get(field)) is int and value[field] > 0 for field in ("id", number))
               for value in values)


def check_forge(root, checks, add, *, remote, provider, network, required, timeout):
    severity = "error" if required else "warning"
    emitted = set()
    env = diagnostic_environment()

    def record(name, status, message, **details):
        emitted.add(name)
        add(checks, "forge." + name, status, message, **details)

    def failure(name, reason, remedy):
        record(name, severity, FAILURES[reason], reason=reason, remedy=remedy)

    def run_checks():
        target, error, message = select_target(root, remote, provider, timeout, env)
        if error:
            record("target", severity, message, reason=error,
                   remedy="Проверьте Git целевого проекта и fetch remote; при неоднозначности задайте --forge-remote, для корпоративного хоста --forge-provider")
            return
        record("target", "ok", f"Remote {target['remote']}: {target['provider']} {target['host']}/{target['repository']}", **target)
        name = "gh" if target["provider"] == "github" else "glab"
        executable = resolve_client(name)
        if not executable:
            record("cli", severity, f"{name} не найден в PATH", client=name, reason="missing_client",
                   remedy=f"Установите {name} и добавьте исполняемый клиент в PATH")
            return
        output, error = invoke(executable, ["--version"], root, timeout, env)
        if error:
            failure("cli", error, f"Проверьте {name}, его runtime и PATH")
            return
        version = client_version(output, target["provider"])
        if version is None:
            record("cli", severity, f"{name} --version не вернул распознаваемую версию",
                   reason="invalid_version", remedy=f"Проверьте установку {name} и его runtime")
            return
        record("cli", "ok", f"{name} {version}", path=executable, client=name, version=version)
        if not (network or required):
            return
        remedy = "Проверьте авторизацию CLI на выбранном хосте и права чтения API; настройку выполняйте отдельно"
        user, error = api(executable, "/user", target, root, timeout, env)
        if error:
            failure("auth", error, remedy)
            return
        account_field = "login" if target["provider"] == "github" else "username"
        web_field = "html_url" if target["provider"] == "github" else "web_url"
        if (not isinstance(user, dict) or type(user.get("id")) is not int or user["id"] <= 0 or
                not isinstance(user.get(account_field), str) or not SAFE_NAME.fullmatch(user[account_field])):
            failure("auth", "invalid_response", remedy)
            return
        if web_field in user and not web_identity(user[web_field], target["host"]):
            failure("auth", "identity_mismatch", remedy)
            return
        record("auth", "ok", "Авторизация подтверждена чтением /user на выбранном хосте")
        endpoint = ("repos/" + target["repository"] if target["provider"] == "github"
                    else "projects/" + quote(target["repository"], safe=""))
        repository, error = api(executable, endpoint, target, root, timeout, env)
        if error:
            failure("repository", error, remedy)
            return
        identity_field = "full_name" if target["provider"] == "github" else "path_with_namespace"
        if (not isinstance(repository, dict) or not isinstance(repository.get(identity_field), str) or
                not isinstance(repository.get(web_field), str)):
            failure("repository", "invalid_response", remedy)
            return
        github = target["provider"] == "github"
        identity_matches = (repository[identity_field].lower() == target["repository"].lower() if github
                            else repository[identity_field] == target["repository"])
        if not identity_matches or not web_identity(repository[web_field], target["host"], target["repository"], case_insensitive=github):
            failure("repository", "identity_mismatch", remedy)
            return
        record("repository", "ok", "Подтверждено чтение API выбранного репозитория и его identity")
        claims = permissions_claims(repository.get("permissions"), target["provider"])
        record("permissions", "ok" if claims else "skipped",
               "Заявленные API права: " + json.dumps(claims, ensure_ascii=False, sort_keys=True) + "; запись не проверялась" if claims
               else "API не сообщил распознаваемые права; запись не проверялась", permissions=claims)
        for feature, suffix in (("issues", "issues"), ("pull_requests", "pulls" if target["provider"] == "github" else "merge_requests")):
            enabled = feature_enabled(repository, target["provider"], feature)
            if enabled is not True:
                failure(feature, "feature_disabled" if enabled is False else "invalid_response",
                        "Проверьте настройки функции и права чтения выбранного репозитория")
                continue
            values, error = api(executable, endpoint + "/" + suffix + "?per_page=1", target, root, timeout, env)
            if error:
                failure(feature, error, remedy)
            elif not valid_list(values, target["provider"]):
                failure(feature, "invalid_response", remedy)
            else:
                record(feature, "ok", "Подтверждено чтение " + ("issues" if feature == "issues" else "PR/MR") + " через API (пустой список допустим)")

    run_checks()
    for name in CHECKS:
        if name not in emitted:
            message = ("Запись не проверялась; чтение и заявленные API права не подтверждают запись" if name == "write"
                       else "Сетевая проверка отключена; включите --forge-network или --require-forge" if name in ("auth", "repository", "issues", "pull_requests", "permissions") and not (network or required)
                       else "Проверка пропущена: необходимые предыдущие проверки не подтвердились")
            record(name, "skipped", message)
