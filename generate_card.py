"""
🏦 银行优惠活动卡片 · 自动生成器
================================
输入: 银行名(4字) + 主标题(≤10字) + 利益点(≤10字)
输出: 678×562px PNG 宣传卡片

用法:
  python generate_card.py --bank 建设银行 --title "满100减50" --benefit "每日限量抢"
  python generate_card.py --batch  # 从 Obsidian vault 批量生成
  python generate_card.py --list   # 列出支持的所有银行

依赖: Pillow>=9.0 + HarmonyOS Sans SC 字体
"""

import sys
import io as _io
import os
import argparse
import math

sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from PIL import Image, ImageDraw, ImageFont, ImageFilter

# ═══════════════════════════════════════════════════
# 银行品牌色数据（来自 bank-colors-final.md）
# ═══════════════════════════════════════════════════

BANK_COLORS = {
    "建设银行": {"hex": "#0269B5", "light": "#D9E8F3", "tone": "蓝"},
    "交通银行": {"hex": "#013579", "light": "#D8E0EA", "tone": "蓝"},
    "招商银行": {"hex": "#E40809", "light": "#FAD9DA", "tone": "红"},
    "民生银行": {"hex": "#1C1F89", "light": "#DCDDED", "tone": "蓝"},
    "中信银行": {"hex": "#D81821", "light": "#F9DCDD", "tone": "红"},
    "浦发银行": {"hex": "#0D427A", "light": "#DAE2EB", "tone": "蓝"},
    "兴业银行": {"hex": "#13499D", "light": "#DBE3F0", "tone": "蓝"},
    "广发银行": {"hex": "#BA0216", "light": "#F4D9DC", "tone": "红"},
    "平安银行": {"hex": "#EA6D0F", "light": "#FBE9DB", "tone": "橙"},
    "浙商银行": {"hex": "#DA2027", "light": "#F9DDDE", "tone": "红"},
    "九江银行": {"hex": "#FD0000", "light": "#FED8D8", "tone": "红"},
    "上饶银行": {"hex": "#EB611F", "light": "#FCE7DD", "tone": "橙"},
    "渤海银行": {"hex": "#004290", "light": "#D8E2EE", "tone": "蓝"},
    "邮储银行": {"hex": "#08763A", "light": "#D9EAE1", "tone": "绿"},
    "中国银行": {"hex": "#982338", "light": "#EFDEE1", "tone": "红"},
    "农业银行": {"hex": "#029882", "light": "#D9EFEC", "tone": "绿"},
    "江西农商": {"hex": "#03735A", "light": "#D9EAE6", "tone": "绿"},
    "工商银行": {"hex": "#E60012", "light": "#FDE8E8", "tone": "红"},
    "北京银行": {"hex": "#C41230", "light": "#FDE8ED", "tone": "红"},
    "华夏银行": {"hex": "#C4201B", "light": "#F6DDDC", "tone": "红"},
    "光大银行": {"hex": "#6B238E", "light": "#F0E6F5", "tone": "紫"},
    "江西银行": {"hex": "#01367A", "light": "#D8E0EB", "tone": "蓝"},
    "赣州银行": {"hex": "#E50311", "light": "#FBD9DB", "tone": "红"},
}

# 别名映射
BANK_ALIAS = {
    "中行": "中国银行", "农行": "农业银行", "建行": "建设银行",
    "交行": "交通银行", "招行": "招商银行", "工行": "工商银行",
    "邮储": "邮储银行",
}

# ═══════════════════════════════════════════════════
# 路径配置
# ═══════════════════════════════════════════════════

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(SCRIPT_DIR, "fonts", "HarmonyOS Sans", "HarmonyOS_SansSC")
FONT_BOLD = os.path.join(FONT_DIR, "HarmonyOS_SansSC_Bold.ttf")
FONT_MEDIUM = os.path.join(FONT_DIR, "HarmonyOS_SansSC_Medium.ttf")
FONT_REGULAR = os.path.join(FONT_DIR, "HarmonyOS_SansSC_Regular.ttf")

# Obsidian vault 路径
OBSIDIAN_VAULT = r"F:\CC Tools\酱酱&小克的实验室\银行优惠"

# ═══════════════════════════════════════════════════
# 卡片尺寸 & 布局参数
# ═══════════════════════════════════════════════════

CARD_W, CARD_H = 678, 562
TOP_RADIUS = 40

# 左对齐布局
LEFT_PAD = 50                # 左侧留白
BANK_TAG_PAD_X = 22          # 标签内左右padding（164+44=208≈PSD 209px）
BANK_TAG_PAD_Y = 12          # 标签内上下padding（40+24≈64≈PSD 65px）
TITLE_Y = 102                # 主标题距顶部
SUBTITLE_GAP = 10            # 副标题与主标题间距
ARROW_SIZE = 44              # 箭头按钮直径
ARROW_MARGIN = 12            # 箭头与胶囊间距
CAPSULE_PAD_X = 22           # 副标题胶囊内左右padding
CAPSULE_PAD_Y = 10           # 副标题胶囊内上下padding


