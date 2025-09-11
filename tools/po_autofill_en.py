import re
import argparse
from pathlib import Path

# Словарь быстрых переводов (добавим базовые из навигации и часто встречающиеся)
MAP = {
    "Главная": "Home",
    "Личный кабинет": "Dashboard",
    "Настройки": "Settings",
    "Сменить пароль": "Change password",
    "Email-адреса": "Email addresses",
    "Безопасность (2FA)": "Security (2FA)",
    "Удалить аккаунт": "Delete account",
    "Выйти": "Log out",
    "Войти": "Log in",
    "Регистрация": "Sign up",
    "Забыли пароль?": "Forgot password?",
    "Вы вошли как": "You are logged in as",
    "Админка": "Admin",
    "Анонимный пользователь": "Guest",

    "Криптообменник": "Crypto exchange",
    "Быстрый и безопасный обмен криптовалют.": "Fast and secure cryptocurrency exchange.",
    "Начать обмен": "Start exchange",
    "Узнать больше": "Learn more",

    "Сумма": "Amount",
    "Продолжить": "Continue",
    "Отмена": "Cancel",
    "Сохранить": "Save",
    "Удалить": "Delete",
    "Поиск": "Search",
    "Подтвердить": "Confirm",
    "Назад": "Back",
    "Далее": "Next",
}

ENTRY_RE = re.compile(r'(?ms)^msgid\s+"(.*?)"\s*\nmsgstr\s+"(.*?)"\s*$')

def fill_po(po_path: Path, apply: bool):
    text = po_path.read_text(encoding="utf-8")
    changed = False
    def repl(m):
        nonlocal changed
        msgid = m.group(1)
        msgstr = m.group(2)
        if msgid in MAP and (not msgstr):
            new = f'msgid "{msgid}"\nmsgstr "{MAP[msgid]}"'
            changed = True
            return new
        return m.group(0)

    new_text = ENTRY_RE.sub(repl, text)
    if changed and apply:
        po_path.write_text(new_text, encoding="utf-8")
    return changed

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--po", required=True, help="Path to locale/en/LC_MESSAGES/django.po")
    ap.add_argument("--apply", action="store_true", help="Write changes to file")
    args = ap.parse_args()

    po = Path(args.po)
    if not po.exists():
        print(f"File not found: {po}")
        return

    changed = fill_po(po, args.apply)
    if changed:
        print("PO updated.")
    else:
        print("No changes (maybe already filled or msgids differ).")

if __name__ == "__main__":
    main()
