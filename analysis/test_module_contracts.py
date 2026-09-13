# -*- coding: utf-8 -*-
"""test_module_contracts.py — 模块契约冒烟测试（无数据文件、秒级、云端 pytest 执行）。

契约来源：`08.生信分析模块库/模块开发规范.md`（内化自 `10.代码生成规范参考`）。
覆盖五类契约：
  ① 注册表契约：编号规范、字段齐全、依赖已注册；
  ② 配置契约：所有 pipeline_config*.json 只引用已注册模块、装配可校验；
  ③ 纯函数数值契约：bh / logrank 的已知值；
  ④ 结构适配器回归：to_wide 对宽表、长表（pandas 3 字符串 dtype）、不可识别三态；
  ⑤ 插件与确定性：插件目录可加载、新模块无硬编码阈值、同输入同输出。

设计原则：只测契约与纯函数，不依赖任何数据文件（可离线、可云端、秒级）。
"""
import importlib.util
import json
import os
import re
import sys

import numpy as np
import pandas as pd
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bio_pipeline as bp  # noqa: E402

# 先加载插件（新模块以文件形式增量加入），否则配置校验会误报"未注册模块"
_LOADED_PLUGINS = bp.load_plugins()


# ---------- ① 注册表契约 ----------
def test_registry_ids_wellformed_and_unique():
    assert bp.REG, "注册表为空"
    for mid in bp.REG:
        assert re.fullmatch(r"M\d{2}[A-Za-z]?", mid), f"编号不合规：{mid}"


def test_registry_entries_have_full_contract():
    for mid, m in bp.REG.items():
        for key in ("name", "folder", "fn", "deps"):
            assert key in m, f"{mid} 缺字段 {key}"
        assert isinstance(m["name"], str) and m["name"], f"{mid} name 为空"
        assert isinstance(m["folder"], str) and m["folder"], f"{mid} folder 为空"
        assert callable(m["fn"]), f"{mid} fn 不可调用"
        assert isinstance(m["deps"], list), f"{mid} deps 必须是列表"
        for d in m["deps"]:
            assert d in bp.REG, f"{mid} 依赖未注册模块 {d}"


# ---------- ② 配置契约 ----------
@pytest.mark.parametrize("cfg_path", sorted(
    __import__("glob").glob(os.path.join(HERE, "pipeline_config*.json"))))
def test_configs_reference_registered_modules(cfg_path):
    cfg = json.load(open(cfg_path, encoding="utf-8"))
    assert isinstance(cfg.get("modules"), list) and cfg["modules"], "modules 不能为空"
    errs, _warns = bp.validate_config(cfg)
    assert not errs, f"{os.path.basename(cfg_path)} 装配致命错误：{errs}"
    for mid in cfg["modules"]:
        params = cfg.get("params", {}).get(mid, {})
        assert isinstance(params, dict), f"{mid} 的 params 必须是对象"


def test_validate_config_rejects_unknown_module():
    errs, _ = bp.validate_config({"modules": ["M99"]})
    assert errs and "M99" in errs[0]


# ---------- ③ 纯函数数值契约 ----------
def test_bh_matches_manual_value():
    p = np.array([0.01, 0.02, 0.03, 0.04, 0.05])
    assert np.allclose(bp.bh(p), 0.05, atol=1e-12)


def test_bh_is_monotone_and_bound_to_one():
    p = np.array([0.001, 0.5, 0.2, 0.9])
    q = bp.bh(p)
    assert np.all(q <= 1.0) and np.all(q >= 0.0)
    order = np.argsort(p)
    assert np.all(np.diff(q[order]) >= -1e-12), "BH 校正后应随 p 单调不减"


def test_logrank_detects_separation_and_null():
    e = np.ones(8, dtype=int)
    # 分离组：早期事件集中在一组 → 应显著
    chi_sep, p_sep = bp.logrank(np.array([1., 2, 3, 4, 5, 6, 7, 8]), e,
                                np.array([0, 0, 0, 0, 1, 1, 1, 1]))
    assert chi_sep > 0 and p_sep < 0.05, "完全分离的两组应显著"
    # 真实零假设：两组经历同一事件时间（观察数 = 期望数）→ chi² 恰为 0
    chi_null, p_null = bp.logrank(np.full(8, 5.0), e, np.array([0, 1, 0, 1, 0, 1, 0, 1]))
    assert chi_null == pytest.approx(0.0, abs=1e-9), f"零假设下应无信号，实际 {chi_null}"
    assert p_null > 0.9


