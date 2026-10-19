"""P2 核心：观点 × 数据 交叉核验。

把「张雪峰定性观点（推荐/慎选/避坑）」与「后端定量录取数据（可达批次/冲稳保）」做一致性校验，
输出 alignment（一致/需谨慎/冲突）与可执行建议，强化偏见校正层。
"""
from .admission import analyze_major, classify
from .content import VIEW_LABEL

# 高危低位次批次：在这些批次读到"推荐"专业，需提示 bias 风险
LOW_TIERS = {"普通二本", "专科"}


def verify(province: str, subject: str, user_rank: int, major_name: str, major_cat: str,
           view: str, reason: str, bias: str) -> dict:
    """交叉核验单个专业。"""
    ana = analyze_major(province, subject, user_rank, major_name, major_cat)
    if not ana["ok"]:
        return ana

    best = ana["best_reachable"]
    if best is None:
        # 用户位次无法达到该专业的任何批次
        alignment = "conflict"
        message = (f"你的位次（{user_rank}）在所有批次都够不到「{major_name}」"
                   f"（最易批次门槛位次 {ana['tiers'][-1]['min_rank']}），"
                   f"该专业当前对你属于「不可及」，建议优先看冲稳保梯度内的专业。")
        suggestions = [
            "回到诊断画布查看可达专业清单（数据侧已按你的位次筛出 冲/稳/保）",
            "若坚持该专业，需显著提高位次或考虑同大类更易录取的方向",
        ]
        return _pack(province, subject, user_rank, major_name, view, reason, bias, ana,
                     alignment, message, suggestions)

    best_tier = best["tier"]
    best_level = best["level"]

    # —— 一致性判定 ——
    if view == "recommend":
        if best_tier in LOW_TIERS:
            alignment = "caution"
            message = (f"「{major_name}」张雪峰视角为<b>推荐</b>，但你的位次只能摸到"
                       f"<b>{best_tier}</b>层次（门槛位次 {best['min_rank']}，判定「{best_level}」）。"
                       f"该推荐通常假设进入较优质的培养单位；低位次段就读时，原 bias 提示的风险会被放大。")
            suggestions = [
                f"对照 bias 提示逐条评估：{bias}",
                "若只能读低位次院校，优先选 same 大类中门槛更低但仍有壁垒的方向",
                "用资源中心的 gaokao-advisor 核验该专业在你位次段的真实招生量",
            ]
        else:
            alignment = "aligned"
            message = (f"「{major_name}」张雪峰视角为<b>推荐</b>，且你的位次可够到"
                       f"<b>{best_tier}</b>层次（门槛位次 {best['min_rank']}，判定「{best_level}」），"
                       f"观点与数据方向一致，可作为重点候选。")
            suggestions = [
                f"仍需核对 bias 提示，避免把推荐当定论：{bias}",
                "用资源中心工具核验该专业目标院校的真实录取位次波动",
            ]
    elif view == "caution":
        alignment = "caution"
        message = (f"「{major_name}」张雪峰视角为<b>慎选</b>，你的位次可摸到"
                   f"<b>{best_tier}</b>层次（判定「{best_level}」）。"
                   f"该专业并非完全不可，但需满足条件（如深造/转方向）才成立。")
        suggestions = [
            f"关键看 bias 提示里的「前提条件」：{bias}",
            "仅在能满足前提（如坚定读研、能啃硬课）时纳入",
        ]
    else:  # avoid
        if best_tier in LOW_TIERS:
            alignment = "conflict"
            message = (f"「{major_name}」张雪峰视角为<b>避坑</b>，而你的位次正好落在"
                       f"<b>{best_tier}</b>层次——这正是该观点最不推荐的处境，建议坚决规避或仅作保底。")
            suggestions = [
                f"务必阅读 bias 提示里的「例外方向」：{bias}",
                "优先用数据侧筛出的 稳/保 专业替换",
            ]
        else:
            alignment = "caution"
            message = (f"「{major_name}」张雪峰视角为<b>避坑</b>，但你的位次能摸到"
                       f"<b>{best_tier}</b>层次（判定「{best_level}」）。"
                       f"若你确有资源/热爱，可在充分了解风险后谨慎考虑。")
            suggestions = [
                f"仅当满足 bias 提示中的例外（如热爱科研且规划读博）才考虑：{bias}",
                "普通家庭无背景时，建议仍按避坑处理",
            ]

    return _pack(province, subject, user_rank, major_name, view, reason, bias, ana,
                 alignment, message, suggestions)


def _pack(province, subject, user_rank, major_name, view, reason, bias, ana,
          alignment, message, suggestions) -> dict:
    return {
        "ok": True,
        "province": province, "subject": subject, "user_rank": user_rank,
        "major": major_name,
        "view": view, "view_label": VIEW_LABEL.get(view, view),
        "reason": reason, "bias": bias,
        "best_reachable": ana["best_reachable"],
        "tiers": ana["tiers"],
        "alignment": alignment,
        "alignment_label": {"aligned": "观点与数据一致", "caution": "需谨慎", "conflict": "存在冲突"}[alignment],
        "message": message,
        "suggestions": suggestions,
        "data_source": ana["data_source"],
    }
