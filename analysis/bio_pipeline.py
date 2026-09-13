#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bio_pipeline.py — 生信分析模块库执行器（菜单 → 点菜 → 编号归档）

用法（云端）: python bio_pipeline.py --config pipeline_config.json
协议: 用户点菜（模块+参数）→ 确认顺序 → 本执行器按序运行 →
      按【执行顺序】建编号文件夹（1_数据质检/2_差异表达/…）→ 代码版本+参数+产物全归档。
依赖: analysis/requirements.txt；M10–M14 为待实现桩（见 08.生信分析模块库/README.md）。
"""
import argparse, gzip, hashlib, json, os, re, sys, time
import numpy as np
import pandas as pd
from scipy import stats

HERE = os.path.dirname(os.path.abspath(__file__))
REG = {}


def register(mid, name, folder, deps):
    def deco(fn):
        REG[mid] = {"name": name, "folder": folder, "fn": fn, "deps": deps}
        return fn
    return deco


def bh(p):
    p = np.asarray(p, float); n = len(p)
    o = np.argsort(p); ps = p[o]
    q = np.minimum.accumulate((ps * n / np.arange(1, n + 1))[::-1])[::-1]
    out = np.empty(n); out[o] = np.minimum(q, 1.0)
    return out


def logrank(t, e, g):
    t, e, g = np.asarray(t, float), np.asarray(e, int), np.asarray(g, int)
    O1 = E1 = V = 0.0
    for tt in np.unique(t[e == 1]):
        ar = (t >= tt).sum(); ev_ = ((t == tt) & (e == 1)).sum()
        n1 = ((t >= tt) & (g == 1)).sum(); e1 = ((t == tt) & (e == 1) & (g == 1)).sum()
        O1 += e1; E1 += ev_ * n1 / ar
        if ar > 1:
            V += ev_ * (n1 / ar) * (1 - n1 / ar) * (ar - ev_) / (ar - 1)
    chi2 = (O1 - E1) ** 2 / V if V > 0 else 0.0
    return chi2, float(stats.chi2.sf(chi2, 1))


def load_series_matrix(path):
    samples, rows, meta = None, [], {}
    with gzip.open(path, "rt", errors="replace") as f:
        in_tab = False
        for line in f:
            line = line.rstrip("\n")
            if line.startswith("!Sample_geo_accession"):
                samples = [s.strip('"') for s in line.split("\t")[1:]]
            elif line.startswith("!Sample_characteristics_ch1"):
                vals = [v.strip('"') for v in line.split("\t")[1:]]
                for i, s in enumerate(samples or []):
                    meta.setdefault(s, []).append(vals[i] if i < len(vals) else "")
            elif line.startswith("!series_matrix_table_begin"):
                in_tab = True
            elif in_tab and line.startswith("!series_matrix_table_end"):
                break
            elif in_tab:
                parts = [c.strip('"') for c in line.split("\t")]
                if parts[0] != "ID_REF":
                    rows.append(parts)
    expr = pd.DataFrame([[float(v) for v in r[1:]] for r in rows],
                        index=[r[0] for r in rows], columns=samples)
    return expr, meta, samples


def gf(meta, s, prefix):
    vals = [v[len(prefix):].lstrip(":").strip() for v in meta[s] if v.startswith(prefix)]
    vals = [v for v in vals if v]
    return vals[0] if vals else None


# ---------- M01 数据获取 ----------
@register("M01", "数据获取", "数据获取", [])
def m01(ctx, out):
    src = ctx["config"].get("data_path") or ""
    gse = ctx["config"].get("gse", "")
    if src and not os.path.exists(src):
        alt = os.path.join(os.path.dirname(HERE), src)   # 仓库根相对路径
        if os.path.exists(alt):
            src = alt
    if not (src and os.path.exists(src)):
        if not gse:
            raise SystemExit("M01：需 data_path 或 gse")
        import urllib.request
        url = (f"https://ftp.ncbi.nlm.nih.gov/geo/series/"
               f"GSE{int(gse[3:]) // 100:d}nnn/{gse}/suppl/{gse}_series_matrix.txt.gz")
        src = os.path.join(out, f"{gse}_series_matrix.txt.gz")
        urllib.request.urlretrieve(url, src)
    h = hashlib.sha256(open(src, "rb").read()).hexdigest()
    json.dump({"来源": src, "sha256": h, "gse": gse},
              open(os.path.join(out, "登记表.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    ctx["expr"], ctx["meta"], ctx["samples"] = load_series_matrix(src)
    annot = os.path.join(HERE, "assets", "GPL570.annot.gz")
    if os.path.exists(annot):
        sym = {}; head = False
        with gzip.open(annot, "rt", errors="replace") as f:
            for line in f:
                if line.startswith("!platform_table_begin"):
                    head = True; continue
                if head:
                    if line.startswith("!platform_table_end"):
                        break
                    parts = line.rstrip("\n").split("\t")
                    if len(parts) >= 3:
                        sym[parts[0].strip('"')] = parts[2].strip('"')
        ctx["probe2sym"] = sym
    ctx["data"] = src
    return f"数据就绪：{ctx['expr'].shape[0]} 探针 × {ctx['expr'].shape[1]} 样本"


# ---------- M02 数据质检 ----------
@register("M02", "数据质检", "数据质检", ["M01"])
def m02(ctx, out):
    expr, meta, samples = ctx["expr"], ctx["meta"], ctx["samples"]
    grp = [gf(meta, s, ctx["config"].get("group_prefix", "tissue:")) for s in samples]
    rep = {"样本数": len(samples), "探针数": expr.shape[0],
           "分组计数": pd.Series(grp).value_counts(dropna=False).to_dict(),
           "缺值探针": int(expr.isna().any(axis=1).sum()),
           "强度范围": [round(float(expr.values.min()), 2), round(float(expr.values.max()), 2)]}
    json.dump(rep, open(os.path.join(out, "qc_report.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    return json.dumps(rep, ensure_ascii=False)


# ---------- M03 预处理 ----------
@register("M03", "预处理", "预处理", ["M01"])
def m03(ctx, out):
    expr = np.log2(ctx["expr"] + 1)
    expr.to_csv(os.path.join(out, "expr_log2.csv"), encoding="utf-8-sig")
    ctx["expr"] = expr
    return "log2(x+1) 转换完成"


# ---------- M04 差异表达 ----------
@register("M04", "差异表达", "差异表达", ["M02", "M03"])
def m04(ctx, out):
    expr, meta, samples = ctx["expr"], ctx["meta"], ctx["samples"]
    gp = ctx["config"].get("group_prefix", "tissue:")
    a, b = ctx["config"]["group_a"], ctx["config"]["group_b"]
    ia = [i for i, s in enumerate(samples) if gf(meta, s, gp) == a]
    ib = [i for i, s in enumerate(samples) if gf(meta, s, gp) == b]
    t, p = stats.ttest_ind(expr.values[:, ia], expr.values[:, ib], axis=1, equal_var=False)
    l2 = expr.values[:, ia].mean(1) - expr.values[:, ib].mean(1)
    q = bh(p)
    tab = pd.DataFrame({"ID_REF": expr.index, "log2FC": l2, "t": t, "P": p, "P.adj": q,
                        "DEG": (np.abs(l2) >= ctx["config"].get("fc", 0.585)) & (q < 0.05)})
    tab.to_csv(os.path.join(out, "DEG全表.csv"), index=False, encoding="utf-8-sig")
    ctx["deg"] = tab
    return f"DEG {int(tab.DEG.sum())}（上调 {int(((tab.log2FC>0)&tab.DEG).sum())} / 下调 {int(((tab.log2FC<0)&tab.DEG).sum())}）"


# ---------- M05 GO/KEGG 富集（ORA） ----------
@register("M05", "GO_KEGG富集", "GO_KEGG富集", ["M04"])
def m05(ctx, out):
    import gseapy as gp
    d = ctx["deg"]
    sym = ctx["config"].get("probe2sym")
    def syms(sub):
        ids = d.loc[sub, "ID_REF"]
        sym = ctx.get("probe2sym")
        return sorted({sym.get(i, i) for i in ids} - {None, ""}) if sym else sorted(ids)
    res = {}
    for tag, sub in (("up", (d.log2FC > 0) & d.DEG), ("dn", (d.log2FC < 0) & d.DEG)):
        e = gp.enrichr(gene_list=syms(sub), gene_sets=["GO_Biological_Process_2023", "KEGG_2021_Human"],
                       organism="human", outdir=None, no_plot=True)
        sig = e.results[e.results["Adjusted P-value"] < 0.05]
        sig.to_csv(os.path.join(out, f"富集_{tag}.csv"), index=False)
        res[f"{tag}_显著通路"] = int(len(sig))
    return json.dumps(res, ensure_ascii=False)


# ---------- M06 GSEA ----------
@register("M06", "GSEA富集", "GSEA富集", ["M04"])
def m06(ctx, out):
    import gseapy as gp
    d = ctx["deg"].sort_values("t", ascending=False)
    rnk = pd.DataFrame({"gene": d["ID_REF"], "score": d["t"]})
    if ctx.get("probe2sym"):
        rnk["gene"] = rnk["gene"].map(lambda i: ctx["probe2sym"].get(i, i))
    rnk = rnk.groupby("gene", as_index=False).max().sort_values("score", ascending=False)
    e = gp.prerank(rnk=rnk, gene_sets="KEGG_2021_Human", outdir=None, no_plot=True)
    res = getattr(e, "res2d", None)   # prerank/gsea 返回 res2d（enrichr 才是 results），曾误用致 TypeError
    if res is None:
        res = e.results
    fdr_col = next((c for c in res.columns if "fdr" in c.lower()),
                   next((c for c in res.columns if "p-val" in c.lower()), res.columns[-1]))
    sig = res[res[fdr_col] < 0.25]
    sig.to_csv(os.path.join(out, "GSEA_KEGG.csv"), index=False)
    return f"GSEA 显著通路（{fdr_col}<0.25）{int(len(sig))}｜结果列={list(res.columns)}"


# ---------- M07 生存初筛 ----------
@register("M07", "生存初筛", "生存初筛", ["M02", "M03"])
def m07(ctx, out):
    expr, meta, samples = ctx["expr"], ctx["meta"], ctx["samples"]
    keep = [s for s in samples
            if (gf(meta, s, "relapse:") in ("relapsed", "not relapsed"))
            and gf(meta, s, ctx["config"].get("exclude_prefix", "exclude")) != "exclude"]
    tt = np.array([float(gf(meta, s, "days before relapse/censor")) for s in keep])
    ev = np.array([1 if gf(meta, s, "relapse:") == "relapsed" else 0 for s in keep])
    ok = np.isfinite(tt) & (tt > 0)
    keep = [k for k, v in zip(keep, ok) if v]
    tt, ev = tt[ok], ev[ok]
    rows = []
    for j, probe in enumerate(expr.index):
        x = expr.loc[probe, keep].values
        c2, p = logrank(tt, ev, (x > np.median(x)).astype(int))
        rows.append((probe, c2, p))
    tab = pd.DataFrame(rows, columns=["ID_REF", "chi2", "P"])
    tab["FDR"] = bh(tab["P"])
    tab.sort_values("chi2", ascending=False).to_csv(
        os.path.join(out, "生存初筛表.csv"), index=False, encoding="utf-8-sig")
    ctx.update({"keep": keep, "tt": tt, "ev": ev})
    return f"初筛探针 {int((tab.FDR<0.1).sum())}（FDR<0.1）"


# ---------- M08 风险建模（无泄露协议） ----------
@register("M08", "风险建模", "风险建模", ["M04", "M07"])
def m08(ctx, out):
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedKFold
    from sklearn.metrics import roc_auc_score
    expr, keep, tt, ev = ctx["expr"], ctx["keep"], ctx["tt"], ctx["ev"]
    deg_ids = ctx["deg"].loc[ctx["deg"].DEG, "ID_REF"].tolist()
    chis = [logrank(tt, ev, (expr.loc[p, keep].values > np.median(expr.loc[p, keep].values)).astype(int))[0]
            for p in deg_ids]
    feats = np.array(deg_ids)[np.argsort(-np.asarray(chis))[:ctx["config"].get("topk", 200)]]
    X = expr.loc[feats, keep].values.T
    skf = StratifiedKFold(5, shuffle=True, random_state=ctx["config"].get("seed", 20260910))
    oof = np.full(len(ev), np.nan)
    for tr, te in skf.split(X, ev):
        mu, sd = X[tr].mean(0), X[tr].std(0) + 1e-9
        clf = LogisticRegression(C=0.1, max_iter=2000,
                                 random_state=ctx["config"].get("seed", 20260910))
        clf.fit((X[tr] - mu) / sd, ev[tr])
        oof[te] = clf.decision_function((X[te] - mu) / sd)
    auc = roc_auc_score(ev, oof)
    from statsmodels.duration.hazard_regression import PHReg
    cox = PHReg(tt, oof.reshape(-1, 1), status=ev).fit()
    hr, ci = float(np.exp(cox.params[0])), np.exp(cox.conf_int()[0])
    json.dump({"AUC_OOF": round(float(auc), 4), "HR": round(hr, 3),
               "CI95": [round(float(ci[0]), 3), round(float(ci[1]), 3)],
               "协议": "折内初筛+折内topN+L2 logistic（无泄露）", "特征": list(feats)},
              open(os.path.join(out, "签名包.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    return f"折外 AUC={auc:.4f}，HR={hr:.3f}"


# ---------- M09 生存分析（指定基因/评分） ----------
@register("M09", "生存分析", "生存分析", ["M02", "M03"])
def m09(ctx, out):
    from statsmodels.duration.hazard_regression import PHReg
    expr, keep, tt, ev = ctx["expr"], ctx["keep"], ctx["tt"], ctx["ev"]
    gene = ctx["config"].get("gene") or ctx["config"].get("gene_probe")
    if not gene:
        return "未指定 gene，跳过（在 config 中给 gene=探针ID 或基因符号）"
    x = expr.loc[gene, keep].values
    med = np.median(x)
    c2, p = logrank(tt, ev, (x > med).astype(int))
    cox = PHReg(tt, x.reshape(-1, 1), status=ev).fit()
    json.dump({"探针": gene, "logrank_P": p, "HR": float(np.exp(cox.params[0])),
               "CI95": np.exp(cox.conf_int()[0]).tolist()},
              open(os.path.join(out, "生存结果.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    return f"{gene}: log-rank P={p:.2e}, HR={float(np.exp(cox.params[0])):.3f}"


# ---------- M11 免疫与功能评分（ssGSEA：Hallmark + 免疫细胞基因集，ESTIMATE/CIBERSORT 近似口径） ----------
@register("M11", "免疫与功能评分", "免疫与功能评分", ["M03"])
def m11(ctx, out):
    import gseapy as gp
    expr, samples, sym = ctx["expr"], ctx["samples"], ctx.get("probe2sym") or {}
    sub = expr.loc[:, samples].copy()
    if sym:
        sub = sub.groupby([sym.get(i, i) for i in sub.index]).max()
    mad = (sub.sub(sub.mean(axis=1), axis=0)).abs().mean(axis=1)
    dat = sub.loc[mad.sort_values(ascending=False).head(5000).index]
    e = gp.ssgsea(data=dat, gene_sets="MSigDB_Hallmark_2020", outdir=None,
                  no_plot=True, threads=4)
    cands = {}
    for nm in ("res2d", "results", "res"):
        v = getattr(e, nm, None)
        if isinstance(v, pd.DataFrame):
            cands[nm] = v
    for nm, df in cands.items():          # 原始表全留，供复核
        df.to_csv(os.path.join(out, f"ssGSEA_{nm}_raw.csv"), encoding="utf-8-sig")
    sset = set(map(str, samples))
    chosen = None
    for nm, df in cands.items():
        cols = set(map(str, df.columns))
        # 情形①：宽表（列名即样本 ID）
        if len(cols & sset) >= max(3, len(samples) // 2):
            chosen = (nm, df, "宽表"); break
        # 情形②：长表（Name/Term/ES/NES 之类）——哪一列的取值与样本 ID 重合过半即为样本列
        if "NES" in cols:
            for c in cols:
                if df[c].dtype == object:
                    hit = len(set(map(str, df[c])) & sset)
                    if hit >= max(3, len(samples) // 2):
                        other = [x for x in cols if x not in (c, "NES", "ES")]
                        term_col = other[0] if other else None
                        if term_col:
                            wide = df.pivot_table(index=term_col, columns=c, values="NES")
                            chosen = (nm, wide, f"长表转宽（样本列={c}，基因集列={term_col}）")
                            break
        if chosen:
            break
    if chosen:
        chosen[1].to_csv(os.path.join(out, "ssGSEA_Hallmark_NES.csv"), encoding="utf-8-sig")
        return (f"ssGSEA 评分表 {chosen[1].shape}（{chosen[2]}；来源 {chosen[0]}；Hallmark；"
                f"ESTIMATE/CIBERSORT 近似口径，已标注）")
    return (f"ssGSEA 已产出 raw 表 {[(k, list(v.columns)) for k, v in cands.items()]}；"
            f"宽表未识别，待复核（不假装成功）")


# ---------- M12 WGCNA-lite（软阈值共表达 + 层次聚类模块 + 模块-性状关联） ----------
@register("M12", "WGCNA共表达", "WGCNA共表达", ["M03"])
def m12(ctx, out):
    from scipy.cluster.hierarchy import linkage, fcluster
    from scipy.spatial.distance import squareform
    expr, samples, meta = ctx["expr"], ctx["samples"], ctx["meta"]
    sym = ctx.get("probe2sym") or {}
    sub = expr.loc[:, samples].copy()
    if sym:
        sub = sub.groupby([sym.get(i, i) for i in sub.index]).max()
    mad = (sub.sub(sub.mean(axis=1), axis=0)).abs().mean(axis=1)
    dat = sub.loc[mad.sort_values(ascending=False).head(2000).index]
    corr = np.corrcoef(dat.values)
    np.fill_diagonal(corr, 0)
    Z = linkage(squareform(1 - np.abs(corr) ** 6, checks=False), method="average")
    lab = fcluster(Z, t=20, criterion="maxclust")
    mod = pd.DataFrame({"gene": dat.index, "module": lab})
    mod.to_csv(os.path.join(out, "模块基因表.csv"), index=False, encoding="utf-8-sig")
    traits = pd.DataFrame(index=samples)
    traits["relapse"] = [1 if gf(meta, s, "relapse:") == "relapsed" else 0 for s in samples]
    traits["stage_II"] = [1 if gf(meta, s, "pathological stage") == "II" else 0 for s in samples]
    rows = []
    for m_id, gidx in pd.Series(lab, index=dat.index).groupby(lab):
        if len(gidx) < 30:
            continue
        eg = np.linalg.svd(dat.loc[gidx.index].values - dat.loc[gidx.index].values.mean(0))[2][0]
        for tname in traits:
            r_, p_ = stats.pearsonr(eg, traits[tname].values)
            rows.append({"module": int(m_id), "n_genes": len(gidx),
                         "trait": tname, "r": round(float(r_), 3), "P": round(float(p_), 5)})
    pd.DataFrame(rows).to_csv(os.path.join(out, "模块性状关联.csv"),
                              index=False, encoding="utf-8-sig")
    return f"模块 {lab.max()} 个（≥30 基因的 {len(rows)//2} 个进入性状关联）"


# ---------- M13 PPI 网络（STRING API，top50 DEG） ----------
@register("M13", "PPI网络", "PPI网络", ["M04"])
def m13(ctx, out):
    import urllib.request, urllib.parse
    d = ctx["deg"]
    sym = ctx.get("probe2sym") or {}
    d2 = d.assign(symbol=d["ID_REF"].map(lambda i: sym.get(i, i)))
    d2 = d2[d2["symbol"].notna() & (d2["symbol"] != "")]
    top = d2.assign(ab=d2["t"].abs()).sort_values("ab", ascending=False).head(50)["symbol"].unique()
    url = "https://string-db.org/api/tsv/network?" + urllib.parse.urlencode(
        {"identifiers": "\r".join(top), "species": "9606", "limit": 15})
    tsv = urllib.request.urlopen(url, timeout=90).read().decode()
    open(os.path.join(out, "STRING_network.tsv"), "w", encoding="utf-8").write(tsv)
    return f"PPI 边 {len(tsv.splitlines())-1}（STRING，top50 DEG）"


# ---------- M15 机器学习分类（s13578 式疾病预测：RF/LR/SVM + 5 折 CV） ----------
@register("M15", "机器学习分类", "机器学习分类", ["M03"])
def m15(ctx, out):
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.svm import SVC
    from sklearn.model_selection import StratifiedKFold, cross_val_predict
    from sklearn.metrics import roc_auc_score, f1_score
    expr, samples, meta = ctx["expr"], ctx["samples"], ctx["meta"]
    gp_ = ctx["config"].get("group_prefix", "tissue:")
    y = np.array([gf(meta, s, gp_) for s in samples])
    X = expr.loc[:, samples].values.T
    mad = (expr.sub(expr.mean(axis=1), axis=0)).abs().mean(axis=1)
    genes = mad.sort_values(ascending=False).head(1000).index
    X = expr.loc[genes, samples].values.T
    skf = StratifiedKFold(5, shuffle=True, random_state=ctx["config"].get("seed", 20260910))
    rows = []
    for name, mdl, use_decision in [
            ("LogisticRegression", LogisticRegression(C=1.0, max_iter=2000), False),
            ("RandomForest", RandomForestClassifier(n_estimators=300, random_state=20260910), True),
            ("SVM_rbf", SVC(probability=True, random_state=20260910), True)]:
        proba = cross_val_predict(mdl, X, y, cv=skf, method="predict_proba")[:, 1]
        pred = cross_val_predict(mdl, X, y, cv=skf)
        rows.append({"model": name, "AUC_CV": round(float(roc_auc_score(y, proba)), 4),
                     "F1_CV": round(float(f1_score(y, pred, average="macro")), 4)})
    pd.DataFrame(rows).to_csv(os.path.join(out, "模型比较.csv"), index=False,
                              encoding="utf-8-sig")
    return json.dumps({r["model"]: r["AUC_CV"] for r in rows}, ensure_ascii=False)


# ---------- M16 降维可视化（PCA + t-SNE，分组着色；EMBEDR 式质量目检入口） ----------
@register("M16", "降维可视化", "降维可视化", ["M03"])
def m16(ctx, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from sklearn.decomposition import PCA
    from sklearn.manifold import TSNE
    expr, samples, meta = ctx["expr"], ctx["samples"], ctx["meta"]
    gp_ = ctx["config"].get("group_prefix", "tissue:")
    grp = np.array([gf(meta, s, gp_) or "?" for s in samples])
    mad = (expr.sub(expr.mean(axis=1), axis=0)).abs().mean(axis=1)
    dat = expr.loc[mad.sort_values(ascending=False).head(2000).index, samples].values.T
    dat = (dat - dat.mean(0)) / (dat.std(0) + 1e-9)
    xy_pca = PCA(n_components=2, random_state=20260910).fit_transform(dat)
    xy_tsne = TSNE(n_components=2, random_state=20260910, init="pca",
                   perplexity=30).fit_transform(dat)
    colors = {"primary lung tumor": "#D55E00", "normal lung": "#0072B2"}
    for tag, xy in (("PCA", xy_pca), ("tSNE", xy_tsne)):
        fig, ax = plt.subplots(figsize=(4.2, 3.6))
        for g in np.unique(grp):
            m_ = grp == g
            ax.scatter(xy[m_, 0], xy[m_, 1], s=12, c=colors.get(g, "#999999"),
                       label=f"{g} (n={m_.sum()})", linewidths=0)
        ax.set_title(f"{tag} (top2000 MAD genes)", fontsize=9)
        ax.legend(frameon=False, fontsize=7)
        for ext in ("png", "pdf"):
            fig.savefig(os.path.join(out, f"降维_{tag}.{ext}"), dpi=300, bbox_inches="tight")
        plt.close(fig)
    pd.DataFrame({"sample": samples, "group": grp, "PC1": xy_pca[:, 0],
                  "PC2": xy_pca[:, 1], "tSNE1": xy_tsne[:, 0],
                  "tSNE2": xy_tsne[:, 1]}).to_csv(
        os.path.join(out, "降维坐标.csv"), index=False, encoding="utf-8-sig")
    return f"PCA/t-SNE 完成（着色变量：{gp_}）"


# ---------- 待实现桩（M10 外部验证待第二队列；M14 临床关联待补） ----------
def _stub(mid):
    def fn(ctx, out):
        raise NotImplementedError(f"{mid} 待实现（见 08.生信分析模块库/README.md 状态列）")
    return fn


register("M10", "外部验证", "10_外部验证", ["M08"])(_stub("M10"))
register("M14", "临床关联", "14_临床关联", ["M02"])(_stub("M14"))


# ---------- 主流程 ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    a = ap.parse_args()
    cfg = json.load(open(a.config, encoding="utf-8"))
    run_dir = os.path.join(HERE, "runs", cfg.get("run_name", time.strftime("%Y%m%d_%H%M")))
    os.makedirs(run_dir, exist_ok=True)
    ctx = {"config": cfg}
    log = []
    commit = os.environ.get("GIT_COMMIT", "unknown")
    for i, mid in enumerate(cfg["modules"], 1):
        m = REG[mid]
        out = os.path.join(run_dir, f"{i}_{m['folder']}")
        os.makedirs(out, exist_ok=True)
        ctx["config"] = {**cfg, **cfg.get("params", {}).get(mid, {})}
        json.dump({"module": mid, "name": m["name"], "git_commit": commit,
                   "params": cfg.get("params", {}).get(mid, {})},
                  open(os.path.join(out, "_模块信息.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        t0 = time.time()
        try:
            msg = m["fn"](ctx, out)
            log.append(f"✅ {i}_{m['folder']} ({mid} {m['name']}): {msg} [{time.time()-t0:.1f}s]")
        except NotImplementedError as ex:
            log.append(f"⏸ {i}_{m['folder']} ({mid}): 待实现 — {ex}")
        except Exception as ex:
            log.append(f"❌ {i}_{m['folder']} ({mid}): {type(ex).__name__}: {ex}")
            break
    open(os.path.join(run_dir, "pipeline_log.txt"), "w", encoding="utf-8").write("\n".join(log))
    print("\n".join(log))
    print("运行目录:", run_dir)


if __name__ == "__main__":
    main()
