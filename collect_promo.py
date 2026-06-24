"""
🏦 银行优惠活动 · 自动采集器
============================
从什么值得买搜索银行优惠 → AI 提取字段 → 生成 Obsidian 笔记 → 自动出图

用法:
  python collect_promo.py                         # 全量采集（需要 DEEPSEEK_API_KEY）
  python collect_promo.py --bank 建设银行          # 只搜指定银行
  python collect_promo.py --dry-run               # 预览，不写入文件
  python collect_promo.py -g                      # 采集 + 自动生成卡片
  python collect_promo.py --from-file test.json   # 从本地文件读取（离线测试）

依赖: pip install openai requests beautifulsoup4
"""

import sys
import io as _io
import os
import json
import time
import re
import argparse
import subprocess
import datetime

# 确保中文输出不乱码
sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# ═══════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VAULT_PATH = os.environ.get("BANK_PROMO_VAULT", r"F:\CC Tools\酱酱&小克的实验室\银行优惠")
TEMPLATE_PATH = os.path.join(VAULT_PATH, "模板", "活动卡片模板.md")

# 银行别名映射（复用 generate_card.py 的逻辑）
BANK_ALIAS = {
    "中行": "中国银行", "农行": "农业银行", "建行": "建设银行",
    "交行": "交通银行", "招行": "招商银行", "工行": "工商银行",
    "邮储": "邮储银行", "民生": "民生银行", "浦发": "浦发银行",
    "兴业": "兴业银行", "中信": "中信银行", "平安": "平安银行",
    "光大": "光大银行", "广发": "广发银行", "华夏": "华夏银行",
    "浙商": "浙商银行", "北京": "北京银行", "渤海": "渤海银行",
    "九江": "九江银行", "上饶": "上饶银行", "江西": "江西银行",
    "赣州": "赣州银行",
}

# 23 家银行全称列表
ALL_BANKS = list(BANK_ALIAS.values())

# 搜索关键词模板
SEARCH_KEYWORDS = [
    "云闪付 银行 优惠",
    "信用卡 满减 优惠",
    "银行卡 活动 立减",
    "银行 支付 优惠 什么值得买",
]

# ═══════════════════════════════════════════════════
# AI 提取 Prompt
# ═══════════════════════════════════════════════════

SYSTEM_PROMPT = """你是一个专门提取中国银行优惠活动信息的助手。
你的任务是从搜索结果文本中提取结构化数据。

提取规则：
1. bank: 银行全称，如"建设银行""招商银行""工商银行"。简称自动转全称
2. title: 主标题，≤10字。**优先列出具体商户/平台/场景名，而非概括词。**
   ✅ "京东淘宝抖音立减"（保留平台名）
   ✅ "水电燃气满50减8"（保留场景细节）
   ✅ "0.1元购乘车券"（保留具体金额）
   ✅ "1分钱乘地铁"（保留场景）
   ❌ "多平台支付优惠"（丢失了哪些平台）
   ❌ "生活缴费立减"（丢失了水/电/燃气细节）
   ❌ "银行支付优惠"（太泛，毫无信息量）
3. benefit: 利益点，≤10字。**同上原则——保留具体数字、条件、平台名。**
   ✅ "满50减8元""得5元券包""首绑立减6元"
   ❌ "支付立减优惠"（丢失金额和条件）
4. region: 适用地区，未明确指出则填"全国"
5. start_date: 开始日期，格式 YYYY-MM-DD，未提及填 null
6. end_date: 结束日期，格式 YYYY-MM-DD，未提及填 null
7. link: 来源链接（保持原值）
8. tags: 2-4个标签，如["云闪付","生活缴费","信用卡"]。**注意：如果 title 因字数限制无法列出全部平台/场景，tags 里应补全。**
9. raw_description: 保留原始文本摘要（**尽量保留原文具体商户名/平台名，不要概括**）
10. confidence: "high"/"medium"/"low"
    - high: 银行、title、benefit 都明确
    - medium: 部分字段需推断
    - low: 信息模糊，仅供参考

注意事项：
- 涉及多家银行时拆分为多条记录
- title 和 benefit 必须简短（要印在卡片上），但**不要把具体名字概括成笼统词**
- benefit 优先提取具体数字（满减/折扣/返现）
- 不要编造信息，不确定填 null
- 如果根本不是银行优惠活动，返回 {"skip": true, "reason": "..."}
- 只输出 JSON 数组，不要 markdown 代码块标记"""

USER_PROMPT_TEMPLATE = """请从以下搜索结果中提取银行优惠活动信息。

结果列表：
{results}

请返回 JSON 格式：
[{{
  "bank": "银行名",
  "title": "主标题≤10字",
  "benefit": "利益点≤10字",
  "region": "地区",
  "start_date": "YYYY-MM-DD 或 null",
  "end_date": "YYYY-MM-DD 或 null",
  "link": "链接",
  "tags": ["标签"],
  "raw_description": "原文摘要",
  "confidence": "high/medium/low"
}}]
如果没有有效活动，返回 []"""


