"""Interactive local credential setup; password is never saved or echoed."""
import getpass
import json
import secrets
from pathlib import Path
from urllib.request import Request, build_opener
from urllib.error import HTTPError, URLError
from dotenv import dotenv_values, set_key
from x2pos.client import NoRedirect, identifier, LIMIT
import subprocess

def main():
    env = Path(__file__).resolve().parents[1] / ".env"
    check = subprocess.run(["git","check-ignore","-q","--",str(env)],cwd=env.parent,
                           stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    if check.returncode != 0:
        print("Сначала исключи .env из Git. Настройка остановлена.")
        return
    current = dotenv_values(env)
    login = getpass.getpass("Логин X2POS (скрытый ввод): ")
    password = getpass.getpass("Пароль X2POS (скрытый ввод): ")
    boundary = "guardian" + secrets.token_hex(16)
    body = b""
    for name, value in (("user",login),("password",password)):
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n"
                 f"{value}\r\n").encode()
    body += f"--{boundary}--\r\n".encode()
    req = Request("https://x2pos.com/api/auth",data=body,method="POST",
                  headers={"Content-Type":f"multipart/form-data; boundary={boundary}",
                           "Accept":"application/json"})
    try:
        with build_opener(NoRedirect()).open(req,timeout=10) as response:
            raw = response.read(LIMIT+1)
        if len(raw)>LIMIT:
            raise ValueError()
        data = json.loads(raw)
        token = data.get("token") if isinstance(data,dict) else None
        if not isinstance(token,str) or not token or not token.isascii() or any(c.isspace() for c in token):
            raise ValueError()
        req = Request("https://x2pos.com/api/employee",
                      headers={"API-KEY":token,"Accept":"application/json"})
        with build_opener(NoRedirect()).open(req,timeout=10) as response:
            raw=response.read(LIMIT+1)
        if len(raw)>LIMIT:
            raise ValueError()
        employee=json.loads(raw)
        branches=employee.get("branches")
        if not isinstance(branches,list) or not branches:
            raise ValueError()
        branches=[identifier(b) for b in branches]
        branch=str(employee.get("current_branch_id") or "")
        if branch not in branches:
            print("Доступные ID филиалов: "+", ".join(branches))
            branch=input("ID нужного филиала: ").strip()
        if branch not in branches:
            raise ValueError()
        owner=current.get("X2POS_OWNER_ID") or current.get("KASPI_OWNER_ID")
        if not owner:
            owner=input("Твой числовой Telegram ID: ").strip()
        values={"X2POS_API_KEY":token,"X2POS_BRANCH_ID":branch,
                "X2POS_USER_ID":identifier(employee.get("user_id")),
                "X2POS_OWNER_ID":identifier(owner)}
        for name,value in values.items():
            set_key(str(env),name,value)
        print("Ключ и доступ к филиалу проверены. Настройки сохранены в .env. Пароль не сохранён.")
    except (HTTPError,URLError,OSError,ValueError,TypeError,AttributeError):
        print("X2POS не подтвердил доступ. Настройки не сохранены.")
    except Exception:
        print("Настройка не завершена. Проверь локальный файл .env.")

if __name__=="__main__":
    main()
