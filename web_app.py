"""
🏦 银行优惠 · Web 采集界面
==========================
本地启动: python web_app.py
浏览器打开: http://localhost:5000
"""
import sys, os, json, re, time, datetime

from flask import Flask, request, jsonify, render_template_string
app = Flask(__name__)

# 延迟导入 collect_promo（需要时加载）
_collect_promo = None
def _get_collect():
    global _collect_promo
    if _collect_promo is None:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import collect_promo
        _collect_promo = collect_promo
    return _collect_promo

# ── HTML 模板 ──
HTML = r"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>🏦 银行优惠采集</title>
<style>
  :root {
    --bg: #f5f3ef; --card: #ffffff; --text: #2c2416;
    --accent: #c41e3a; --accent2: #0269b5; --border: #e0d9cf;
    --green: #2e7d32; --warn: #e67e22;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
         background: var(--bg); color: var(--text); min-height: 100vh; }
  .container { max-width: 780px; margin: 0 auto; padding: 24px 16px; }

  header { text-align: center; padding: 32px 0 24px; }
  header h1 { font-size: 2em; }
  header p { color: #8c8273; margin-top: 4px; font-size: 0.9em; }

  .card { background: var(--card); border-radius: 16px; padding: 24px;
          box-shadow: 0 1px 4px rgba(0,0,0,0.06); margin-bottom: 20px; }

  textarea { width: 100%; min-height: 180px; border: 2px solid var(--border);
             border-radius: 12px; padding: 14px 16px; font-size: 15px;
             font-family: inherit; resize: vertical; outline: none;
             transition: border-color 0.2s; line-height: 1.6; }
  textarea:focus { border-color: var(--accent2); }
  textarea::placeholder { color: #bfb8a8; }

  .options { display: flex; gap: 20px; margin: 14px 0;
             flex-wrap: wrap; align-items: center; }
  .options label { display: flex; align-items: center; gap: 6px;
                   cursor: pointer; font-size: 0.92em; color: #5c5346; }
  .options input[type=checkbox] { width: 18px; height: 18px; accent-color: var(--accent2); }

  .btn { display: block; width: 100%; padding: 14px; border: none;
         border-radius: 12px; font-size: 17px; font-weight: 600;
         cursor: pointer; transition: all 0.2s; letter-spacing: 0.5px; }
  .btn-primary { background: var(--accent2); color: #fff; }
  .btn-primary:hover { background: #01538a; transform: translateY(-1px);
                       box-shadow: 0 4px 12px rgba(2,105,181,0.3); }
  .btn-primary:disabled { background: #94b8d4; cursor: not-allowed;
                          transform: none; box-shadow: none; }

  .spinner { display: none; text-align: center; padding: 20px; }
  .spinner.active { display: block; }
  .spinner::after { content: ''; display: inline-block; width: 32px; height: 32px;
    border: 3px solid var(--border); border-top-color: var(--accent2);
    border-radius: 50%; animation: spin 0.7s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }

  .result { display: none; }
  .result.active { display: block; }

  .promo-item { background: #faf9f7; border-radius: 10px; padding: 14px 16px;
                margin-bottom: 10px; border-left: 4px solid var(--accent2); }
  .promo-item.revised { border-left-color: var(--warn); }
  .promo-item .bank { font-size: 0.85em; color: var(--accent); font-weight: 600; }
  .promo-item .title { font-size: 1.1em; font-weight: 700; margin: 4px 0; }
  .promo-item .benefit { color: #5c5346; }
  .promo-item .badge { display: inline-block; padding: 2px 8px; border-radius: 10px;
    font-size: 0.78em; margin-left: 6px; }
  .badge-ok { background: #e8f5e9; color: var(--green); }
  .badge-edit { background: #fff3e0; color: var(--warn); }
  .badge-new { background: #e3f2fd; color: var(--accent2); }

  .stats { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 16px; }
  .stat { padding: 8px 16px; border-radius: 20px; font-weight: 600;
          font-size: 0.9em; background: #f0ede8; }

  .card-preview { display: inline-block; margin: 6px; border-radius: 10px;
                  overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
  .card-preview img { max-width: 280px; display: block; }

  .tip { background: #fffbf0; border: 1px solid #f0d77b; border-radius: 10px;
         padding: 12px 16px; font-size: 0.88em; color: #8c6d1f; margin-top: 16px; }
</style>
</head>
<body>
<div class="container">
  <header>
    <h1>🏦 银行优惠 · 快速采集</h1>
    <p>粘贴活动链接或文案 → 一键提取 + 审核 + 出图</p>
  </header>

  <div class="card">
    <textarea id="input" placeholder="粘贴活动链接或文案，每行一条...&#10;&#10;支持: smzdm / 云闪付 / 银行官网 / 公众号文章 / 直接贴文字&#10;示例: https://www.smzdm.com/p/xxxx 或 「工商银行 大众点评满50减5」"></textarea>

    <div class="options">
      <label><input type="checkbox" id="genCards" checked> 🎨 生成卡片</label>
      <label><input type="checkbox" id="noReview"> ⚡ 跳过审核</label>
    </div>

    <button class="btn btn-primary" id="submitBtn" onclick="doCollect()">
      🚀 开始采集
    </button>
  </div>

  <div class="spinner" id="spinner"></div>

  <div class="result" id="result"></div>

  <div class="tip" id="tip" style="display:none;"></div>
</div>

<script>
async function doCollect() {
  const input = document.getElementById('input').value.trim();
  if (!input) return;

  const btn = document.getElementById('submitBtn');
  const spinner = document.getElementById('spinner');
  const result = document.getElementById('result');
  const tip = document.getElementById('tip');

  btn.disabled = true;
  btn.textContent = '⏳ 处理中...';
  spinner.classList.add('active');
  result.classList.remove('active');
  tip.style.display = 'none';

  try {
    const resp = await fetch('/collect', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        input: input,
        generate_cards: document.getElementById('genCards').checked,
        no_review: document.getElementById('noReview').checked,
      })
    });
    const data = await resp.json();
    renderResult(data);
  } catch(e) {
    result.innerHTML = `<div class="card" style="color:var(--accent)">❌ 请求失败: ${e.message}</div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = '🚀 开始采集';
    spinner.classList.remove('active');
    result.classList.add('active');
  }
}

function renderResult(data) {
  const r = document.getElementById('result');
  let html = '';

  // Stats
  html += `<div class="card"><div class="stats">`;
  html += `<span class="stat">📥 输入 ${data.input_count} 条</span>`;
  html += `<span class="stat">🤖 提取 ${data.extracted_count || 0} 个活动</span>`;
  html += `<span class="stat">📝 新笔记 ${data.note_count || 0} 篇</span>`;
  html += `<span class="stat">🎨 卡片 ${data.card_count || 0} 张</span>`;
  html += `</div>`;

  if (data.error) {
    html += `<div style="color:var(--warn);font-weight:600">⚠️ ${data.error}</div>`;
  }
  if (data.card_error) {
    html += `<div style="color:var(--warn);margin-top:4px">🎨 ${data.card_error}</div>`;
  }

  // SPA warning
  if (data.spa_warning) {
    html += `<div class="tip">💡 ${data.spa_warning}</div>`;
  }

  // Promos
  if (data.promos && data.promos.length > 0) {
    html += `<h3 style="margin:16px 0 10px">📋 提取结果</h3>`;
    for (const p of data.promos) {
      const cls = p.review_result === 'revised' ? 'revised' : '';
      const badge = p.review_result === 'revised'
        ? '<span class="badge badge-edit">已修订</span>'
        : '<span class="badge badge-ok">通过</span>';
      html += `<div class="promo-item ${cls}">`;
      html += `<div class="bank">🏦 ${p.bank}</div>`;
      html += `<div class="title">${p.title}${badge}</div>`;
      html += `<div class="benefit">${p.benefit}</div>`;
      if (p.card_path) {
        html += `<div class="card-preview" style="margin-top:8px">`;
        html += `<img src="${p.card_path}" alt="${p.title}" loading="lazy">`;
        html += `</div>`;
      }
      html += `</div>`;
    }
  }

  html += `</div>`;
  r.innerHTML = html;

  // Tip
  if (data.note_count > 0) {
    const tip = document.getElementById('tip');
    tip.innerHTML = `✅ 笔记已写入 Obsidian vault<br>📂 <code>${data.vault_path || ''}</code>`;
    tip.style.display = 'block';
  }
}
</script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML)

@app.route("/collect", methods=["POST"])
def collect():
    data = request.get_json()
    user_input = data.get("input", "").strip()
    generate_cards = data.get("generate_cards", True)
    no_review = data.get("no_review", False)

    if not user_input:
        return jsonify({"error": "请输入活动链接或文案", "input_count": 0})

    cp = _get_collect()

    # 解析输入
    lines = [l.strip() for l in user_input.split("\n") if l.strip()]
    if not lines:
        return jsonify({"error": "请输入活动链接或文案", "input_count": 0})

    # 抓取 URL → 构建 raw_items
    raw_items = []
    spa_count = 0
    for item in lines:
        if item.startswith("http://") or item.startswith("https://"):
            content = cp.fetch_url_content(item, verbose=False)
            raw_items.append({
                "title": item.split("/")[-1][:60] or item[:60],
                "url": item,
                "snippet": content,
                "source": "user_url",
            })
            if len(content) < 100:
                spa_count += 1
        else:
            raw_items.append({
                "title": item[:60],
                "url": "",
                "snippet": item,
                "source": "user_text",
            })

    if spa_count == len(raw_items) and lines[0].startswith("http"):
        return jsonify({
            "input_count": len(lines),
            "extracted_count": 0,
            "spa_warning": "所有链接均为 SPA 页面（如云闪付），HTML 无实际内容。请从浏览器复制活动文案文字后粘贴。",
        })

    # AI 提取
    promos = cp.extract_with_claude(raw_items, verbose=False)
    if not promos:
        return jsonify({
            "input_count": len(lines),
            "extracted_count": 0,
            "error": "AI 未能提取到有效活动，请确认文案包含完整的银行优惠信息。",
        })

    # 审核
    if no_review:
        for p in promos:
            p["review_result"] = "skipped"
    else:
        promos, review_stats = cp.review_copy(promos, verbose=False)

    # 去重
    vault_path = os.environ.get("BANK_PROMO_VAULT", cp.VAULT_PATH)
    new_promos, dup_count = cp.deduplicate(promos, vault_path)

    # 写入笔记
    note_count = 0
    for p in new_promos:
        if cp.write_note(p, vault_path, verbose=False):
            note_count += 1

    # 出图
    card_count = 0
    card_error = ""
    if generate_cards and note_count > 0:
        ok = cp.trigger_card_generation(vault_path)
        if not ok:
            card_error = "出图子进程执行失败，请查看终端日志"
        # 统计生成的卡片（文件名格式：银行-标题.png）
        for p in new_promos:
            safe_bank = re.sub(r'[\\/*?:"<>|]', "", p.get("bank", "")[:8])
            safe_title = "".join(c if c not in r'\/:*?"<>|' else "·" for c in p.get("title", ""))
            png_path = os.path.join(vault_path, f"{safe_bank}-{safe_title}.png")
            if os.path.exists(png_path):
                p["card_path"] = "/cards/" + os.path.basename(png_path)
                card_count += 1

    # 构建返回数据
    promo_list = []
    for p in new_promos:
        promo_list.append({
            "bank": p.get("bank", ""),
            "title": p.get("title", ""),
            "benefit": p.get("benefit", ""),
            "review_result": p.get("review_result", "approved"),
            "card_path": p.get("card_path", ""),
        })

    return jsonify({
        "input_count": len(lines),
        "extracted_count": len(promos),
        "note_count": note_count,
        "card_count": card_count,
        "card_error": card_error,
        "promos": promo_list,
        "vault_path": vault_path,
    })

# 静态文件：从 vault 直接 serve 卡片图片
from flask import send_file
@app.route("/cards/<path:filename>")
def serve_card(filename):
    cp = _get_collect()
    vault_path = os.environ.get("BANK_PROMO_VAULT", cp.VAULT_PATH)
    filepath = os.path.join(vault_path, filename)
    if os.path.exists(filepath):
        return send_file(filepath, mimetype="image/png")
    return "Not found", 404


if __name__ == "__main__":
    cp = _get_collect()
    vault = os.environ.get("BANK_PROMO_VAULT", cp.VAULT_PATH)
    print("=" * 55)
    print("🏦 银行优惠 · Web 采集界面")
    print("=" * 55)
    print(f"\n📂 Vault: {vault}")
    print(f"🌐 浏览器打开: http://localhost:5000")
    print(f"\n按 Ctrl+C 退出\n")
    app.run(host="127.0.0.1", port=5000, debug=False)
