from .base import *

# Автовыбор оверрайдов по DEBUG из base.py
if DEBUG:
    from .dev import *
else:
    from .prod import *
