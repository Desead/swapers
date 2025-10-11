from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter

from app_market.providers.numeric import UA

# Единый session для всех провайдеров (без встроенных ретраев — они в базовом классе)
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": UA,
    "Accept": "application/json",
    "Accept-Encoding": "gzip",
})

# Чуть больше коннекшенов в пуле — полезно, если провайдеры будут вызываться параллельно
_adapter = HTTPAdapter(pool_connections=20, pool_maxsize=50, max_retries=0)
SESSION.mount("https://", _adapter)
SESSION.mount("http://", _adapter)