# ═══════════════════════════════════════════════════
# 函数 1: 搜索什么值得买
# ═══════════════════════════════════════════════════

def search_smzdm(bank=None, query=None, max_results=10, verbose=False):
    """
    从什么值得买搜索银行优惠信息。

    参数:
        bank: 指定银行名（可选），为空则通用搜索
        query: 自定义关键词（可选）
        max_results: 最大返回数
        verbose: 输出诊断信息

    返回:
        list[dict]: 每个 dict 含 title, url, snippet, source
    """
    results = []

    # 确定搜索关键词
    if query:
        keywords = [query]
    elif bank:
        keywords = [f"{bank} 优惠", f"{bank} 活动", f"{bank} 满减"]
    else:
        keywords = SEARCH_KEYWORDS

    # 代理支持（国内用户可在 CI 中配 HTTP_PROXY 访问中文站）
    proxies = None
    http_proxy = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
    https_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if http_proxy or https_proxy:
        proxies = {"http": http_proxy, "https": https_proxy or http_proxy}
        if verbose:
            print(f"   🌐 使用代理: {https_proxy or http_proxy}")

    try:
        import requests
        from bs4 import BeautifulSoup

        # 使用 Session 保持连接 + 完整浏览器头
        session = requests.Session()
        session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Cache-Control": "max-age=0",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        })

        for kw in keywords[:2]:  # 最多搜 2 组关键词，避免太慢
            for attempt in range(3):  # 最多重试 3 次
                try:
                    # smzdm 搜索 URL（编码关键词）
                    from urllib.parse import quote
                    url = f"https://search.smzdm.com/?c=post&s={quote(kw)}&order=time&p=1"
                    if verbose:
                        print(f"   🔍 搜索: {kw} (尝试 {attempt+1}/3)")

                    resp = session.get(url, timeout=20, proxies=proxies)
                    if verbose:
                        print(f"      HTTP {resp.status_code} | 页面大小: {len(resp.text)} 字符")

                    resp.raise_for_status()

                    # 检查是否被拦截（常见反爬页面特征）
                    if len(resp.text) < 500 or "请进行验证" in resp.text or "cf-browser-verify" in resp.text:
                        if verbose:
                            print(f"      ⚠️ 疑似反爬拦截，{'重试' if attempt < 2 else '放弃'}...")
                        if attempt < 2:
                            time.sleep(2 * (attempt + 1))
                            continue
                        break

                    soup = BeautifulSoup(resp.text, "html.parser")

                    # 多套 CSS 选择器（兼容 smzdm 改版）
                    selectors = [
                        ".feed-row-wide", ".feed-row",          # 经典 PC 版
                        ".search-result-item",                   # 备用
                        "li[class*='feed']",                     # 模糊匹配
                        ".card-group-list .card",                # 新版
                    ]
                    items = []
                    for sel in selectors:
                        items = soup.select(sel)
                        if items:
                            if verbose:
                                print(f"      ✅ 选择器 '{sel}' 匹配到 {len(items)} 条")
                            break

                    if verbose and not items:
                        print(f"      ⚠️ 无匹配结果（所有选择器均无结果）")

                    for item in items[:max_results]:
                        link_el = item.select_one("a[href]")
                        title_el = (
                            item.select_one(".feed-block-title")
                            or item.select_one(".title")
                            or item.select_one("h3 a")
                            or item.select_one("a[title]")
                            or link_el
                        )
                        snippet_el = item.select_one(
                            ".feed-block-descripe, .feed-block-extras, .desc, .summary, p"
                        )

                        if link_el and title_el:
                            href = link_el.get("href", "")
                            if not href.startswith("http"):
                                href = "https:" + href if href.startswith("//") else "https://www.smzdm.com" + href

                            results.append({
                                "title": title_el.get_text(strip=True),
                                "url": href,
                                "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
                                "source": "smzdm",
                            })

                    if results:
                        break  # 找到了就不搜下一组关键词
                    elif attempt < 2:
                        time.sleep(2 * (attempt + 1))
                        continue

                except requests.exceptions.Timeout as e:
                    if verbose:
                        print(f"      ⚠️ 超时: {e}")
                    if attempt < 2:
                        time.sleep(2 * (attempt + 1))
                    continue
                except requests.exceptions.ConnectionError as e:
                    if verbose:
                        print(f"      ⚠️ 连接失败: {e}")
                    break  # 连接失败不重试，直接试下一个关键词
                except Exception as e:
                    if verbose:
                        print(f"      ⚠️ 搜索异常: {type(e).__name__}: {e}")
                    break

            if results:
                break  # 找到结果就不搜下一组关键词

    except ImportError:
        print("   ⚠️ requests/bs4 未安装，无法在线搜索")

    # 去重（按 url）
    seen = set()
    unique = []
    for r in results:
        if r["url"] not in seen:
            seen.add(r["url"])
            unique.append(r)

    if verbose:
        print(f"   📊 搜索汇总: {len(results)} 条原始 → {len(unique)} 条去重后")

    return unique[:max_results]


