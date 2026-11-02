"""记录检索随数据量增长的实测：LIKE 全表扫描 vs 倒排索引（含候选池）

为什么要有这个：用户明确说了「后期经验数据多了估计查询会更慢」。
光说「加了索引就快了」不算数 —— 要给出**量化的增长曲线**，
才能承诺「数据涨 10 倍，检索慢多少」。

量两种关键词，因为它们的代价完全不同：
  · 常见词（命中一大片）：LIKE 扫描凑够 limit 条就停，本来就快；
  · 罕见词（命中零星几条）：LIKE 扫描必须翻遍全表 ——
    这才是「经验数据越多越慢」的真实写照。

跑法（容器内）：
    docker run --rm -v "$PWD/backend/app:/app/app:ro" \
      -v "$PWD/scripts:/scripts:ro" --entrypoint python \
      kb-workbench-backend:latest /scripts/bench-retrieval-scale.py
"""
import os
import sqlite3
import statistics
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.environ.get("KB_BACKEND_DIR") or os.path.join(REPO, "backend")
if not os.path.isdir(os.path.join(BACKEND, "app")) and os.path.isdir("/app/app"):
    BACKEND = "/app"
sys.path.insert(0, BACKEND)

from app.services.docindex import seg_bigram_sql  # type: ignore

# 关键词要分两种，因为它们的代价完全不同：
#   常见词：LIKE 扫描凑够 limit 条就停，代价低；
#   罕见词：LIKE 扫描必须翻遍全表才凑不够 —— 这才是「经验数据多了就越慢」
#           的真实写照（用户搜的往往就是罕见词）。
COMMON = "采购"
RARE = "绝密档案"


def build_db(path: str, n: int) -> None:
    con = sqlite3.connect(path)
    con.execute("create table entity_record(id integer primary key, "
                "entity_type_id integer, search_text text)")
    con.execute("create table entity_type(id integer primary key, key text)")
    con.execute("insert into entity_type(id, key) values (1, 'note')")
    words = ["采购", "投标", "客户", "深圳", "合同", "验收", "交付", "报价",
             "预算", "评审", "整改", "复盘", "知识库", "经验", "教训"]
    rows = []
    for i in range(n):
        w1 = words[i % len(words)]
        w2 = words[(i * 7 + 3) % len(words)]
        # 每 500 条混一条罕见词，模拟「数量少但重要」的记录
        rare = " 绝密档案" if (i % 500 == 0) else ""
        rows.append((i + 1, 1, f"{w1} {w2} 第{i}号记录 备注{rare}"))
    con.executemany("insert into entity_record values (?,?,?)", rows)
    con.commit()
    con.close()


def build_fts(path: str) -> None:
    con = sqlite3.connect(path)
    con.create_function("kb_seg_bigram", 1, seg_bigram_sql, deterministic=True)
    con.execute("create virtual table record_fts using fts5("
                "body, tokenize='unicode61 remove_diacritics 2')")
    con.execute("""create trigger record_fts_ai after insert on entity_record begin
      insert into record_fts(rowid, body) values (new.id, kb_seg_bigram(ifnull(new.search_text,'')));
    end""")
    con.execute("""create trigger record_fts_ad after delete on entity_record begin
      delete from record_fts where rowid = old.id;
    end""")
    con.execute("""create trigger record_fts_au after update of search_text on entity_record begin
      delete from record_fts where rowid = old.id;
      insert into record_fts(rowid, body) values (new.id, kb_seg_bigram(ifnull(new.search_text,'')));
    end""")
    con.execute("insert into record_fts(rowid, body) "
                "select id, kb_seg_bigram(ifnull(search_text,'')) from entity_record")
    con.commit()
    con.close()


def timeit(fn, reps=15):
    xs = []
    for _ in range(reps):
        t0 = time.perf_counter()
        fn()
        xs.append((time.perf_counter() - t0) * 1000)
    xs.sort()
    return statistics.median(xs), xs[int(len(xs) * 0.95) - 1]


def main():
    print(f"{'记录数':>8} | {'LIKE 全表扫 p50':>16} | {'倒排索引 p50':>14} | "
          f"{'LIKE p95':>10} | {'索引 p95':>10} | 提速")
    print("-" * 92)
    for n in (200, 2000, 20000, 100000):
        d = tempfile.mkdtemp(prefix="kb-scale-")
        path = os.path.join(d, "scale.db")
        build_db(path, n)
        build_fts(path)
        con = sqlite3.connect(path)
        con.create_function("kb_seg_bigram", 1, seg_bigram_sql, deterministic=True)

        def like_scan(kw):
            k = "%" + kw + "%"
            con.execute(
                "select r.id from entity_record r "
                "join entity_type t on t.id = r.entity_type_id "
                "where r.search_text like ? limit 50", (k,)).fetchall()

        def fts_scan(kw):
            # 复刻 record_search 的真实逻辑：候选池 + 装满就退回扫描
            pool = 200
            cands = con.execute(
                "select rowid from record_fts where record_fts match ? limit ?",
                (kw, pool)).fetchall()
            if len(cands) >= pool:
                like_scan(kw)
                return
            con.execute(
                "select r.id from entity_record r "
                "join entity_type t on t.id = r.entity_type_id "
                "where r.id in (select rowid from record_fts "
                "where record_fts match ? limit ?) "
                "and r.search_text like ? limit 50",
                (kw, pool, "%" + kw + "%")).fetchall()

        print(f"--- {n} 条记录 ---")
        for label, kw in (("常见词", COMMON), ("罕见词", RARE)):
            like_scan(kw)
            fts_scan(kw)
            lp50, lp95 = timeit(lambda: like_scan(kw))
            fp50, fp95 = timeit(lambda: fts_scan(kw))
            print(f"  {label} {kw:<8} LIKE p50={lp50:>8.2f}ms p95={lp95:>8.2f}ms | "
                  f"倒排 p50={fp50:>7.2f}ms p95={fp95:>7.2f}ms | "
                  f"提速 {lp50 / max(fp50, 0.001):>6.1f}×")
        con.close()


if __name__ == "__main__":
    main()