# ---------- ④ 结构适配器回归（M11 宽表识别） ----------
def _long_table(samples, terms, dtype_str=True):
    rows = []
    for s in samples:
        for k, tm in enumerate(terms):
            rows.append({("Name" if dtype_str else "sample"): s,
                         ("Term" if dtype_str else "geneset"): tm,
                         "ES": 100.0 + k, "NES": 0.5 + 0.01 * k})
    df = pd.DataFrame(rows)
    if dtype_str:                       # 显式转成 pandas 3 的字符串 dtype（回归点）
        df["Name"] = df["Name"].astype("str")
        df["Term"] = df["Term"].astype("str")
    return df


def test_to_wide_passthrough_for_wide_input():
    samples = ["GSM1", "GSM2", "GSM3"]
    wide = pd.DataFrame(np.ones((4, 3)), index=["g1", "g2", "g3", "g4"], columns=samples)
    out, why = bp.to_wide(wide, samples)
    assert out is not None and out.shape == (4, 3) and "宽表" in why


def test_to_wide_from_long_table_with_str_dtype():
    samples = [f"GSM{i}" for i in range(6)]
    terms = ["E2F Targets", "Mitotic Spindle", "G2M Checkpoint"]
    out, why = bp.to_wide(_long_table(samples, terms), samples)
    assert out is not None, f"长表应能转宽（回归：pandas 3 str dtype），实际原因：{why}"
    assert set(out.columns) == set(samples), "列应为样本"
    assert set(out.index) == set(terms), "行应为基因集"
    assert out.loc["E2F Targets", "GSM0"] == pytest.approx(0.5)


def test_to_wide_reports_failure_instead_of_pretending():
    df = pd.DataFrame({"a": ["x", "y"], "b": [1.0, 2.0], "NES": [0.1, 0.2]})
    out, why = bp.to_wide(df, ["GSM1", "GSM2", "GSM3"])
    assert out is None and "无列取值与样本 ID 重合过半" in why


def test_to_wide_is_deterministic():
    samples = [f"GSM{i}" for i in range(5)]
    terms = ["T1", "T2"]
    df = _long_table(samples, terms)
    a, _ = bp.to_wide(df, samples)
    b, _ = bp.to_wide(df, samples)
    assert a.equals(b)


# ---------- ⑤ 插件契约 ----------
def _load_plugin(fname):
    path = os.path.join(HERE, "modules", fname)
    spec = importlib.util.spec_from_file_location(f"plug_{fname[:-3]}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_plugin_modules_are_loadable_and_registered():
    loaded = bp.load_plugins()
    assert "M17" in loaded, f"插件未加载成功，实际加载：{loaded}"
    assert "M17" in bp.REG
    for mid in loaded:
        assert bp.REG[mid]["fn"] is not None


def test_plugin_rejects_hardcoded_default_threshold():
    """阈值必须来自 config：缺参必须报错，而不是偷偷用默认值。"""
    mod = _load_plugin("m17_sample_similarity.py")
    with pytest.raises(ValueError):
        mod.run({"config": {}, "expr": pd.DataFrame(np.ones((3, 3))),
                 "samples": ["a", "b", "c"]}, os.getcwd())


def test_plugin_sample_similarity_flags_planted_outlier():
    mod = _load_plugin("m17_sample_similarity.py")
    rng = np.random.default_rng(7)
    latent = rng.normal(size=(60, 1))
    core = latent @ np.ones((1, 8)) + rng.normal(scale=0.3, size=(60, 8))
    alien = rng.normal(scale=1.0, size=(60, 1))
    expr = pd.DataFrame(np.column_stack([core, alien]),
                        columns=[f"S{i}" for i in range(9)],
                        index=[f"G{j}" for j in range(60)])
    cm, cand = mod.sample_similarity(expr, 0.8)
    assert cm.shape == (9, 9)
    assert cand.iloc[0]["sample"] == "S8" and bool(cand.iloc[0]["outlier"]), \
        "植入的离群样本应被识别为最低中位相关"
    assert not cand.iloc[1:]["outlier"].any(), "同源样本不应误判"


def test_plugin_sample_similarity_refuses_tiny_design():
    mod = _load_plugin("m17_sample_similarity.py")
    expr = pd.DataFrame(np.ones((5, 2)), columns=["a", "b"])
    assert mod.sample_similarity(expr, 0.8) == (None, None)
