import logging
from typing import Dict, Any, List, Optional

from ai_services.ai_platform.llm.mixins import AIServiceMixin
from core.exceptions import BizException
from core.error_codes import ErrorCode

from ai_services.schemas.creative.editing_director import (
    EditingDirectorPayload, EditingDirectorResponse, EditingDecision, EditingActionType
)
from ai_services.schemas.creative.asset_selector import SelectedCandidate

logger = logging.getLogger(__name__)

class EditingDirectorService(AIServiceMixin):
    """
    剪辑决策服务 (Creative)
    职责: 基于素材候选和目标时长，计算具体的剪辑指令 (裁剪/变速/生成)。
    """
    SERVICE_NAME = "editing_director"

    def __init__(self, logger: logging.Logger, **kwargs):
        # 兼容 RefineryBaseHandler 的初始化参数 (gemini_processor, cost_calculator)
        # 虽然纯逻辑服务不需要它们，但为了保持接口一致性，我们接收并忽略
        self.logger = logger

    def execute(self, payload: Dict[str, Any], config: Dict[str, Any] = None) -> Dict[str, Any]:
        self.logger.info("🚀 Starting Editing Director...")

        # 1. 输入校验
        try:
            task_input = EditingDirectorPayload(**payload)
        except Exception as e:
            raise BizException(ErrorCode.PAYLOAD_VALIDATION_ERROR, f"Schema Error: {e}")

        # 2. 准备参数
        params = task_input.service_params
        
        # 建立索引映射
        selections_map = {s.segment_index: s.candidates for s in task_input.selections}
        
        decisions = []
        stats = {
            "total_segments": len(task_input.dubbing_script),
            "action_use_slice": 0,
            "action_generate": 0,
            "action_empty": 0
        }

        # 3. 逐段决策
        for seg in task_input.dubbing_script:
            target_duration = seg.duration
            candidates = selections_map.get(seg.index, [])
            
            decision = self._make_decision(seg.index, seg.text, target_duration, candidates, params)
            decisions.append(decision)
            
            # 统计
            if decision.action == EditingActionType.USE_SLICE:
                stats["action_use_slice"] += 1
            elif decision.action == EditingActionType.GENERATE:
                stats["action_generate"] += 1
            else:
                stats["action_empty"] += 1

        return EditingDirectorResponse(
            decisions=decisions,
            stats=stats
        ).model_dump()

    def _make_decision(self, 
                       index: int, 
                       text: str, 
                       target: float, 
                       candidates: List[SelectedCandidate],
                       params: Any) -> EditingDecision:
        
        # 策略 0: 无候选 -> 生成
        if not candidates:
            return EditingDecision(
                segment_index=index,
                action=EditingActionType.GENERATE,
                target_duration=target,
                generation_prompt=f"Cinematic shot: {text}", # 简单透传，后续可优化 Prompt
                reason="No candidates found."
            )

        # 策略 1: 优选最佳候选 (Score > Duration)
        # 排序逻辑: Score 降序 -> Duration 降序
        best_cand = sorted(candidates, key=lambda x: (x.score, x.duration), reverse=True)[0]
        
        src_dur = best_cand.duration
        
        # 策略 2: 极短素材 -> 放弃并生成
        # 如果素材时长连目标的 30% 都不到，强行拉伸效果太差
        if src_dur < target * params.generation_threshold:
             return EditingDecision(
                segment_index=index,
                action=EditingActionType.GENERATE,
                target_duration=target,
                generation_prompt=f"Cinematic shot: {text}",
                reason=f"Best candidate too short ({src_dur}s vs {target}s)."
            )

        # 策略 3: 时长对齐
        diff = src_dur - target
        
        if diff >= 0:
            # Case A: 素材够长 -> 裁剪 (Keep Start)
            # 也可以考虑 Keep Middle，但 Keep Start 通常更符合“看到即所得”
            return EditingDecision(
                segment_index=index,
                action=EditingActionType.USE_SLICE,
                slice_id=best_cand.slice_id,
                source_range=(0.0, target),
                speed_rate=1.0,
                target_duration=target,
                reason=f"Trimmed from {src_dur}s to {target}s."
            )
        else:
            # Case B: 素材不够长 -> 变速 (Slow Motion)
            # 计算需要的倍速: speed = src / target (e.g. 5s / 10s = 0.5x)
            required_speed = src_dur / target
            
            # 限制最小倍速 (防止变成 PPT)
            final_speed = max(required_speed, params.min_speed_rate)
            
            # 如果变速后还不够，说明触底了，剩下的时间其实是 Freeze Frame 效果
            # 但在指令层面，我们只需告诉下游：用全段，速度设为 final_speed
            # 下游渲染引擎如果发现时长还不够，会自动定格最后一帧
            
            return EditingDecision(
                segment_index=index,
                action=EditingActionType.USE_SLICE,
                slice_id=best_cand.slice_id,
                source_range=(0.0, src_dur),
                speed_rate=round(final_speed, 2),
                target_duration=target,
                reason=f"Speed ramped to {final_speed:.2f}x."
            )