# ═══════════════════════════════════════════════════
# 函数 2: 从本地文件加载搜索结果
# ═══════════════════════════════════════════════════

def load_from_file(filepath):
    """
    从本地 JSON 文件加载数据（离线测试用）。

    自动检测两种格式：
    - 原始搜索结果: [{"title":..., "url":..., "snippet":...}, ...]
      → 需要再经过 AI 提取
    - 预提取数据: [{"bank":..., "title":..., "benefit":...}, ...]
      → 直接跳过 AI 提取，进入写入流程

    返回:
        (items, is_extracted): 数据列表 + 是否已提取
    """
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        items = data
    elif isinstance(data, dict) and "results" in data:
        items = data["results"]
    else:
        raise ValueError(f"无法解析 JSON 文件: {filepath}（期望数组或含 'results' 键的对象）")

    # 检测：如果第一条含 "bank" 字段，说明是预提取数据
    is_extracted = len(items) > 0 and "bank" in items[0]

    return items, is_extracted


# ═══════════════════════════════════════════════════
# 函数 3: AI 提取结构化字段
# ═══════════════════════════════════════════════════

def extract_with_claude(raw_items, verbose=False):
    """
    调用 Claude API 从原始搜索结果中提取结构化活动信息。

    参数:
        raw_items: search_smzdm() 或 load_from_file() 返回的列表
        verbose: 是否打印详细日志

    返回:
        list[dict]: 结构化活动数据（bank, title, benefit, ...）
    """
    if not raw_items:
        print("   ⚠️ 没有搜索结果可提取")
        return []

    try:
        from openai import OpenAI
    except ImportError:
        print("   ❌ 请先安装 openai: pip install openai")
        return []

    api_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("LLM_API_KEY")
    if not api_key:
        print("   ❌ 未找到 DEEPSEEK_API_KEY 或 LLM_API_KEY 环境变量")
        print("   💡 请在终端运行（三选一）:")
        print("      $env:DEEPSEEK_API_KEY = 'sk-...'        # DeepSeek 官方")
        print("      $env:LLM_API_KEY = 'sk-...'              # 中转站 / 其他模型")
        print("      $env:LLM_BASE_URL = 'https://...'        # 中转站地址（可选）")
        return []

    base_url = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com")
    model = os.environ.get("LLM_MODEL", "deepseek-chat")
    client = OpenAI(api_key=api_key, base_url=base_url)
    all_promos = []

    # 每批最多 5 条，减少 API 调用
    batch_size = 5
    batches = [raw_items[i:i+batch_size] for i in range(0, len(raw_items), batch_size)]

    for batch_idx, batch in enumerate(batches):
        if verbose:
            print(f"   📤 发送第 {batch_idx+1}/{len(batches)} 批（{len(batch)} 条）到 AI 提取...")

        # 构造消息
        results_text = "\n---\n".join([
            f"[{i}] 标题: {item.get('title', '')}\n链接: {item.get('url', '')}\n摘要: {item.get('snippet', '')}"
            for i, item in enumerate(batch)
        ])
        user_msg = USER_PROMPT_TEMPLATE.format(results=results_text)

        # 调用 API（含重试）
        for attempt in range(3):
            try:
                response = client.chat.completions.create(
                    model=model,
                    max_tokens=2048,
                    temperature=0.1,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_msg},
                    ],
                )

                # 解析响应
                text = response.choices[0].message.content.strip()
                # 去掉可能的 markdown 代码块标记
                text = re.sub(r"^```(?:json)?\s*", "", text)
                text = re.sub(r"\s*```$", "", text)

                parsed = json.loads(text)
                if isinstance(parsed, list):
                    for item in parsed:
                        if not item.get("skip"):
                            all_promos.append(_postprocess(item))
                elif isinstance(parsed, dict) and not parsed.get("skip"):
                    all_promos.append(_postprocess(parsed))

                break  # 成功，跳出重试循环

            except json.JSONDecodeError as e:
                if verbose:
                    print(f"   ⚠️ JSON 解析失败: {e}")
                    print(f"   原始响应: {text[:200]}...")
                if attempt == 2:
                    print(f"   ❌ 第 {batch_idx+1} 批 JSON 解析失败（已重试 3 次），跳过")
            except Exception as e:
                err_msg = str(e)
                if "rate" in err_msg.lower() or "429" in err_msg:
                    wait = (attempt + 1) * 10
                    print(f"   ⏳ 遇到限流，{wait}秒后重试...")
                    time.sleep(wait)
                else:
                    print(f"   ❌ API 错误: {e}")
                    if attempt < 2:
                        time.sleep(3)
                    else:
                        print(f"   ❌ 第 {batch_idx+1} 批提取失败，跳过")

        # 批次间短暂停顿，避免限流
        if batch_idx < len(batches) - 1:
            time.sleep(1)

    return all_promos


