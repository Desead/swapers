# Swapers

Коротко о проекте: Полностью автоматический обменник криптовалют.

# Алгоритм входа и добавления новых сотрудников
- войдите суперпользователем в ЛК
- получите 2фа код и войдите в админку
- при первом входе можно/нужно изменить путь к админке и название для OTP. Эти действия требуют перезагрузки сервера
- новый пользователь регистрируется в ЛК и подтверждает свою почту
- Суперпользователь в админке новому пользователю ставит чек что он является персоналом и добавляет ему нужные роли. Без ролей в админку не пустит!
- Теперь у этого пользователя появится в ЛК актуальный путь к админке и возможность создавать 2фа код
- После привязки своего телефона и получения 2а кода можно войти в админку и увидеть только то, на что были даны права

## Быстрый старт (dev)

```bash

python -m venv .venv
. .venv/Scripts/activate  # Windows (PowerShell: .venv\Scripts\Activate.ps1)
python.exe -m pip install --upgrade pip
pip install -r .\requirements.txt
python .\manage.py makemigrations
python .\manage.py migrate
python .\manage.py createsuperuser
python .\manage.py init_roles
python .\manage.py test
pytest -q
python .\manage.py runserver


# Создать/обновить каталоги переводов
python manage.py makemessages -l ru -l de -l fr -l es -l it -l uk `
  --ignore=.venv/* --ignore=node_modules/* --no-location
# если есть переводы в JS:
python manage.py makemessages -d djangojs -l ru -l de -l fr -l es -l it -l uk `
  --ignore=.venv/* --ignore=node_modules/* --no-location

# Скомпилировать в .mo
django-admin compilemessages


```


# создать фикстуру
python manage.py dumpdata app_library.DocumentTemplate --indent 2 --output app_library/fixtures/document_templates_ru.json

# Проверить что файл создался в кодировке utf8
import json, sys
p="app_library/fixtures/document_templates_ru.json"
json.load(open(p, encoding="utf-8"))
print("OK:", p, "UTF-8")

# если он в CP1251 (типичный случай для «ANSI»)
from pathlib import Path
src = Path("app_library/fixtures/document_templates_ru.json")
dst = Path("app_library/fixtures/document_templates_ru_utf8.json")
dst.write_text(src.read_text(encoding="cp1251"), encoding="utf-8")
print("Перекодирован:", dst)

# PowerShell (перекодировать в UTF-8)
# из корня проекта, путь поправьте при необходимости
Get-Content app_library\fixtures\document_templates_ru.json -Raw -Encoding Default `
| Set-Content app_library\fixtures\document_templates_ru_utf8.json -NoNewline -Encoding UTF8
# Загрузить данные из фикстуры
python manage.py loaddata app_library/fixtures/document_templates_ru_utf8.json