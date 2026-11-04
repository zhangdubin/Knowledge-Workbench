"""测试专用的护栏：绝不允许测试碰到线上库

为什么需要这个文件：
    这次出过一次真实的数据事故 —— 「线上 60 条基因（dna_gene）被清空」，而且是两次。

    原因链条：
      1. app/config.py 的默认库路径是**相对路径**（./data/kb.db），
         相对的是**当前工作目录**；
      2. 测试想切到内存库，用的是 os.environ.setdefault("KB_DATABASE_URL", ...)
         —— 而 app/config.py 的 _promote_kb_env() 只在**无前缀**的 DATABASE_URL
         不存在时才把 KB_DATABASE_URL 提升上去。容器里 compose 已经设了
         DATABASE_URL，所以那个 setdefault 根本没生效；
      3. app/config.py 在 **import 时**就把 Settings() 固化了，
         之后再改环境变量已经太晚；
      4. 于是测试连的是容器里的 ./data/kb.db —— 也就是**线上库**
         （bind mount 到宿主 data/kb.db）；
      5. test_dna_learning.py 的 tearDown 里的 delete 语句就清空了线上基因表。

    教训：「测试不会碰到生产数据」不能靠测试作者记得写对环境变量。
    护栏必须由基础设施强制 —— 所以这个模块做的事是：
      - 先把环境变量**无条件**设成临时目录（不是 setdefault）；
      - 再断言最终解析出来的库路径确实落在临时目录里；
      - 不满足就直接抛错，让测试**立刻失败**而不是默默清空线上库。

怎么用：
    在每个测试文件里，**第一行 import 应用模块之前**写：

        import _guard
        _guard.use_temp_db()

    注意 import 顺序很要紧：护栏必须在 app.config 被 import 之前跑完。
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


def use_temp_db() -> str:
    """把数据库与文件目录指到临时目录，并断言确实生效

    返回临时目录路径。
    """
    tmp = tempfile.mkdtemp(prefix="kb-test-")
    db_path = Path(tmp) / "kb.db"
    # 注意：用的是**无前缀**的变量名，而且是无条件赋值。
    #   KB_DATABASE_URL 只有在 DATABASE_URL 不存在时才会被提升，
    #   容器里 DATABASE_URL 早就被 compose 设好了 —— 用 setdefault 等于没设。
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///" + str(db_path)
    os.environ["DATA_DIR"] = str(Path(tmp) / "data")
    os.environ["FILE_STORE_DIR"] = str(Path(tmp) / "files")
    os.environ["FILE_STORE"] = "fs"
    os.environ["AUTH_ENABLED"] = "false"
    os.environ["MAINTENANCE_ENABLED"] = "false"
    return tmp


def assert_test_db() -> None:
    """断言当前生效的库确实是测试库（不是线上库）

    什么时候需要单独调：
        护栏设置完环境变量、但在应用模块 import 之前，
        settings 可能还没被固化 —— 这时断言不了。
        所以这个函数要在 **app.config import 之后** 再调一次。

    断言不过就直接抛 RuntimeError：
        宁可测试直接报错，也不能让它「跑起来了」——
        跑起来就意味着可能已经在删线上数据了。
    """
    from app import config  # 延迟 import：必须在环境变量设好之后

    url = str(config.settings.database_url)
    tmp_markers = ("kb-test-", ":memory:", "/tmp/", "tmp")
    if not any(m in url for m in tmp_markers):
        raise RuntimeError(
            "测试拒绝运行：当前生效的数据库是 "
            + url
            + "，看起来不是临时库。\n"
            "测试如果连到线上库，tearDown 里的清理语句会删掉生产数据。\n"
            "请先调用 _guard.use_temp_db()（必须在 import app.config 之前）。"
        )