def _postprocess(item):
    """后处理单条提取结果：别名映射、字段校验、默认值填充"""
    bank = item.get("bank", "")

    # 银行别名 → 全称
    if bank in BANK_ALIAS:
        bank = BANK_ALIAS[bank]
    # 模糊匹配（如 "建行" 不算在别名表里，尝试子串查找）
    if bank not in ALL_BANKS:
        for full_name in ALL_BANKS:
            if bank and (bank in full_name or full_name in bank):
                bank = full_name
                break

    item["bank"] = bank

    # title/benefit 截断到 10 字
    for field in ["title", "benefit"]:
        val = item.get(field, "")
        if val and len(val) > 10:
            item[field] = val[:10]

    # 填充默认值
    item.setdefault("region", "全国")
    item.setdefault("start_date", None)
    item.setdefault("end_date", None)
    item.setdefault("tags", [])
    item.setdefault("raw_description", "")
    item.setdefault("confidence", "medium")
    item.setdefault("link", "")

    return item


# ═══════════════════════════════════════════════════
# 文案审核 Prompt
# ═══════════════════════════════════════════════════

REVIEW_SYSTEM_PROMPT = """你是一个银行优惠文案审核助手。你的唯一任务是：

检查每条优惠活动的"主标题 + 利益点"是否丢失了原文描述中的**具体信息**：
- 商户名（如京东、淘宝、抖音、美团、饿了么、拼多多…）
- 平台名（如云闪付、微信支付、支付宝…）
- 场景细节（如水费、电费、燃气费、地铁、公交、加油、外卖…）
- 金额/折扣数字（如满50减8、1折、0.1元…）

判定标准：
- **approved**: 标题已保留关键具体信息，没有丢失重要内容
- **revised**: 丢失了关键具体信息，但能在≤10字内改写补上
  → 提供 revised_title 和/或 revised_benefit
- **needs_human**: 信息太复杂、无法在字数限制内说清楚，或你无法确定
  → 不修改，留给人来决定

改写原则：
- ≤10字硬限制
- 优先保留商户/平台名 > 场景细节 > 金额
- 不要编造原文没有的信息
- 不要过度改写——如果原文就是概括性的，就不改

只输出 JSON 数组，不要 markdown 代码块标记。"""

REVIEW_USER_TEMPLATE = """请审核以下 {count} 条银行优惠文案：

{items}

返回 JSON：
[{{
  "index": 0,
  "result": "approved|revised|needs_human",
  "revised_title": "修改后的标题（仅 revised 时填写）",
  "revised_benefit": "修改后的利益点（仅 revised 时填写）",
  "reason": "一句话说明审核理由"
}}]"""


# ═══════════════════════════════════════════════════
# 函数 3.5: 文案审核
# ═══════════════════════════════════════════════════

