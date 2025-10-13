
---

# 0) Доступ и общая информация

* **Домен:** `garantcoin.io`
* **VPS (SSH):**

  ```
  ssh root@89.150.59.196
  пароль: tL2uF4gI1voS
  ```

* **ОС:** Ubuntu 24.04 LTS
* **Веб-сервер:** Apache 2.4
* **PHP:** 8.3 + необходимые модули
* **БД:** MariaDB (локальная), кодировка по умолчанию utf8mb4/utf8mb4_unicode_ci
* **Фаервол:** UFW (80/443/22 разрешены)
* **ISP manager:** https://89.150.59.196:1500/ispmgr
* **ISP manager login:** root
* **ISP manager pass:** tL2uF4gI1voS

---

# 1) Структура проекта и пути

* **Корень сайта (DocumentRoot):**

  ```
  /var/www/richexchanger
  ```


* **Конфиг Apache (виртуальный хост):**

  ```
  /etc/apache2/sites-available/garantcoin.io.conf
  ```

  Активируется `a2ensite garantcoin.io.conf`, дефолтный 000-default отключён.

* **Логи именно этого сайта:**

  ```
  /var/log/apache2/garantcoin.io_error.log
  /var/log/apache2/garantcoin.io_access.log
  ```

* **Где лежит rk-config.php (конфиг скрипта):**

  ```
  /var/www/richexchanger/rk-config.php
  ```

---

# 2) Apache + виртуальный хост

Файл уже подготовлен (типовой вид):

```apache
<VirtualHost *:80>
    ServerName garantcoin.io
    ServerAlias www.garantcoin.io

    DocumentRoot /var/www/richexchanger

    <Directory /var/www/richexchanger>
        AllowOverride All
        Require all granted
        Options -Indexes
    </Directory>

    Header always set X-Content-Type-Options "nosniff"
    Header always set Referrer-Policy "strict-origin-when-cross-origin"
    Header always set X-Frame-Options "SAMEORIGIN"
    Header always set Permissions-Policy "geolocation=(), microphone=(), camera=()"

    ErrorLog ${APACHE_LOG_DIR}/garantcoin.io_error.log
    CustomLog ${APACHE_LOG_DIR}/garantcoin.io_access.log combined
</VirtualHost>
```

# 3) PHP 8.3 и ionCube

* Установлены пакеты PHP 8.3 и расширения (mbstring, xml, zip, curl, gd, mysql, cli, common).
* **ionCube Loader** скопирован в каталог расширений PHP и подключён ini-файлами.

# 4) База данных (создано)

Созданы БД и учётка приложения:

* **База:** `exchanger_db`
* **Пользователь:** `exchanger_user`
* **Пароль:** `iJU09AF12ss_xcv`


Вход в БД через root по паролю: 
* **Пароль:** `juhY&^twgsg12A`


# 5) Конфиг скрипта (`rk-config.php`)

Файл создан и заполнен базовыми настройками:

```php
define('RK_DB_PREFIX', 'bexch');              // префикс таблиц (можно менять до установки)
define('RK_DB_NAME', 'exchanger_db');
define('RK_DB_USER', 'exchanger_user');
define('RK_DB_PASSWORD', 'iJU09AF12ss_xcv');
define('RK_DB_HOST', 'localhost');

define('RK_SITEURL', 'https://garantcoin.io/');  // полный URL со слешем в конце
define('RK_LOGINPAGE_PATH', 'adminlogin');       // путь страницы логина админов

define('RK_ADMIN_LANG', 'ru_RU');
define('RK_SITE_LANG', 'ru_RU');
// define('RK_ENABLE_LANGS', 'ru_RU, en_US'); // включить при мультиязычии

define('RK_CRON_HASH', '3mQkXF2M');
define('RK_NONCE_SALT', 'y3uvQH^*g1UPBrMo');
define('RK_LOGIN_SALT', 'PCi0TDhVw2LYe*rV');
define('RK_TIME_SALT', 'juGGruRYhbUC)qou');
define('RK_AUTH_SALT', '620&iD#DmWCC4(Wx');
define('RK_AUTHCOOKIE_SALT', 'N&&W)vc5f6zdiDjO');
define('RK_EXT_SALT', 'tgglMyqJ@I)Zg5cTBJHt9C@uWMkbAEgz');
define('RK_PASS_SALT', '1eQYLI#XPil^H&YzF6s4%!F&bJW2eER9');
```


## Резюме: что уже сделано

* Подготовлен веб-стек (Apache 2.4 + PHP 8.3 + модули).
* Установлен и подключён ionCube Loader.
* Созданы БД и учётка приложения:

  * DB: `exchanger_db`
  * USER: `exchanger_user`
  * PASS: `iJU09AF12ss_xcv`
  * HOST: `localhost`
  * ROOT USER: `root`
  * ROOT PASS: `juhY&^twgsg12A`
* Создан `rk-config.php` с базовыми настройками проекта (URL/БД/языки/логин-путь).
* Настроен виртуальный хост для `garantcoin.io` (HTTP; SSL — через certbot).
* Брандмауэр включён, порт 80/443/22 разрешены.

## Что осталось сделать

* Залить дистрибутив RichExchanger в `/var/www/richexchanger`.
* Привязать лицензию на домен, открыть сайт и завершить инсталляцию (создание таблиц, первый админ).
* Настроить cron (URL из админки).
---
