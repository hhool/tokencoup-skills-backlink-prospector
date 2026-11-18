#!/usr/bin/env python3
"""统一身份配置读取：邮箱 / 应用专用密码 / 站点信息。

唯一来源：~/.sextant/poki2-gmail.env（权限 600）
环境变量优先于文件，便于临时覆盖或 CI 注入。

用法：
  from identity import identity
  ident = identity()
  ident["email"], ident["has_password"], ident["password"]
"""
import os
import re

ENV_FILE = os.path.expanduser("~/.sextant/poki2-gmail.env")
DEFAULT_ADDRESS = "poki2.online@gmail.com"


def _parse(path):
    out = {}
    if not os.path.exists(path):
        return out
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r'(?:export\s+)?([A-Z0-9_]+)\s*=\s*["\']?([^"\']*)["\']?\s*$', line)
            if m:
                out[m.group(1)] = m.group(2).strip()
    return out


def identity():
    f = _parse(ENV_FILE)
    email = (os.environ.get("POKI2_GMAIL_ADDRESS")
             or f.get("POKI2_GMAIL_ADDRESS") or DEFAULT_ADDRESS).strip()
    password = (os.environ.get("POKI2_GMAIL_APP_PASSWORD")
                or f.get("POKI2_GMAIL_APP_PASSWORD") or "").strip()
    return {
        "email": email,
        "password": password,
        "has_password": bool(password),
        "env_file": ENV_FILE,
        "env_file_exists": os.path.exists(ENV_FILE),
    }


def require_password():
    """返回 (ident, None) 或 (ident, 错误说明)。"""
    ident = identity()
    if ident["has_password"]:
        return ident, None
    msg = ("缺少 Gmail 应用专用密码。\n"
           "  文件：%s\n"
           "  填写：export POKI2_GMAIL_APP_PASSWORD=\"16位应用专用密码\"\n"
           "  权限：chmod 600 %s\n"
           "  邮箱地址已配置为：%s" % (ENV_FILE, ENV_FILE, ident["email"]))
    return ident, msg


if __name__ == "__main__":
    i = identity()
    print("邮箱地址：%s" % i["email"])
    print("配置文件：%s（%s）" % (i["env_file"], "存在" if i["env_file_exists"] else "不存在"))
    print("应用专用密码：%s" % ("已配置" if i["has_password"] else "未配置"))