def review_copy(promos, verbose=False):
    """
    AI 自审文案：检查 title/benefit 是否丢失了 raw_description 中的
    具体商户名、平台名、场景名、金额数字。

    参数:
        promos: extract_with_claude() 返回的结构化活动列表
        verbose: 详细日志

    返回:
        (reviewed_promos, stats): 审核后的 promos + 统计 dict
    """
    if not promos:
        return [], {"approved": 0, "revised": 0, "needs_human": 0, "skipped": 0}

    try:
        from openai import OpenAI
    except ImportError:
        print("   ⚠️ openai 未安装，跳过文案审核")
        for p in promos:
            p["review_result"] = "skipped"
        return promos, {"approved": 0, "revised": 0, "needs_human": 0, "skipped": len(promos)}

    api_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("LLM_API_KEY")
    if not api_key:
        print("   ⚠️ 未找到 DEEPSEEK_API_KEY 或 LLM_API_KEY，跳过文案审核")
        print("   💡 文案将标记为 needs_review，待人工确认后出图")
        for p in promos:
            p["review_result"] = "skipped"
        return promos, {"approved": 0, "revised": 0, "needs_human": 0, "skipped": len(promos)}

    base_url = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com")
    model = os.environ.get("LLM_MODEL", "deepseek-chat")
    client = OpenAI(api_key=api_key, base_url=base_url)
    stats = {"approved": 0, "revised": 0, "needs_human": 0, "skipped": 0}

    # 每批 6 条（审核比提取简单）
    batch_size = 6
    batches = [promos[i:i+batch_size] for i in range(0, len(promos), batch_size)]

    for batch_idx, batch in enumerate(batches):
        if verbose:
            print(f"   🔍 审核第 {batch_idx+1}/{len(batches)} 批（{len(batch)} 条）...")

        # 构造审核请求
        items_text = "\n---\n".join([
            f"[{i}] 标题: {p.get('title', '')}\n"
            f"    利益点: {p.get('benefit', '')}\n"
            f"    原文: {p.get('raw_description', '')}"
            for i, p in enumerate(batch)
        ])
        user_msg = REVIEW_USER_TEMPLATE.format(count=len(batch), items=items_text)

        for attempt in range(3):
            try:
                response = client.chat.completions.create(
                    model=model,
                    max_tokens=1024,
                    temperature=0.0,
                    messages=[
                        {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
                        {"role": "user", "content": user_msg},
                    ],
                )

                text = response.choices[0].message.content.strip()
                text = re.sub(r"^```(?:json)?\s*", "", text)
                text = re.sub(r"\s*```$", "", text)

                reviewed = json.loads(text)
                if isinstance(reviewed, list):
                    for item in reviewed:
                        idx = item.get("index", -1)
                        result = item.get("result", "approved")
                        reason = item.get("reason", "")

                        if idx >= 0 and idx < len(batch):
                            promo = batch[idx]
                            promo["review_result"] = result
                            promo["review_reason"] = reason

                            if result == "revised":
                                new_title = item.get("revised_title", "").strip()
                                new_benefit = item.get("revised_benefit", "").strip()
                                if new_title and len(new_title) <= 10:
                                    promo["title"] = new_title
                                if new_benefit and len(new_benefit) <= 10:
                                    promo["benefit"] = new_benefit
                                stats["revised"] += 1
                                if verbose:
                                    print(f"      ✏️ [{idx}] 修订: {promo['title']} | {promo['benefit']}")
                                    print(f"         理由: {reason}")
                            elif result == "needs_human":
                                stats["needs_human"] += 1
                                if verbose:
                                    print(f"      👤 [{idx}] 需人工: {promo['title']} — {reason}")
                            else:
                                stats["approved"] += 1
                                if verbose:
                                    print(f"      ✅ [{idx}] 通过: {promo['title']}")

                break  # 成功

            except json.JSONDecodeError as e:
                if verbose:
                    print(f"   ⚠️ 审核 JSON 解析失败: {e}")
                if attempt == 2:
                    print(f"   ⚠️ 第 {batch_idx+1} 批审核失败，标记为 needs_human")
                    for p in batch:
                        p.setdefault("review_result", "needs_human")
                        p.setdefault("review_reason", "审核解析失败")
                    stats["needs_human"] += len(batch)
            except Exception as e:
                err_msg = str(e)
                if "rate" in err_msg.lower() or "429" in err_msg:
                    wait = (attempt + 1) * 10
                    print(f"   ⏳ 审核遇限流，{wait}秒后重试...")
                    time.sleep(wait)
                else:
                    print(f"   ❌ 审核 API 错误: {e}")
                    if attempt < 2:
                        time.sleep(3)
                    else:
                        print(f"   ⚠️ 第 {batch_idx+1} 批审核失败，标记为 needs_human")
                        for p in batch:
                            p.setdefault("review_result", "needs_human")
                            p.setdefault("review_reason", f"审核异常: {e}")
                        stats["needs_human"] += len(batch)

        if batch_idx < len(batches) - 1:
            time.sleep(1)

    # 确保所有 promo 都有 review_result
    for p in promos:
        p.setdefault("review_result", "approved")
        p.setdefault("review_reason", "")

    return promos, stats


# ═══════════════════════════════════════════════════
# 函数 4: 去重
# ═══════════════════════════════════════════════════

def deduplicate(promos, vault_path=None):
    """
    检查 vault 中已有笔记，过滤重复活动。

    返回:
        (new_promos, skipped): 新活动列表 + 被跳过的数量
    """
    if vault_path is None:
        vault_path = VAULT_PATH

    # 收集 vault 中已有的 .md 文件名（不含扩展名）和链接
    existing_names = set()
    existing_links = set()

    if os.path.isdir(vault_path):
        for root, dirs, files in os.walk(vault_path):
            for f in files:
                if f.endswith(".md") and f != "活动卡片模板.md":
                    existing_names.add(os.path.splitext(f)[0])
                    # 读 frontmatter 提取 link
                    try:
                        with open(os.path.join(root, f), "r", encoding="utf-8") as fh:
                            content = fh.read()
                        if content.startswith("---"):
                            parts = content.split("---", 2)
                            if len(parts) >= 3:
                                for line in parts[1].strip().split("\n"):
                                    if line.startswith("link:"):
                                        existing_links.add(line.split(":", 1)[1].strip())
                    except Exception:
                        pass

    new_promos = []
    skipped = 0

    for promo in promos:
        title = promo.get("title", "")
        link = promo.get("link", "")

        # 安全文件名（替换 Windows 非法字符）
        safe_title = "".join(c if c not in r'\/:*?"<>|' else "·" for c in title)

        if safe_title in existing_names:
            if title:
                print(f"   ⏭️ 跳过（标题已存在）: {title}")
            skipped += 1
            continue

        if link and link in existing_links:
            print(f"   ⏭️ 跳过（链接已存在）: {title}")
            skipped += 1
            continue

        new_promos.append(promo)

    return new_promos, skipped


# ═══════════════════════════════════════════════════
# 函数 5: 写入 Obsidian 笔记
# ═══════════════════════════════════════════════════

def write_note(promo, vault_path=None, verbose=False):
    """
    根据模板生成 Obsidian 笔记，写入 vault。

    参数:
        promo: 结构化活动数据（含 review_result 和 review_reason）
        vault_path: vault 根目录
        verbose: 打印详情

    返回:
        (filepath, success): 文件路径 + 是否成功
    """
    if vault_path is None:
        vault_path = VAULT_PATH

    title = promo.get("title", "未命名活动")
    bank = promo.get("bank", "")
    region = promo.get("region", "全国")
    start_date = promo.get("start_date") or ""
    end_date = promo.get("end_date") or ""
    link = promo.get("link", "")
    tags = promo.get("tags", [])
    benefit = promo.get("benefit", "")
    raw_desc = promo.get("raw_description", "")
    confidence = promo.get("confidence", "")
    review_result = promo.get("review_result", "approved")

    # 审核状态 → Obsidian status
    # "skipped" = 用户主动跳过审核（--no-review），视为通过
    if review_result in ("approved", "revised", "skipped"):
        note_status = "active"
    else:
        note_status = "needs_review"

    # 安全文件名
    safe_title = "".join(c if c not in r'\/:*?"<>|' else "·" for c in title)

    # 构建 tags YAML
    if tags:
        tags_yaml = "\n".join(f"  - {t}" for t in tags)
    else:
        tags_yaml = "  - 云闪付"

    # 构建审核状态说明
    review_note = ""
    if note_status == "needs_review":
        review_reason = promo.get("review_reason", "")
        review_note = (
            f"\n> ⚠️ **待人工审核**：文案可能丢失了原文中的关键信息"
            + (f"（{review_reason}）" if review_reason else "")
            + "。\n> 请检查并修改文案后，将 frontmatter 中 `status` 改为 `active` 即可出图。\n"
        )

    # 读取模板（失败则用内置模板）
    template = None
    if os.path.exists(TEMPLATE_PATH):
        with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
            template = f.read()

    if template:
        # 用模板填充
        content = template
        # 替换 frontmatter 字段
        content = re.sub(r"^bank:\s*$", f"bank: {bank}", content, flags=re.MULTILINE)
        content = re.sub(r"^region:\s*$", f"region: {region}", content, flags=re.MULTILINE)
        content = re.sub(r"^start_date:\s*$", f"start_date: {start_date}", content, flags=re.MULTILINE)
        content = re.sub(r"^end_date:\s*$", f"end_date: {end_date}", content, flags=re.MULTILINE)
        content = re.sub(r"^link:\s*$", f"link: {link}", content, flags=re.MULTILINE)
        content = re.sub(r"^status:\s*active", f"status: {note_status}", content, flags=re.MULTILINE)
        content = re.sub(r"^tags:\s*\[\]", f"tags:\n{tags_yaml}", content, flags=re.MULTILINE)
        # 替换标题
        content = re.sub(r"^#\s*\{\{.*?\}\}", f"# {title}", content, flags=re.MULTILINE)
        # 替换主标题（模板格式: > *（...提示文字...）*）
        content = re.sub(
            r"(###\s*主标题\s*\n>\s*)\*.+\*",
            lambda m: f"{m.group(1)}{title}",
            content,
        )
        # 替换利益点
        content = re.sub(
            r"(###\s*利益点\s*\n>\s*)\*.+\*",
            lambda m: f"{m.group(1)}{benefit}",
            content,
        )
        # 插入审核警告（如果需要）
        if review_note:
            # 在利益点之后、图片素材之前插入
            content = re.sub(
                r"(##\s*图片素材)",
                lambda m: review_note + "\n" + m.group(1),
                content,
            )
        # 更新原始信息
        today = datetime.date.today().isoformat()
        raw_info = f"\n- **活动**：{raw_desc}\n- **采集时间**：{today}\n- **来源**：什么值得买\n- **可信度**：{confidence}"
        if "## 原始信息" in content:
            content = content.split("## 原始信息")[0] + "## 原始信息\n\n*（采集到的原始活动规则，保留备查）*" + raw_info + "\n"
    else:
        # 内置 fallback 模板
        today = datetime.date.today().isoformat()
        content = f"""---
bank: {bank}
region: {region}
start_date: {start_date}
end_date: {end_date}
link: {link}
status: {note_status}
tags:
{tags_yaml}
---

# {title}

| 字段 | 内容 |
|------|------|
| 🏦 银行 | `= this.bank` |
| 📍 地区 | `= this.region` |
| 📅 活动时间 | `= this.start_date` ~ `= this.end_date` |
| 🔗 跳转链接 | `= this.link` |

## 宣传文案

### 主标题
> {title}

### 利益点
> {benefit}
{review_note}
## 图片素材

- [ ] 678×562 宣传图（待生成）
- [ ] 上架审核

---

## 原始信息

*（采集到的原始活动规则，保留备查）*
- **活动**：{raw_desc}
- **采集时间**：{today}
- **来源**：什么值得买
- **可信度**：{confidence}
"""

    # 写入文件
    filepath = os.path.join(vault_path, f"{safe_title}.md")

    try:
        # 确保目录存在
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        if verbose:
            print(f"   📝 写入: {filepath}")
        return filepath, True
    except Exception as e:
        print(f"   ❌ 写入失败 {filepath}: {e}")
        return filepath, False


# ═══════════════════════════════════════════════════
# 函数 6: 触发卡片生成
# ═══════════════════════════════════════════════════

def trigger_card_generation(vault_path=None):
    """调用 generate_card.py --batch 批量出图"""
    card_script = os.path.join(SCRIPT_DIR, "generate_card.py")

    if not os.path.exists(card_script):
        print(f"   ❌ 找不到 generate_card.py: {card_script}")
        return False

    cmd = [sys.executable, card_script, "--batch"]
    if vault_path:
        cmd.extend(["--vault", vault_path])

    print(f"   🎨 运行: generate_card.py --batch ...")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=60,
        )
        if result.stdout:
            stdout_text = result.stdout.decode("utf-8", errors="replace")
            for line in stdout_text.strip().split("\n"):
                if line.strip():
                    print(f"   {line}")
        if result.returncode != 0:
            stderr_text = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""
            print(f"   ⚠️ 出图错误:\n{stderr_text}")
            return False
        return True
    except Exception as e:
        print(f"   ❌ 出图失败: {e}")
        return False


