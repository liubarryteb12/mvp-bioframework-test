#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_figures.py — U07 图件（作图规范 v1.0 口径）
四图 × 四格式（pdf/tiff/png/jpg，300dpi；jpg 走 pil_kwargs quality）
命名 {NN}_{analysis_step}_{description}.{ext}，stage_tag ∈ criteria.yaml 标签集
色板：Wong 2011；成对比较使用 蓝 #0072B2 / 朱红 #D55E00（非等亮度红绿对）
"""
import io, json, os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import stats

SEED = 20260910
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(BASE, "results"); FIG = os.path.join(BASE, "figures")
os.makedirs(FIG, exist_ok=True)
BLUE, VERM, GREY = "#0072B2", "#D55E00", "#999999"
plt.rcParams.update({"font.size": 9, "axes.linewidth": 0.8, "font.family": "DejaVu Sans",
                     "pdf.fonttype": 42, "ps.fonttype": 42})   # C-4：出版 PDF 须 Type0/TrueType，禁止 Type3


def save(fig, name):
    from PIL import Image
    for ext, kw in [("pdf", {}), ("tiff", {}), ("png", {}), ("jpg", dict(pil_kwargs={"quality": 95}))]:
        p = os.path.join(FIG, f"{name}.{ext}")
        fig.savefig(p, dpi=300, bbox_inches="tight", **kw)
        if ext in ("png", "tiff"):          # C-6 色彩模式：RGB（matplotlib 默认 RGBA）
            with open(p, "rb") as f:        # 先读入内存，避免 PIL 句柄与写回冲突（曾致 Errno 22）
                data = f.read()
            im = Image.open(io.BytesIO(data))
            if im.mode != "RGB":
                bg = Image.new("RGB", im.size, (255, 255, 255))
                bg.paste(im, mask=im.split()[-1] if im.mode in ("RGBA", "LA") else None)
                buf = io.BytesIO()
                bg.save(buf, format="TIFF" if ext == "tiff" else "PNG", dpi=(300, 300))
                tmp = p + ".tmp"
                with open(tmp, "wb") as f:
                    f.write(buf.getvalue())
                os.replace(tmp, p)
                im.close()
    plt.close(fig)
    print("图件:", name, "×4 格式")


R = json.load(open(os.path.join(RES, "results.json"), encoding="utf-8"))

# ---------- 图1 火山图（deg） ----------
d = pd.read_csv(os.path.join(RES, "T02_差异表达全表.csv"))
d["-log10P"] = -np.log10(d["P"].clip(lower=1e-300))
fig, ax = plt.subplots(figsize=(4.2, 3.4))
m = ~d["DEG"].astype(bool)
ax.scatter(d.loc[m, "log2FC"], d.loc[m, "-log10P"], s=2, c=GREY, alpha=0.3, linewidths=0)
up = d["DEG"].astype(bool) & (d["log2FC"] > 0); dn = d["DEG"].astype(bool) & (d["log2FC"] < 0)
ax.scatter(d.loc[up, "log2FC"], d.loc[up, "-log10P"], s=3, c=VERM, linewidths=0, label=f"Up ({up.sum()})")
ax.scatter(d.loc[dn, "log2FC"], d.loc[dn, "-log10P"], s=3, c=BLUE, linewidths=0, label=f"Down ({dn.sum()})")
ax.axhline(-np.log10(0.05), ls="--", lw=0.6, c="k"); ax.axvline(0.585, ls="--", lw=0.6, c="k"); ax.axvline(-0.585, ls="--", lw=0.6, c="k")
ax.set_xlabel("log2 fold change (tumor vs normal)"); ax.set_ylabel("-log10 P (Welch t)")
ax.legend(frameon=False, loc="upper center", ncol=2)
n = R["T02_DEG"]["value"]
ax.set_title(f"Differential expression, GSE31210 (n = 246)", fontsize=9)
save(fig, "01_deg_volcano")

# ---------- 图2 富集点图（enrichment） ----------
try:
    up = pd.read_csv(os.path.join(RES, "T04_富集_上调.csv"))
    dn = pd.read_csv(os.path.join(RES, "T04_富集_下调.csv"))
    sel = pd.concat([up.assign(grp="Up-regulated"), dn.assign(grp="Down-regulated")])
    sel = sel.sort_values("Adjusted P-value").groupby("grp").head(8)
    sel = sel.sort_values(["grp", "Adjusted P-value"], ascending=[True, False])
    fig, ax = plt.subplots(figsize=(5.0, 3.6))
    y = np.arange(len(sel))
    ax.scatter(sel["Adjusted P-value"], y, s=34, c=[VERM if g == "Up-regulated" else BLUE for g in sel["grp"]])
    ax.set_yticks(y); ax.set_yticklabels([t[:46] for t in sel["Term"]], fontsize=6)
    ax.set_xscale("log"); ax.set_xlabel("Adjusted P-value (BH)")
    ax.set_title("GO/KEGG enrichment of DEGs (Enrichr)", fontsize=9)
    from matplotlib.lines import Line2D
    ax.legend(handles=[Line2D([0], [0], marker="o", color="w", markerfacecolor=VERM, label="Up"),
                       Line2D([0], [0], marker="o", color="w", markerfacecolor=BLUE, label="Down")],
              frameon=False, loc="lower right")
    save(fig, "02_enrichment_dotplot")
except Exception as ex:
    print("图2 跳过:", ex)

# ---------- 图3 KM 曲线（survival） ----------
k = pd.read_csv(os.path.join(RES, "T12_OOF评分表.csv"))


def km(t, e):
    t, e = np.asarray(t, float), np.asarray(e, int)
    ts = np.unique(t[e == 1]); S = 1.0; out_t, out_s, out_lo, out_hi = [0.0], [1.0], [1.0], [1.0]
    cum_h = 0.0
    for tt in ts:
        n_r = (t >= tt).sum(); n_e = ((t == tt) & (e == 1)).sum()
        S *= (1 - n_e / n_r)
        cum_h += n_e / (n_r * (n_r - n_e)) if n_r > n_e else 0
        se = S * np.sqrt(cum_h)
        out_t.append(tt); out_s.append(S); out_lo.append(max(S - 1.96 * se, 0)); out_hi.append(min(S + 1.96 * se, 1))
    return np.array(out_t), np.array(out_s), np.array(out_lo), np.array(out_hi)


med = k["score_oof"].median()
hi = k[k["score_oof"] > med]; lo = k[k["score_oof"] <= med]
p_km = R["T06_KM"]["value"]["P"]
fig, ax = plt.subplots(figsize=(4.2, 3.4))
for grp, c, lab in [(hi, VERM, f"High risk (n={len(hi)}, events={int(hi.event.sum())})"),
                    (lo, BLUE, f"Low risk (n={len(lo)}, events={int(lo.event.sum())})")]:
    T, S, L, H = km(grp["rfs_days"], grp["event"])
    ax.step(T, S, where="post", c=c, lw=1.4, label=lab)
    ax.fill_between(T, L, H, step="post", alpha=0.15, color=c)
ax.set_xlabel("Days to relapse or censoring"); ax.set_ylabel("Relapse-free survival")
ax.set_ylim(0, 1.02); ax.legend(frameon=False, loc="lower left", fontsize=7.5)
ax.set_title(f"Risk score (out-of-fold), log-rank P = {p_km:.1e}", fontsize=9)
save(fig, "03_survival_km_risk")

# ---------- 图4 ROC（performance） ----------
from sklearn.metrics import roc_curve, roc_auc_score
fpr1, tpr1, _ = roc_curve(k["event"], k["score_oof"])
fpr0, tpr0, _ = roc_curve(k["event"], k["score_base"])
a1 = R["T12_CV_AUC"]["value"]["模型"]; a0 = R["T12_CV_AUC"]["value"]["基线"]
fig, ax = plt.subplots(figsize=(3.8, 3.6))
ax.plot(fpr1, tpr1, c=VERM, lw=1.4, label=f"Risk score, AUC = {a1:.3f}")
ax.plot(fpr0, tpr0, c=BLUE, lw=1.4, ls="--", label=f"Clinical baseline, AUC = {a0:.3f}")
ax.plot([0, 1], [0, 1], c=GREY, lw=0.8, ls=":")
ax.set_xlabel("1 - Specificity"); ax.set_ylabel("Sensitivity")
ax.legend(frameon=False, loc="lower right", fontsize=7.5)
ax.set_title("Relapse prediction, 5-fold CV (out-of-fold)", fontsize=9)
save(fig, "04_performance_roc_cv")

# ---------- 图5 校准曲线（performance，补充材料） ----------
cal_p = os.path.join(RES, "T13b_校准分位.csv")
if os.path.exists(cal_p):
    cal = pd.read_csv(cal_p)
    fig, ax = plt.subplots(figsize=(3.8, 3.6))
    ax.scatter(cal["p_mean"], cal["obs_rate"], s=30, c=VERM, zorder=3)
    ax.plot([0, 1], [0, 1], c=GREY, lw=0.8, ls=":")
    ax.set_xlabel("Predicted probability (out-of-fold)")
    ax.set_ylabel("Observed relapse rate")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.set_title("Calibration, quintiles of OOF risk", fontsize=9)
    save(fig, "05_performance_calibration_curve")
else:
    print("图5 跳过：缺 T13b_校准分位.csv")

# ---------- 图6 决策曲线（dca，补充材料） ----------
dca_p = os.path.join(RES, "T13c_DCA曲线.csv")
if os.path.exists(dca_p):
    dc = pd.read_csv(dca_p)
    fig, ax = plt.subplots(figsize=(3.8, 3.6))
    ax.plot(dc["threshold"], dc["NB_model"], c=VERM, lw=1.4, label="Risk score")
    ax.plot(dc["threshold"], dc["NB_all"], c=BLUE, lw=1.2, ls="--", label="Treat all")
    ax.axhline(0, c=GREY, lw=0.8, ls=":", label="Treat none")
    ax.set_xlabel("Threshold probability"); ax.set_ylabel("Net benefit")
    ax.legend(frameon=False, fontsize=7.5)
    ax.set_title("Decision curve, 5-year relapse (GVH)", fontsize=9)
    save(fig, "06_dca_net_benefit")
else:
    print("图6 跳过：缺 T13c_DCA曲线.csv")

print("全部图件完成 →", FIG)
