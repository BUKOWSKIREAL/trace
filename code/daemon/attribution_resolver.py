"""
Weighted attribution resolver.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable

from daemon.detectors import scan_active_agents, scan_global_active_agents
from daemon.detectors.transcript_detector import find_transcript_attribution
from models.agent import AgentAttribution, AgentInstance

METHOD_WEIGHTS = {
    "activity_fs_usage": 0.98,
    "activity_transcript": 0.93,
    "transcript_claude": 0.93,
    "transcript_codex": 0.93,
    "activity_psutil_poll": 0.80,
    "workspace_cli": 0.95,
    "gui_app": 0.85,
    "local_script": 0.82,
    "global_cli_fallback": 0.65,
}

AMBIGUITY_GAP = 0.08


def _weight_for(method: str, confidence: float) -> float:
    base = METHOD_WEIGHTS.get(method, confidence)
    return max(base, confidence)


def resolve_attribution(
    workspace: Path,
    file_path: Path,
    *,
    event_time: float | None = None,
    override_agent: str | None = None,
    trace_activity=None,
    activity_recorder=None,
    transcript_scan: Callable | None = None,
    scan_workspace: Callable[[Path], list[AgentInstance]] | None = None,
    scan_global: Callable[[], list[AgentInstance]] | None = None,
) -> AgentAttribution:
    event_time = event_time if event_time is not None else time.time()

    if override_agent is not None:
        return AgentAttribution(
            agent=override_agent,
            confidence=1.0,
            detection_method="manual_override",
        )

    if trace_activity is not None:
        trace_attr = trace_activity.resolve(file_path, event_time)
        if trace_attr is not None:
            return trace_attr

    candidates: list[tuple[str, float, str]] = []

    if activity_recorder is not None:
        activity_attr = activity_recorder.resolve(file_path, event_time)
        if activity_attr is not None:
            if not activity_attr.ambiguous:
                return activity_attr
            for name in activity_attr.candidates:
                candidates.append(
                    (
                        name,
                        _weight_for(activity_attr.detection_method, activity_attr.confidence),
                        activity_attr.detection_method,
                    )
                )

    if os.environ.get("TRACE_DISABLE_TRANSCRIPT_ATTRIBUTION") != "1":
        transcript_fn = transcript_scan or find_transcript_attribution
        transcript_attr = transcript_fn(workspace, file_path, event_time)
        if transcript_attr is not None:
            if not transcript_attr.ambiguous:
                return transcript_attr
            for name in transcript_attr.candidates:
                candidates.append(
                    (
                        name,
                        _weight_for(transcript_attr.detection_method, transcript_attr.confidence),
                        transcript_attr.detection_method,
                    )
                )

    scan_fn = scan_workspace or scan_active_agents
    active = scan_fn(workspace)
    if len(active) == 1:
        agent = active[0]
        category_method = {
            "cli": "workspace_cli",
            "gui_app": "gui_app",
            "local_script": "local_script",
        }.get(agent.category, "workspace_cli")
        return AgentAttribution(
            agent=agent.name,
            confidence=_weight_for(category_method, 0.95),
            detection_method=category_method,
        )
    if len(active) > 1:
        for agent in active:
            category_method = {
                "cli": "workspace_cli",
                "gui_app": "gui_app",
                "local_script": "local_script",
            }.get(agent.category, "workspace_cli")
            candidates.append((agent.name, _weight_for(category_method, 0.75), category_method))

    if not active:
        if os.environ.get("TRACE_DISABLE_GLOBAL_AGENT_FALLBACK") == "1":
            return AgentAttribution(agent="human", confidence=0.9)
        global_fn = scan_global or scan_global_active_agents
        global_active = global_fn()
        if len(global_active) == 1:
            return AgentAttribution(
                agent=global_active[0].name,
                confidence=0.65,
                detection_method="global_cli_fallback",
            )
        if len(global_active) > 1:
            names = list(dict.fromkeys(a.name for a in global_active))
            return AgentAttribution(
                agent="unknown",
                confidence=0.35,
                detection_method="global_cli_fallback",
                ambiguous=True,
                candidates=names,
            )
        return AgentAttribution(agent="human", confidence=0.9)

    if not candidates:
        names = list(dict.fromkeys(a.name for a in active))
        return AgentAttribution(
            agent="unknown",
            confidence=0.35,
            ambiguous=True,
            candidates=names,
            detection_method="workspace_ambiguous",
        )

    best_by_agent: dict[str, tuple[float, str]] = {}
    for name, score, method in candidates:
        prev = best_by_agent.get(name)
        if prev is None or score > prev[0]:
            best_by_agent[name] = (score, method)

    ranked = sorted(best_by_agent.items(), key=lambda item: item[1][0], reverse=True)
    top_name, (top_score, top_method) = ranked[0]
    if len(ranked) == 1:
        return AgentAttribution(
            agent=top_name,
            confidence=top_score,
            detection_method=top_method,
        )

    second_score = ranked[1][1][0]
    if top_score - second_score < AMBIGUITY_GAP:
        return AgentAttribution(
            agent="unknown",
            confidence=min(top_score, 0.5),
            detection_method="weighted_ambiguous",
            ambiguous=True,
            candidates=[name for name, _ in ranked[:4]],
        )

    return AgentAttribution(
        agent=top_name,
        confidence=top_score,
        detection_method=top_method,
    )