def hex_to_rgb(hex_str):
    """#0269B5 → (2, 105, 181)"""
    hex_str = hex_str.lstrip("#")
    return tuple(int(hex_str[i : i + 2], 16) for i in (0, 2, 4))


def blend_hex(hex_color, white_ratio=0.92):
    """将颜色与白色混合，ratio=0.92 表示 92%白+8%品牌色 → 极浅背景"""
    r, g, b = hex_to_rgb(hex_color)
    br = int(r + (255 - r) * white_ratio)
    bg = int(g + (255 - g) * white_ratio)
    bb = int(b + (255 - b) * white_ratio)
    return (br, bg, bb)


def darken_hex(hex_color, factor=0.85):
    """加深颜色用于文字（浅色品牌色时需要）"""
    r, g, b = hex_to_rgb(hex_color)
    return (int(r * factor), int(g * factor), int(b * factor))


def resolve_bank(name):
    """解析银行名，支持别名和模糊匹配"""
    if name in BANK_ALIAS:
        name = BANK_ALIAS[name]
    if name in BANK_COLORS:
        return name
    # 模糊匹配
    for bank in BANK_COLORS:
        if name in bank or bank in name:
            return bank
    return None


def create_top_rounded_mask(w, h, radius):
    """创建只有顶部两个角是圆角的蒙版"""
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle([(0, 0), (w, h + radius)], radius, fill=255)
    return mask


def draw_gradient_bg(draw, brand_hex):
    """绘制浅品牌色→白色的垂直渐变背景（起点约15%品牌色+85%白色）"""
    r, g, b = blend_hex(brand_hex, 0.85)  # 起点：15%品牌色
    w, h = CARD_W, CARD_H

    for y in range(h):
        ratio = y / h
        ratio = 1 - math.pow(1 - ratio, 3.0)  # ease-out
        cr = int(r + (255 - r) * ratio)
        cg = int(g + (255 - g) * ratio)
        cb = int(b + (255 - b) * ratio)
        draw.line([(0, y), (w, y)], fill=(cr, cg, cb))


def draw_bank_tag(draw, bank_name, brand_hex, font):
    """
    左上角银行名标签（参考样图精确布局）
    - 药丸形（全圆角），定位在画布原点 (0, 0)
    - 圆角弧线自然从 (radius, 0) 弯到 (0, radius)
    - 标签背景色随银行品牌色变化，白色加粗文字
    """
    r, g, b = hex_to_rgb(brand_hex)
    text_w = draw.textlength(bank_name, font=font)

    tag_w = text_w + BANK_TAG_PAD_X * 2
    tag_h = font.size + BANK_TAG_PAD_Y * 2
    radius = tag_h // 2  # 半高 → 药丸形

    # 标签从画布原点 (0,0) 开始，圆角在画布内可见
    tag_x, tag_y = 0, 0

    draw.rounded_rectangle(
        [(tag_x, tag_y), (tag_x + tag_w, tag_y + tag_h)],
        radius=radius,
        fill=(r, g, b),
    )
    # 文字在标签内居中
    text_x = tag_x + BANK_TAG_PAD_X
    text_y = tag_y + BANK_TAG_PAD_Y - 2
    draw.text((text_x, text_y), bank_name, fill=(255, 255, 255), font=font)

    return tag_y + tag_h  # 返回标签底部Y


def draw_title_text(draw, text, brand_hex, font):
    """
    主标题——品牌色 60px Bold，左对齐
    自动加深浅色品牌色确保可读性
    """
    r, g, b = hex_to_rgb(brand_hex)
    brightness = r + g + b
    if brightness > 550:
        r, g, b = darken_hex(brand_hex, 0.55)
    elif brightness > 450:
        r, g, b = darken_hex(brand_hex, 0.75)

    draw.text((LEFT_PAD, TITLE_Y), text, fill=(r, g, b), font=font)
    return TITLE_Y + font.size  # 返回标题底部Y


