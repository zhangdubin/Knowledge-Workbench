"""路由模块集合

**这里不做路由注册。** 真正的注册在 `main.py`：
需要登录的路由统一放在 PROTECTED 列表里 include_router，
并统一挂上 `current_principal` 依赖；公开路由（auth）单独 include。

把注册集中在一处，是为了让人一眼看清「哪些路径需要登录」——
注册散在各个包里，早晚会漏掉一个，而漏掉的那个接口
在鉴权开启时是 401、关闭时却是全开的，这种差异极难在测试里发现。

这里只把各路由模块显式 import 出来，
是为了让「from .routers import xxx」这种包级写法成立，
不必依赖 Python 的「子模块按需导入」兜底 ——
后者在名字写错时报的是 AttributeError，
看半天也不知道是哪个模块名拼错了。
"""
from . import dna  # noqa: F401  养料 DNA（只读）
