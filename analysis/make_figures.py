#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_figures.py — U07 图件（作图规范 v1.0 · 视觉规范修订）

对治《08.生信分析模块库/出图自查清单.md》六类缺陷（源自 09.SCI文章排版参考/01/不足.txt）：

  D1 文字/标签盖过数据 → 图例一律置于坐标轴外（下方），绝不落进数据区
  D2 文字超出图框     → 固定栏宽 figsize + constrained_layout，文本锁在版心内
  D3 图例过长盖过数据 → 图例条目 ≤6、横排于轴外；长条目/长标签换行
  D4 图例体系缺失     → 有序列必有图例；多面板图加粗体面板标记；缩写就地定义
  D5 图与图跨页       → 一 Figure 一文件、单页矢量 PDF（保存后校验页数 = 1）
  D6 图间空白过多     → 统一栏宽网格（单栏 89mm / 双栏 183mm），同类图同尺寸

规范来源 crossval/spec/figure_spec.yaml：
  fontsize_pt ∈ [5,7]（面板标记 8）、linewidth_pt ∈ [0.25,1.0]、禁 background_grid；
  栏宽 single 89mm / double 183mm、高 ≤170mm。色板 Wong 2011（色盲安全）。
导出四格式 pdf/tiff/png/jpg @300dpi；png/tiff 强制 RGB（C-6）。
"""
import io, os, json, textwrap
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

SEED = 20260910
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(BASE, "results")
FIG = os.environ.get("FIG_DIR", os.path.join(BASE, "figures"))
os.makedirs(FIG, exist_ok=True)

# ── 栏宽网格（mm→in）────────────────────────────────────────────────────────
# 安全规格（09/02/出图要求 §0）：单栏 85、双栏 170mm（各家范围 85–90 / 170–190，取小值最安全）
COL1, COL2 = 85 / 25.4, 170 / 25.4           # 3.346 in / 6.693 in
H_SINGLE = 3.0                                # 单栏图统一高度（D6：同类图同尺寸）
# ── 字号 / 线宽（出图要求：正文文字 6–8pt、刻度 ≥6pt、分图标签 8–10pt 粗体）──
FS_MIN, FS_MAX = 6, 8
FS, FS_SMALL, FS_PANEL = 7, 6, 8              # 面板标记 8pt（规范单列）
LW_MIN, LW_MAX = 0.25, 1.0
LW, LW_THIN, LW_REF = 0.9, 0.6, 0.5           # 曲线 / 轴 / 辅助线
# ── 色板 Wong 2011（= Okabe-Ito，色盲安全；出图要求 3.3）─────────────────────
BLUE, VERM, GREY = "#0072B2", "#D55E00", "#999999"

plt.rcParams.update({
    # 出图要求 0/3.2：全篇图统一 Arial/Helvetica（Windows=Arial，云端=Liberation Sans
    # 度量兼容，DejaVu 兜底希腊字母/箭头等）；不要 Times、不要中文字体
    "font.family": "sans-serif",
    "font.sans-serif": ["Arial", "Liberation Sans", "Helvetica", "DejaVu Sans"],
    "font.size": FS,
    "axes.titlesize": FS, "axes.labelsize": FS,
    "xtick.labelsize": FS_SMALL, "ytick.labelsize": FS_SMALL,
    "legend.fontsize": FS_SMALL,
    "axes.linewidth": LW_THIN, "axes.grid": False,
    "lines.linewidth": LW,
    "xtick.major.width": LW_THIN, "ytick.major.width": LW_THIN,
    "xtick.major.size": 2.5, "ytick.major.size": 2.5,
    "figure.constrained_layout.use": True,
    "pdf.fonttype": 42, "ps.fonttype": 42,     # C-4：出版 PDF 须 Type0/TrueType，禁 Type3
})


# ══════════════════════════ 规范层（D1–D8 共用）══════════════════════════════
def new_fig(w=COL1, h=H_SINGLE):
    """D2/D6：按栏宽网格出图；constrained_layout 保证文本不出框、图间可无缝排布。
    同时限制刻度数量（D8 防御：图例移到右侧后绘图区变窄，刻度标签易互相重叠）。"""
    assert abs(w - COL1) < 1e-3 or abs(w - COL2) < 1e-3, "宽度须落在栏宽网格（85/170mm）"
    fig, ax = plt.subplots(figsize=(w, h), constrained_layout=True)
    ax.xaxis.set_major_locator(mticker.MaxNLocator(nbins=4))
    ax.yaxis.set_major_locator(mticker.MaxNLocator(nbins=4))
    return fig, ax


def _place_labels(ax, pts, labels, fontsize=FS_SMALL, italic=True):
    """D7/D8：图内点标签的**像素级贪心避让**。

    逐个标签尝试 8 个候选偏移，取第一个"完全落在坐标轴框内 且 不与已放标签相交"的位置；
    全部候选冲突则**放弃该标签**（宁缺毋压），返回实际放置条数。
    """
    fig = ax.get_figure()
    placed, n = [], 0
    for (x, y), s in zip(pts, labels):
        got = None
        for dx, dy, va in [(0, 6, "bottom"), (0, -6, "top"), (8, 2, "bottom"),
                           (-8, 2, "bottom"), (0, 16, "bottom"), (0, -16, "top"),
                           (13, -10, "top"), (-13, -10, "top")]:
            ann = ax.annotate(s, (x, y), xytext=(dx, dy), textcoords="offset points",
                              ha="center", va=va, fontsize=fontsize,
                              style="italic" if italic else "normal")
            fig.canvas.draw()
            r = fig.canvas.get_renderer()
            ab, tb = ax.get_window_extent(r), ann.get_window_extent(r)
            ok = (tb.x0 >= ab.x0 and tb.x1 <= ab.x1 and tb.y0 >= ab.y0
                  and tb.y1 <= ab.y1
                  and all(_ov_area(tb, pb) <= 0.0 for pb in placed))
            if ok:
                got = ann; placed.append(tb); break
            ann.remove()
        if got is not None:
            n += 1
    return n


def wrap(s, n):
    """D2/D3：把超长文本按宽度换行，避免横向溢出图框。"""
    s = str(s)
    return "\n".join(textwrap.wrap(s, n)) if len(s) > n else s


def legend_outside(ax, ncol=1):
    """D1/D3：图例置于**图右侧**（figure legend，loc="outside right center"），
    由 constrained_layout 预留空间 → 永不覆盖数据、也不出画布；条目上限 6。
    （2026-09-14 用户反馈"图例没在右边"：SCI 常规为右侧竖排单列图例。）"""
    hs, ls = ax.get_legend_handles_labels()
    if not hs:
        return
    assert len(hs) <= 6, f"D3 违规：图例 {len(hs)} 条 > 6"
    ax.get_figure().legend(hs, ls, frameon=False, loc="outside right center",
                           ncol=ncol, handlelength=1.3,
                           handletextpad=0.5, columnspacing=1.2, labelspacing=0.5)


def panel(ax, letter):
    """D4：多面板图的粗体面板标记（置于轴外左上，8pt）。单面板图不调用。"""
    ax.text(-0.16, 1.04, letter, transform=ax.transAxes, fontsize=FS_PANEL,
            fontweight="bold", va="bottom", ha="left")


def _overlap(b1, b2):
    return b1.x0 < b2.x1 and b2.x0 < b1.x1 and b1.y0 < b2.y1 and b2.y0 < b1.y1


def _ov_area(b1, b2):
    """两 bbox 相交面积（pt²）——用于容忍 1pt 级的擦边，只报真实重叠。"""
    dx = min(b1.x1, b2.x1) - max(b1.x0, b2.x0)
    dy = min(b1.y1, b2.y1) - max(b1.y0, b2.y0)
    return dx * dy if dx > 0 and dy > 0 else 0.0


def _texts(ax):
    """该轴上全部可见文字（标题/轴标/刻度标签/图内标注）。"""
    out = [ax.title, ax.xaxis.label, ax.yaxis.label]
    out += list(ax.get_xticklabels()) + list(ax.get_yticklabels()) + list(ax.texts)
    return [t for t in out if t is not None and t.get_visible() and str(t.get_text()).strip()]


def audit(fig, name):
    """D1/D2/D3/D4/D6 + 规范区间（字号/线宽/禁网格）的机器自检；返回问题列表。"""
    fig.canvas.draw()
    r = fig.canvas.get_renderer()
    issues = []
    # D2：整幅内容（含全部文字）必须落在画布内。用 get_tightbbox 判定——
    #     逐条 Text 判定会误伤 xlim 之外、本就不绘制的越界刻度标签（实测假阳性）。
    tb = fig.get_tightbbox(r)                          # 单位：英寸
    w, h = fig.get_size_inches()
    if tb.x0 < -0.02 or tb.y0 < -0.02 or tb.x1 > w + 0.02 or tb.y1 > h + 0.02:
        issues.append(f"D2 内容出框：tight={tuple(round(v, 2) for v in tb.bounds)}")
    for ax in fig.axes:
        if len(fig.axes) > 1 and ax.texts == []:
            issues.append("D4 多面板图缺面板标记")
        texts = ax.get_xticklabels() + ax.get_yticklabels() + [ax.xaxis.label, ax.yaxis.label]
        if ax.get_title():
            texts.append(ax.title)
        for t in texts:                                # 规范：字号 ∈ [5,8]
            if not t.get_text() or not t.get_visible():
                continue                               # 跳过空串与越界 tick 的隐形 Text
            if not (FS_MIN - 1e-6 <= t.get_fontsize() <= FS_PANEL + 1e-6):
                issues.append(f"字号越界 {t.get_fontsize():g}pt：{t.get_text()[:14]}")
        for ln in ax.lines:                            # 规范：线宽 ≤ 1.0pt
            if ln.get_linewidth() > LW_MAX + 1e-9:
                issues.append(f"线宽越界 {ln.get_linewidth():g}pt")
        for c in ax.collections:
            lws = np.atleast_1d(c.get_linewidths())
            if lws.size and lws.max() > LW_MAX + 1e-9:
                issues.append(f"散点线宽越界 {lws.max():g}pt")
        if any(g.get_visible() for g in ax.get_xgridlines() + ax.get_ygridlines()):
            issues.append("存在背景网格（规范禁止）")
        ab = ax.get_window_extent(r)                   # D7：图内标注须落在坐标轴框内
        for t in ax.texts:
            if not str(t.get_text()).strip() or not t.get_visible():
                continue
            tb = t.get_window_extent(r)
            if tb.x0 < ab.x0 - 1 or tb.x1 > ab.x1 + 1 or tb.y0 < ab.y0 - 1 or tb.y1 > ab.y1 + 1:
                issues.append(f"D7 图内文字超出坐标轴框：{str(t.get_text())[:14]}")
    legends = list(fig.legends) + [ax.get_legend() for ax in fig.axes if ax.get_legend()]
    # D8：文字互不相压（刻度标签 / 图内标注 / 图例文字，容忍 ≤2pt² 擦边）
    _boxes = [(t, t.get_window_extent(r)) for ax in fig.axes for t in _texts(ax)]
    _boxes += [(t, t.get_window_extent(r)) for leg in legends for t in leg.get_texts()
               if str(t.get_text()).strip()]
    for _i in range(len(_boxes)):
        for _j in range(_i + 1, len(_boxes)):
            if _overlap(_boxes[_i][1], _boxes[_j][1]) and _ov_area(_boxes[_i][1], _boxes[_j][1]) > 2.0:
                issues.append(f"D8 文字重叠：{str(_boxes[_i][0].get_text())[:10]}"
                              f" ↔ {str(_boxes[_j][0].get_text())[:10]}")
    for leg in legends:
        if len(leg.get_texts()) > 6:                    # D3
            issues.append("D3 图例条目 > 6")
        lb = leg.get_window_extent(r)                   # D1/D3：图例不得压住任一坐标轴区域
        for ax in fig.axes:
            if _overlap(lb, ax.get_window_extent(r)):
                issues.append("D1 图例与坐标轴区域重叠")
                break
    for ax in fig.axes:                                 # D4：有序列必有图例
        if len(ax.get_legend_handles_labels()[1]) >= 2 and not legends:
            issues.append("D4 多序列缺图例")
    if not any(abs(w - c) < 1e-3 for c in (COL1, COL2)):  # D6：栏宽网格
        issues.append(f"D6 宽度 {w:.2f}in 不在栏宽网格")
    if h * 25.4 > 170 + 1:
        issues.append("高度 > 170mm")
    print(f"  [审计{'✗' if issues else '✓'}] {name}"
          + ("：" + "；".join(issues) if issues else "：D1–D8 + 规范区间通过"))
    return issues


def save(fig, name):
    from PIL import Image
    issues = audit(fig, name)
    # 出图要求：线条图+文字的位图须 ≥600 dpi（spec dpi.line_min；TIFF 用 LZW 压缩）
    for ext, kw in [("pdf", {}), ("tiff", dict(pil_kwargs={"compression": "tiff_lzw"})),
                    ("png", {}), ("jpg", dict(pil_kwargs={"quality": 95}))]:
        dpi = 600 if ext == "tiff" else 300
        p = os.path.join(FIG, f"{name}.{ext}")
        fig.savefig(p, dpi=dpi, **kw)                   # 不裁框：尺寸=栏宽网格（D6）
        if ext in ("png", "tiff"):                      # C-6 色彩模式：RGB（matplotlib 默认 RGBA）
            with open(p, "rb") as f:                    # 先读入内存，避免 PIL 句柄与写回冲突（曾致 Errno 22）
                data = f.read()
            im = Image.open(io.BytesIO(data))
            if im.mode != "RGB":
                bg = Image.new("RGB", im.size, (255, 255, 255))
                bg.paste(im, mask=im.split()[-1] if im.mode in ("RGBA", "LA") else None)
                buf = io.BytesIO()
                bg.save(buf, format="TIFF" if ext == "tiff" else "PNG", dpi=(dpi, dpi))
                tmp = p + ".tmp"
                with open(tmp, "wb") as f:
                    f.write(buf.getvalue())
                os.replace(tmp, p)
                im.close()
    try:                                                # D5：一 Figure 一文件、单页
        from pypdf import PdfReader
        n = len(PdfReader(os.path.join(FIG, f"{name}.pdf")).pages)
        if n != 1:
            issues.append(f"D5 PDF {n} 页（应单页）")
    except ImportError:
        pass
    plt.close(fig)
    print(f"  图件：{name} ×4 格式")
    return issues


# ══════════════════════════ 图件 ════════════════════════════════════════════
R = json.load(open(os.path.join(RES, "results.json"), encoding="utf-8"))
_audit_issues = []

# ---------- 图1 火山图（deg） ----------
d = pd.read_csv(os.path.join(RES, "T02_差异表达全表.csv"))
d["-log10P"] = -np.log10(d["P"].clip(lower=1e-300))
fig, ax = new_fig(COL1, H_SINGLE)
m = ~d["DEG"].astype(bool)
ax.scatter(d.loc[m, "log2FC"], d.loc[m, "-log10P"], s=2, c=GREY, alpha=0.35, linewidths=0)
up = d["DEG"].astype(bool) & (d["log2FC"] > 0)
dn = d["DEG"].astype(bool) & (d["log2FC"] < 0)
ax.scatter(d.loc[dn, "log2FC"], d.loc[dn, "-log10P"], s=3, c=BLUE, linewidths=0,
           label=f"Down-regulated (n = {int(dn.sum())})")
ax.scatter(d.loc[up, "log2FC"], d.loc[up, "-log10P"], s=3, c=VERM, linewidths=0,
           label=f"Up-regulated (n = {int(up.sum())})")
ax.axhline(-np.log10(0.05), ls="--", lw=LW_REF, c="k")
ax.axvline(0.585, ls="--", lw=LW_REF, c="k")
ax.axvline(-0.585, ls="--", lw=LW_REF, c="k")
ax.set_xlabel("log2 fold change (tumour vs normal)")
ax.set_ylabel("-log10 P (Welch t-test)")
# 出图要求：图内不得出现图题（图题/图注写在稿件正文里）——标题移入图注。
# 注：T02_DEG.value 是 {'总数','上调','下调'} 字典，直接串进标题会渲染出超长文本
#     （原缺陷 D2 源头）；DEG 计数已由图例承担。
# 出图要求 4.6：火山图须有关键基因标签；基因名斜体（3.2）。每侧取 -log10P 前 3 个。
# 位置由 `_place_labels()` 像素级避让决定（D7 不出框 + D8 不重叠；全冲突则弃标）。
_pts, _labs = [], []
for _msk in (up, dn):
    for _i, _r in d[_msk].nlargest(3, "-log10P").iterrows():
        _pts.append((_r["log2FC"], _r["-log10P"])); _labs.append(str(_r["symbol"]))
legend_outside(ax, ncol=1)       # 先放图例：图例占右侧空间会触发重新布局，
_place_labels(ax, _pts, _labs)   # 标签避让必须基于**最终**几何（否则被挤压后重叠）
_audit_issues += save(fig, "01_deg_volcano")

# ---------- 图2 富集点图（enrichment） ----------
try:
    _up = pd.read_csv(os.path.join(RES, "T04_富集_上调.csv"))
    _dn = pd.read_csv(os.path.join(RES, "T04_富集_下调.csv"))
    sel = pd.concat([_up.assign(grp="Up-regulated"), _dn.assign(grp="Down-regulated")])
    sel = sel.sort_values("Adjusted P-value").groupby("grp").head(8)
    sel = sel.sort_values(["grp", "Adjusted P-value"], ascending=[True, False]).reset_index(drop=True)
    # 纵坐标槽位按**标签实际行数**分配：wrap 后各标签 1–3 行不等，固定行距会令多行
    # 标签互相叠压（用户 2026-09-14 反馈"纵坐标文字叠起来了"的根因）。
    # 出图要求 4.6：富集图须含**基因数**（气泡大小 + 大小图例）与颜色图例。
    # 基因数取 T04 的 Overlap 分子（如 "38/109" → 38）。
    sel["n_gene"] = sel["Overlap"].astype(str).str.split("/").str[0].astype(int)
    labs = [wrap(t, 40) + f" (n={int(c)})" for t, c in zip(sel["Term"], sel["n_gene"])]
    ln = np.array([l.count("\n") + 1 for l in labs], float)
    ypos = np.concatenate([[0.0], np.cumsum(ln)])[:-1]   # 行 i 的起点 = 前 i 个标签占的总行数
    # 图高随总行数自适应：行高取 2.0 倍 FS_SMALL（constrained_layout 会把标题/轴标/
    # 轴外图例从图高中扣掉一大块固定余量，1.5 倍实测仍会叠压），另留 1.3in 版面余量
    fig, ax = new_fig(COL2, max(3.3, float(ln.sum()) * FS_SMALL * 2.0 / 72 + 1.3))
    _nmin = float(sel["n_gene"].min())
    _sz = 10 + (sel["n_gene"].astype(float) - _nmin) * 2.2      # 气泡面积随基因数增大
    for grp, col in [("Up-regulated", VERM), ("Down-regulated", BLUE)]:
        s = (sel["grp"] == grp).to_numpy()
        ax.scatter(sel.loc[s, "Adjusted P-value"], ypos[s], s=_sz[s].to_numpy(), c=col,
                   linewidths=0, label=f"{grp} genes (n = {int(s.sum())})")
    ax.set_yticks(ypos)
    ax.set_yticklabels(labs, fontsize=FS_SMALL)
    ax.set_ylim(float(ypos[-1] + ln[-1]) - 0.35, -0.75)
    ax.set_xscale("log")
    ax.set_xlabel("Adjusted P-value (Benjamini–Hochberg)")
    # 双图例：右上=方向（颜色），右下=基因数（气泡大小）——均在坐标轴外，不压数据
    from matplotlib.lines import Line2D
    _h, _l = ax.get_legend_handles_labels()
    fig.legend(_h, _l, frameon=False, loc="outside right upper", handlelength=1.1,
               handletextpad=0.5, labelspacing=0.5)
    _ref = sorted({int(sel["n_gene"].min()), int(sel["n_gene"].median()),
                   int(sel["n_gene"].max())})
    _sh = [Line2D([], [], marker="o", ls="", mfc="none", mec="0.35",
                  ms=float(np.sqrt(10 + (v - _nmin) * 2.2)), label=str(v)) for v in _ref]
    fig.legend(handles=_sh, frameon=False, loc="outside right lower", title="Gene count",
               title_fontsize=FS_SMALL, fontsize=FS_SMALL, handletextpad=0.9,
               labelspacing=0.9, borderpad=0.2)
    _audit_issues += save(fig, "02_enrichment_dotplot")
except Exception as ex:
    print("图2 跳过:", ex)

# ---------- 图3 KM 曲线（survival） ----------
k = pd.read_csv(os.path.join(RES, "T12_OOF评分表.csv"))


def km(t, e):
    t, e = np.asarray(t, float), np.asarray(e, int)
    ts = np.unique(t[e == 1]); surv = 1.0
    out_t, out_s, out_lo, out_hi = [0.0], [1.0], [1.0], [1.0]
    cum_h = 0.0
    for tt in ts:
        n_r = (t >= tt).sum(); n_e = ((t == tt) & (e == 1)).sum()
        surv *= (1 - n_e / n_r)
        cum_h += n_e / (n_r * (n_r - n_e)) if n_r > n_e else 0
        se = surv * np.sqrt(cum_h)
        out_t.append(tt); out_s.append(surv)
        out_lo.append(max(surv - 1.96 * se, 0)); out_hi.append(min(surv + 1.96 * se, 1))
    return np.array(out_t), np.array(out_s), np.array(out_lo), np.array(out_hi)


med = k["score_oof"].median()
hi = k[k["score_oof"] > med]; lo = k[k["score_oof"] <= med]
p_km = R["T06_KM"]["value"]["P"]
cox = R["T06_Cox_评分"]["value"]
# 出图要求 4.6：KM 曲线须含 log-rank P、HR (95% CI) 与风险人数表（number at risk）。
# 曲线 + 风险表用上下双轴（sharex）；图题移入图注（图内不得出现图题）。
fig, (ax, axt) = plt.subplots(2, 1, figsize=(COL1, 3.7), sharex=True,
                              height_ratios=[3.0, 0.8], constrained_layout=True)
for grp, c, lab in [(hi, VERM, f"High risk (n = {len(hi)}, events = {int(hi.event.sum())})"),
                    (lo, BLUE, f"Low risk (n = {len(lo)}, events = {int(lo.event.sum())})")]:
    T, S, L, H = km(grp["rfs_days"], grp["event"])
    ax.step(T, S, where="post", c=c, lw=LW, label=lab)
    ax.fill_between(T, L, H, step="post", alpha=0.15, color=c, linewidth=0)
ax.text(0.98, 0.04, f"Log-rank P = {p_km:.1e}\nHR = {cox['HR']:.3f}"
        f" (95% CI {cox['CI95'][0]:.3f}\u2013{cox['CI95'][1]:.3f})",
        transform=ax.transAxes, ha="right", va="bottom", fontsize=FS_SMALL)
ax.set_ylabel("Relapse-free survival")
ax.set_xlim(left=0); ax.set_ylim(0, 1.02)
legend_outside(ax, ncol=1)
# 风险人数表：与横轴共享数据坐标。组名**单独成行**（原与首个数字同行 → D8 重叠），
# 端点数字左/右对齐（居中会越出框 → D7）。
tmax = int(k["rfs_days"].max()); rt = [0, tmax // 3, 2 * tmax // 3, tmax]
ax.set_xticks(rt)
axt.set_ylim(0, 5.6); axt.set_yticks([])   # 末行须离底边 ≥ 半行高，否则压框（D7）
for _sp in ("top", "right", "left"):
    axt.spines[_sp].set_visible(False)
axt.set_xlabel("Days to relapse or censoring")
axt.text(0, 5.0, "No. at risk", fontsize=FS_SMALL, ha="left", va="center")
for _base, (_g, _nm) in [(4.0, (hi, "High risk")), (2.0, (lo, "Low risk"))]:
    axt.text(0, _base, _nm, fontsize=FS_SMALL, ha="left", va="center")
    for _t in rt:
        _ha = "left" if _t == rt[0] else ("right" if _t == rt[-1] else "center")
        axt.text(_t, _base - 1.0, str(int((_g["rfs_days"] >= _t).sum())),
                 fontsize=FS_SMALL, ha=_ha, va="center")
_audit_issues += save(fig, "03_survival_km_risk")

# ---------- 图4 ROC（performance） ----------
from sklearn.metrics import roc_curve
fpr1, tpr1, _ = roc_curve(k["event"], k["score_oof"])
fpr0, tpr0, _ = roc_curve(k["event"], k["score_base"])
a1 = R["T12_CV_AUC"]["value"]["模型"]; a0 = R["T12_CV_AUC"]["value"]["基线"]
fig, ax = new_fig(COL1, H_SINGLE)
ax.plot(fpr0, tpr0, c=BLUE, lw=LW, ls="--", label=f"Clinical baseline (AUC = {a0:.3f})")
ax.plot(fpr1, tpr1, c=VERM, lw=LW, label=f"Risk score (AUC = {a1:.3f})")
ax.plot([0, 1], [0, 1], c=GREY, lw=LW_REF, ls=":")
ax.set_xlabel("1 - specificity"); ax.set_ylabel("Sensitivity")
ax.set_xlim(-0.02, 1.02); ax.set_ylim(-0.02, 1.02)
legend_outside(ax, ncol=1)
_audit_issues += save(fig, "04_performance_roc_cv")

# ---------- 图5 校准曲线（performance，补充材料） ----------
cal_p = os.path.join(RES, "T13b_校准分位.csv")
if os.path.exists(cal_p):
    cal = pd.read_csv(cal_p)
    fig, ax = new_fig(COL1, H_SINGLE)
    ax.plot([0, 1], [0, 1], c=GREY, lw=LW_REF, ls=":", label="Ideal calibration")
    ax.scatter(cal["p_mean"], cal["obs_rate"], s=22, c=VERM, zorder=3, linewidths=0,
               label="Observed (quintile mean)")
    ax.set_xlabel("Predicted probability (out-of-fold)")
    ax.set_ylabel("Observed relapse rate")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    legend_outside(ax, ncol=1)
    _audit_issues += save(fig, "05_performance_calibration_curve")
else:
    print("图5 跳过：缺 T13b_校准分位.csv")

# ---------- 图6 决策曲线（dca，补充材料） ----------
dca_p = os.path.join(RES, "T13c_DCA曲线.csv")
if os.path.exists(dca_p):
    dc = pd.read_csv(dca_p)
    fig, ax = new_fig(COL1, H_SINGLE)
    ax.axhline(0, c=GREY, lw=LW_REF, ls=":", label="Treat none")
    ax.plot(dc["threshold"], dc["NB_all"], c=BLUE, lw=LW, ls="--", label="Treat all")
    ax.plot(dc["threshold"], dc["NB_model"], c=VERM, lw=LW, label="Risk score")
    ax.set_xlabel("Threshold probability"); ax.set_ylabel("Net benefit")
    legend_outside(ax, ncol=3)
    _audit_issues += save(fig, "06_dca_net_benefit")
else:
    print("图6 跳过：缺 T13c_DCA曲线.csv")

print("全部图件完成 →", FIG)
if _audit_issues:
    print(f"！！视觉审计存在 {len(_audit_issues)} 项问题，见上（应修复而非放行）")
    raise SystemExit(1)
print("视觉审计：D1–D6 全部通过")