# ═══════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="🏦 银行优惠活动 · 自动采集器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python collect_promo.py                              # 全量采集（需网络 + API Key）
  python collect_promo.py --bank 建设银行               # 只搜指定银行
  python collect_promo.py --query "云闪付 生活缴费"      # 自定义搜索
  python collect_promo.py --dry-run                    # 预览，不写入文件
  python collect_promo.py -g                           # 采集 + 审核 + 自动出图
  python collect_promo.py --no-review -g               # 跳过审核，直接出图
  python collect_promo.py --from-file test.json -g     # 离线测试 + 出图
  python collect_promo.py --save-search cache.json     # 仅搜索并保存（供 CI 回退用）
        """,
    )
    parser.add_argument("-b", "--bank", help="指定银行名（如'建设银行'）")
    parser.add_argument("-q", "--query", help="自定义搜索关键词")
    parser.add_argument("-n", "--dry-run", action="store_true", help="预览模式，不写入文件")
    parser.add_argument("-g", "--generate-cards", action="store_true", help="写入后自动生成卡片")
    parser.add_argument("--from-file", help="从本地 JSON 文件读取搜索结果（离线测试）")
    parser.add_argument("--no-review", action="store_true", help="跳过文案审核（紧急采集用）")
    parser.add_argument("-v", "--verbose", action="store_true", help="详细日志")
    parser.add_argument("--vault", help="Obsidian vault 路径")
    parser.add_argument("--max-results", type=int, default=10, help="最大搜索结果数（默认10）")
    parser.add_argument("--save-search", help="仅搜索并保存结果到 JSON 文件（供 CI 使用）")
    parser.add_argument("--search-cache", help="CI 回退：当在线搜索失败时，从此 JSON 文件加载")

    args = parser.parse_args()
    vault_path = args.vault or VAULT_PATH

    print("=" * 50)
    print("🏦 银行优惠活动 · 自动采集器")
    print("=" * 50)

    # ── 第 1 步：搜索 ──
    print("\n📡 第 1 步：搜索什么值得买...")

    if args.from_file:
        if not os.path.exists(args.from_file):
            print(f"   ❌ 文件不存在: {args.from_file}")
            return
        print(f"   📂 从本地文件加载: {args.from_file}")
        raw_items, is_extracted = load_from_file(args.from_file)
        print(f"   ✅ 加载 {len(raw_items)} 条数据")
        if is_extracted:
            print("   💡 检测到预提取数据，跳过 AI 提取步骤")
    elif args.save_search:
        # 仅搜索模式：搜索 → 保存 JSON → 退出
        is_extracted = False
        raw_items = search_smzdm(
            bank=args.bank,
            query=args.query,
            max_results=args.max_results,
            verbose=True,
        )
        if not raw_items:
            print("   ⚠️ 搜索无结果，未保存")
            return
        with open(args.save_search, "w", encoding="utf-8") as f:
            json.dump(raw_items, f, ensure_ascii=False, indent=2)
        print(f"   💾 搜索结果已保存: {args.save_search} ({len(raw_items)} 条)")
        print("   💡 提交此文件到仓库后，CI 在线搜索失败时可回退使用")
        return
    else:
        is_extracted = False
        raw_items = search_smzdm(
            bank=args.bank,
            query=args.query,
            max_results=args.max_results,
            verbose=args.verbose,
        )
        # 在线搜索失败 → 尝试缓存回退
        if not raw_items:
            cache_file = args.search_cache or os.path.join(
                os.path.dirname(VAULT_PATH) if os.path.isabs(VAULT_PATH) else ".",
                "output", "search_cache.json"
            )
            # 也尝试仓库根目录
            repo_cache = os.path.join(SCRIPT_DIR, "output", "search_cache.json")
            for cf in [args.search_cache, repo_cache]:
                if cf and os.path.exists(cf):
                    print(f"   🔄 在线搜索无结果，尝试缓存回退: {cf}")
                    raw_items, _ = load_from_file(cf)
                    if raw_items:
                        print(f"   ✅ 从缓存加载 {len(raw_items)} 条历史搜索数据")
                        break
            if not raw_items:
                print("   ⚠️ 搜索无结果（可能需要手动检查网络或 smzdm 是否可访问）")
                print("   💡 提示：")
                print("      1. 本地运行 --save-search output/search_cache.json 保存搜索缓存")
                print("      2. 提交到仓库后，CI 将自动使用缓存")
                print("      3. 或用 --from-file 加载本地测试数据")
                return
        else:
            print(f"   ✅ 搜索到 {len(raw_items)} 条结果")

    if args.verbose:
        for i, item in enumerate(raw_items):
            print(f"   [{i+1}] {item['title'][:60]}...")

    # ── 第 2 步：AI 提取 ──
    if args.from_file and is_extracted:
        # 预提取数据，跳过 AI
        print("\n🤖 第 2 步：AI 提取结构化字段...（已跳过，使用预提取数据）")
        promos = raw_items
    else:
        print("\n🤖 第 2 步：AI 提取结构化字段...")
        promos = extract_with_claude(raw_items, verbose=args.verbose)

    if not promos:
        print("   ⚠️ 未能提取到有效活动")
        return

    print(f"   ✅ 提取到 {len(promos)} 个活动")

    if args.verbose:
        for p in promos:
            print(f"   🏦 {p['bank']} | {p['title']} | {p['benefit']} | 可信度:{p['confidence']}")

    if args.dry_run:
        print("\n📋 预览模式（--dry-run），不写入文件：\n")
        for i, p in enumerate(promos):
            print(f"  [{i+1}] 🏦 {p['bank']}")
            print(f"      标题: {p['title']}")
            print(f"      利益点: {p['benefit']}")
            print(f"      地区: {p['region']} | 时间: {p.get('start_date')}~{p.get('end_date')}")
            print(f"      标签: {', '.join(p.get('tags', []))}")
            print(f"      可信度: {p['confidence']}")
            print(f"      链接: {p['link']}")
            print()
        print(f"💡 去掉 --dry-run 即可写入 Obsidian vault")
        return

    # ── 第 2.5 步：文案审核 ──
    if args.no_review:
        print("\n🔍 第 2.5 步：文案审核...（--no-review，已跳过）")
        for p in promos:
            p["review_result"] = "skipped"
            p["review_reason"] = "跳过审核"
    else:
        print("\n🔍 第 2.5 步：文案审核...")
        promos, review_stats = review_copy(promos, verbose=args.verbose)
        total_reviewed = review_stats["approved"] + review_stats["revised"] + review_stats["needs_human"]
        print(f"   ✅ 审核完成: 通过 {review_stats['approved']} | 修订 {review_stats['revised']} | 待人工 {review_stats['needs_human']}")
        if review_stats["revised"] > 0 and not args.verbose:
            # 简要列出被修订的条目
            for p in promos:
                if p.get("review_result") == "revised":
                    print(f"   ✏️ 修订: 「{p['title']}」— {p.get('review_reason', '')}")

    # ── 第 3 步：去重 ──
    print("\n🔍 第 3 步：检查重复...")
    new_promos, skipped = deduplicate(promos, vault_path)
    print(f"   ✅ 新活动: {len(new_promos)} | ⏭️ 跳过: {skipped}")

    if not new_promos:
        print("   📭 没有新活动可写入")
        return

    # ── 第 4 步：写入笔记 ──
    print("\n📝 第 4 步：写入 Obsidian 笔记...")
    written = 0
    for promo in new_promos:
        _, ok = write_note(promo, vault_path, verbose=args.verbose)
        if ok:
            written += 1

    print(f"   ✅ 成功写入 {written}/{len(new_promos)} 篇笔记")

    # ── 第 5 步（可选）：生成卡片 ──
    if args.generate_cards and written > 0:
        print(f"\n🎨 第 5 步：生成宣传卡片...")
        trigger_card_generation(vault_path)

    print(f"\n{'=' * 50}")
    # 统计审核结果
    active_count = sum(1 for p in new_promos if p.get("review_result") in ("approved", "revised", "skipped"))
    needs_review_count = sum(1 for p in new_promos if p.get("review_result") == "needs_human")
    summary_parts = [f"搜索 {len(raw_items)} → 提取 {len(promos)} → 新活动 {written}"]
    if needs_review_count > 0:
        summary_parts.append(f"待审核 {needs_review_count}")
    summary_parts.append(f"跳过 {skipped}")
    print(f"📊 汇总: {' → '.join(summary_parts)}")
    if active_count > 0:
        print(f"🎨 {active_count} 篇可出图（status: active）")
    if needs_review_count > 0:
        print(f"👤 {needs_review_count} 篇待人工确认（status: needs_review）")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()