def draw_subtitle_capsule(draw, text, brand_hex, font_text, font_arrow, title_bottom_y):
    """
    副标题白底胶囊 + 圆形箭头按钮
    - 文字套在白色圆角矩形内（品牌色细边框+阴影）
    - 右侧紧跟品牌色圆形 › 按钮
    - 位于主标题正下方
    """
    r, g, b = hex_to_rgb(brand_hex)
    text_w = draw.textlength(text, font=font_text)

    cap_w = text_w + CAPSULE_PAD_X * 2
    cap_h = font_text.size + CAPSULE_PAD_Y * 2
    cap_x = LEFT_PAD
    cap_y = title_bottom_y + SUBTITLE_GAP

    # 阴影
    shadow_off = 2
    draw.rounded_rectangle(
        [
            (cap_x + shadow_off, cap_y + shadow_off),
            (cap_x + cap_w + shadow_off, cap_y + cap_h + shadow_off),
        ],
        radius=cap_h // 2,
        fill=(218, 218, 218),
    )
    # 白色主体 + 品牌色边框
    draw.rounded_rectangle(
        [(cap_x, cap_y), (cap_x + cap_w, cap_y + cap_h)],
        radius=cap_h // 2,
        fill=(255, 255, 255),
        outline=(r, g, b),
        width=2,
    )
    # 文字
    text_x = cap_x + CAPSULE_PAD_X
    text_y = cap_y + CAPSULE_PAD_Y - 3
    draw.text((text_x, text_y), text, fill=(r, g, b), font=font_text)

    # ── 圆形箭头按钮 ──
    arrow_cx = cap_x + cap_w + ARROW_MARGIN + ARROW_SIZE // 2
    arrow_cy = cap_y + cap_h // 2

    draw.ellipse(
        [
            (arrow_cx - ARROW_SIZE // 2, arrow_cy - ARROW_SIZE // 2),
            (arrow_cx + ARROW_SIZE // 2, arrow_cy + ARROW_SIZE // 2),
        ],
        fill=(r, g, b),
    )
    arrow_char = "›"
    aw = draw.textlength(arrow_char, font=font_arrow)
    ah = font_arrow.size
    draw.text(
        (arrow_cx - aw // 2, arrow_cy - ah // 2 - 2),
        arrow_char,
        fill=(255, 255, 255),
        font=font_arrow,
    )

    return cap_y + cap_h  # 返回胶囊底部Y


def generate_card(
    bank: str,
    title: str,
    benefit: str,
    output_path: str = None,
    ip_image_path: str = None,
    subtitle: str = None,
):
    """
    生成一张银行优惠活动卡片（左对齐布局，参考现有活动卡片风格）。

    参数:
        bank:     银行名（如"民生银行"、"建设银行"）
        title:    主标题（如"1分钱乘地铁"）
        benefit:  折扣文案（如"满2元减1.99元"）
        output_path: 输出路径，默认 {title}.png
        ip_image_path: 右下IP形象图片路径（可选，预留）
        subtitle:  已废弃，保留兼容

    返回:
        输出文件路径
    """
    # ── 解析银行 ──
    bank_full = resolve_bank(bank)
    if not bank_full:
        print(f"❌ 找不到银行: {bank}")
        print(f"   支持的银行: {', '.join(BANK_COLORS.keys())}")
        return None

    bank_info = BANK_COLORS[bank_full]
    brand_hex = bank_info["hex"]
    bank_name = bank_full  # 4字银行名

    print(f"🎨 生成卡片: {bank_name} | {title} | {benefit}")
    print(f"   品牌色: {brand_hex} | 色系: {bank_info['tone']}")

    # ── 加载字体 ──
    try:
        font_bank = ImageFont.truetype(FONT_BOLD, 42)       # 银行名标签（42号字，匹配PSD 209×65px）
        font_title = ImageFont.truetype(FONT_BOLD, 60)      # 主标题
        font_subtitle = ImageFont.truetype(FONT_MEDIUM, 42) # 副标题（胶囊内）
        font_arrow = ImageFont.truetype(FONT_BOLD, 32)      # 箭头符号
    except OSError as e:
        print(f"❌ 字体加载失败: {e}")
        print(f"   请确认字体路径: {FONT_DIR}")
        return None

    # ── 创建画布 ──
    img = Image.new("RGBA", (CARD_W, CARD_H), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)

    # ── 1. 渐变背景（15%品牌色→白，垂直）──
    draw_gradient_bg(draw, brand_hex)

    # ── 2. 左上角银行名小标签（品牌色底+白字 24px Bold，贴边）──
    draw_bank_tag(draw, bank_name, brand_hex, font_bank)

    # ── 3. 主标题（品牌色 60px Bold，左对齐）──
    title_bottom = draw_title_text(draw, title, brand_hex, font_title)

    # ── 4. 副标题白底胶囊+箭头按钮（42px Medium，套在胶囊内）──
    draw_subtitle_capsule(draw, benefit, brand_hex, font_subtitle, font_arrow, title_bottom)

    # ── 5. 可选：右下IP形象图 ──
    if ip_image_path and os.path.isfile(ip_image_path):
        try:
            ip_img = Image.open(ip_image_path).convert("RGBA")
            # 缩放到合适大小（最大200×200）
            ip_w, ip_h = ip_img.size
            scale = min(200 / ip_w, 200 / ip_h, 1.0)
            ip_img = ip_img.resize(
                (int(ip_w * scale), int(ip_h * scale)), Image.LANCZOS
            )
            # 贴在右下角
            ip_x = CARD_W - ip_img.width - 30
            ip_y = CARD_H - ip_img.height - 20
            img.paste(ip_img, (ip_x, ip_y), ip_img)
        except Exception as e:
            print(f"   ⚠️ IP形象加载失败: {e}")

    # ── 6. 顶部圆角蒙版 ──
    mask = create_top_rounded_mask(CARD_W, CARD_H, TOP_RADIUS)
    img.putalpha(mask)

    # ── 7. 合成白色底并导出PNG ──
    final = Image.new("RGB", (CARD_W, CARD_H), (255, 255, 255))
    final.paste(img, (0, 0), img)

    if output_path is None:
        output_path = f"{title}.png"

    final.save(output_path, "PNG", optimize=True)

    # 检查文件大小
    size_kb = os.path.getsize(output_path) / 1024
    size_ok = "✅" if size_kb < 200 else "⚠️"
    print(f"   {size_ok} 输出: {output_path} ({size_kb:.1f} KB)")

    return output_path


# ═══════════════════════════════════════════════════
# 批量生成：从 Obsidian markdown 读取并生成
# ═══════════════════════════════════════════════════

def batch_generate(vault_path: str = None):
    """扫描 Obsidian vault 中的活动笔记，批量生成卡片"""
    if vault_path is None:
        vault_path = OBSIDIAN_VAULT

    if not os.path.isdir(vault_path):
        print(f"❌ Obsidian vault 路径不存在: {vault_path}")
        return

    import re

    count = 0
    for root, dirs, files in os.walk(vault_path):
        for f in files:
            if not f.endswith(".md") or f == "活动卡片模板.md":
                continue

            filepath = os.path.join(root, f)
            with open(filepath, "r", encoding="utf-8") as fh:
                content = fh.read()

            # 解析 frontmatter
            front = {}
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    for line in parts[1].strip().split("\n"):
                        if ":" in line:
                            k, v = line.split(":", 1)
                            front[k.strip()] = v.strip()

            bank = front.get("bank", "")
            if not bank:
                continue

            # 检查审核状态：只给 status: active 的笔记出图
            status = front.get("status", "active")
            if status != "active":
                # 跳过 needs_review / draft 等状态
                continue

            # 从正文提取标题和利益点
            title_match = re.search(r"###\s*主标题.*?\n>\s*\*?(.+)\*?", content)
            benefit_match = re.search(r"###\s*利益点.*?\n>\s*\*?(.+)\*?", content)

            title = title_match.group(1).strip() if title_match else os.path.splitext(f)[0]
            benefit = benefit_match.group(1).strip() if benefit_match else ""

            if not title:
                continue

            # 生成图片到同目录
            img_name = f"{title}.png"
            img_path = os.path.join(root, img_name)

            result = generate_card(bank, title, benefit, img_path)
            if result:
                count += 1

    print(f"\n📊 批量生成完成: {count} 张卡片")


# ═══════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="🏦 银行优惠活动卡片自动生成器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python generate_card.py -b 民生银行 -t "1分钱乘地铁" -bf "满2元减1.99元"
  python generate_card.py -b 建设银行 -t "满100减50" -bf "每日限量抢"
  python generate_card.py --batch   # 批量从Obsidian生成
  python generate_card.py --list    # 列出所有银行
        """,
    )
    parser.add_argument("-b", "--bank", help="银行名（4字缩写，如'民生银行'）")
    parser.add_argument("-t", "--title", help="主标题（如'1分钱乘地铁'）")
    parser.add_argument("-bf", "--benefit", help="折扣文案（如'满2元减1.99元'）")
    parser.add_argument("-o", "--output", help="输出路径（默认用标题.png）")
    parser.add_argument("-ip", "--ip-image", help="右下IP形象图片路径（可选，预留）")
    parser.add_argument("--batch", action="store_true", help="批量从Obsidian生成")
    parser.add_argument("--vault", help="Obsidian vault 路径（覆盖默认路径）")
    parser.add_argument("--list", action="store_true", help="列出所有支持的银行")

    args = parser.parse_args()

    if args.list:
        print("🏦 支持的银行（23家）：\n")
        for bank, info in BANK_COLORS.items():
            print(f"  {info['tone']} {bank:6s}  {info['hex']}  →  浅色 {info['light']}")
        return

    if args.batch:
        batch_generate(vault_path=args.vault)
        return

    if not args.bank or not args.title or not args.benefit:
        parser.print_help()
        print("\n⚠️  --bank, --title, --benefit 三个参数缺一不可哦~")
        return

    generate_card(
        bank=args.bank,
        title=args.title,
        benefit=args.benefit,
        output_path=args.output,
        ip_image_path=args.ip_image,
    )


if __name__ == "__main__":
    main()
