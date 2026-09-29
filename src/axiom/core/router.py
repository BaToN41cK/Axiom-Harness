"""Model Router + fallback + cost-aware routing (п.16-17).

Маршрут по типу задачи: simple/coding/reasoning/huge-context/vision/fast.
Fallback: primary -> fallback -> fallback2 на 429/timeout/unavailable.
Budget: performance / balanced / economy.

Сверху лежит слой ролей (W4.11): main/subagent/coding/search/summarize. Роль
резолвится сначала по явному правилу из конфига, затем по возможностям
каталога, и только потом — по общей эвристике типа задачи. Ни одно имя
провайдера здесь не зашито: смена провайдера или модели требует только
изменения конфига.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from axiom.core.providers.base import ModelProfile

#: Роли, которые можно маршрутизировать независимо от типа задачи (W4.11).
MODEL_ROLES: tuple[str, ...] = ("main", "subagent", "coding", "search", "summarize")


@dataclass
class RouteTarget:
    provider_id: str
    model: str
    reason: str = ""


@dataclass
class RouterConfig:
    enabled: bool = True
    budget: str = "balanced"
    primary: RouteTarget | None = None
    fallbacks: list[RouteTarget] = field(default_factory=list)
    #: Явные цели по ролям: {"subagent": RouteTarget(...)} (W4.11).
    roles: dict[str, RouteTarget] = field(default_factory=dict)
    #: Правила по возможностям: {"summarize": "long_context"|"auto"} (W4.11).
    role_capabilities: dict[str, str] = field(default_factory=dict)

    def chain(self) -> list[RouteTarget]:
        out: list[RouteTarget] = []
        if self.primary is not None:
            out.append(self.primary)
        out.extend(self.fallbacks)
        return out



def classify_task(text: str) -> str:
    lowered = (text or "").lower()
    if any(k in lowered for k in ("vision", "image", "скрин", "фото", "картинк", "изображен")):
        return "vision"
    if any(k in lowered for k in ("huge", "long context", "весь проект", "вся кодбаза",
                                  "большой контекст", "много файлов")):
        return "huge-context"
    if any(k in lowered for k in ("reason", "архитектур", "спроектир", "сложн",
                                  "докажи", "алгоритм", "рассужден")):
        return "reasoning"
    if any(k in lowered for k in ("code", "код", "баг", "bug", "исправ", "рефактор",
                                  "функци", "класс", "тест", "debug", "ошибк")):
        return "coding"
    if len(lowered.strip()) < 60:
        return "simple"
    return "fast"


def complexity_of(text: str) -> str:
    words = len((text or "").split())
    if words < 15:
        return "low"
    if words < 60:
        return "medium"
    return "high"


#: Возможность, которую роль просит в каталоге, когда правило записано как
#: ``{"capability": "auto"}``. «main» подсказки не имеет: он идёт по общей
#: эвристике типа задачи.
ROLE_CAPABILITIES: dict[str, str] = {
    "subagent": "tool_calling",
    "coding": "coding",
    "search": "fast",
    "summarize": "long_context",
}


def _matches_role(model: ModelProfile, capability: str) -> bool:
    """Одна проверка возможности каталога для роли (W4.11)."""
    if capability == "fast":
        return not model.reasoning
    if capability == "coding":
        return bool(model.coding or model.tool_calling)
    if capability == "tool_calling":
        return bool(model.tool_calling or model.coding)
    return bool(getattr(model, capability, False))


def order_by_budget(models: Iterable[ModelProfile], budget: str) -> list[ModelProfile]:
    """Общий порядок «дорого/дёшево» для маршрутизатора задач и ролей."""
    matches = list(models)
    if budget == "economy":
        matches.sort(key=lambda m: m.id.lower())
    elif budget == "performance":
        matches.sort(key=lambda m: (not m.reasoning, m.id.lower()))
    return matches


class ModelRouter:
    """Чистый роутер: без сети, только эвристики + каталог моделей."""

    def __init__(self, config: RouterConfig | None = None) -> None:
        self.config = config or RouterConfig()

    def role_target(self, role: str | None) -> RouteTarget | None:
        """Явно закреплённая цель роли (W4.11); None — роль не закреплена."""
        if not role:
            return None
        return self.config.roles.get(str(role).strip().lower())

    def role_capability(self, role: str | None) -> str | None:
        """Возможность, которую роли предлагает конфиг (``capability``)."""
        if not role:
            return None
        clean = str(role).strip().lower()
        capability = self.config.role_capabilities.get(clean)
        if not capability:
            return None
        if capability == "auto":
            return ROLE_CAPABILITIES.get(clean)
        return capability

    def route_for_role(self, role: str, text: str = "", catalog=None) -> RouteTarget | None:
        """Модель одной роли. Модель меняется ТОЛЬКО по явному правилу.

        Порядок детерминированный, без единого зашитого имени провайдера:

        1. ``router_roles[<role>] = {"provider_id", "model"}`` — явный пин;
        2. ``{"capability": "<возможность|auto>"}`` — модель из каталога с этой
           возможностью, отобранная тем же бюджетом;
        3. ничего не настроено — общий маршрут (primary + fallback), то есть
           ровно то поведение, которое было до W4.11.
        """
        clean = (role or "").strip().lower()
        explicit = self.config.roles.get(clean)
        if explicit is not None:
            return RouteTarget(explicit.provider_id, explicit.model, f"role={clean} configured")
        if not self.config.enabled:
            return self.config.primary
        capability = self.role_capability(clean)
        models = list(catalog.all()) if catalog is not None else []
        if capability and models:
            matches = order_by_budget(
                (m for m in models if _matches_role(m, capability)), self.config.budget)
            if matches:
                chosen = matches[0]
                return RouteTarget(chosen.provider_id, chosen.id,
                                   f"role={clean} capability={capability}")
        # Каталог здесь намеренно не участвует: маршрут по типу задачи всегда
        # решался над primary/chain, и роль не должна менять это молча.
        return self.route(text, None)

    def route(self, text: str, catalog=None) -> RouteTarget | None:
        if not self.config.enabled:
            return self.config.primary
        task = classify_task(text)
        complexity = complexity_of(text)
        # Явный primary всегда побеждает, если routing включён «мягко».
        if self.config.primary is not None and task in ("simple", "fast") \
                and self.config.budget != "economy":
            return self.config.primary
        models = list(catalog.all()) if catalog is not None else []
        if not models:
            return self.config.primary

        def _pick(pred: Callable[[ModelProfile], bool], fallback_idx: int = 0) -> RouteTarget | None:
            matches = order_by_budget(
                (m for m in models if pred(m)), self.config.budget)
            if not matches:
                return None
            chosen = matches[fallback_idx % len(matches)]
            return RouteTarget(chosen.provider_id, chosen.id,
                               reason=f"task={task} complexity={complexity}")

        if task == "vision":
            hit = _pick(lambda m: m.vision)
            if hit:
                return hit
        if task == "huge-context":
            hit = _pick(lambda m: m.long_context)
            if hit:
                return hit
        if task == "reasoning" or (task == "coding" and complexity == "high"):
            hit = _pick(lambda m: m.reasoning)
            if hit:
                return hit
        if task == "coding":
            hit = _pick(lambda m: m.coding or m.tool_calling)
            if hit:
                return hit
        if task == "simple":
            hit = _pick(lambda m: not m.reasoning)
            if hit:
                return hit
        first = models[0]
        return RouteTarget(first.provider_id, first.id, reason=f"task={task} fallback=first")

    def should_fallback(self, error: Exception | str) -> bool:
        if isinstance(error, str):
            text = error.lower()
        else:
            # The real ``kind`` matters: ``ollama_unavailable`` / ``provider_unavailable``
            # never spell "unavailable" in the human-readable message.
            text = f"{type(error).__name__}: {error} {getattr(error, 'kind', '')}".lower()
        markers = ("429", "rate limit", "timeout", "timed out", "unavailable",
                   "connection", "context", "overloaded", "503", "502", "500")
        return any(m in text for m in markers)

    def next_fallback(self, failed: RouteTarget) -> RouteTarget | None:
        chain = self.config.chain()
        for idx, target in enumerate(chain):
            if target.provider_id == failed.provider_id and target.model == failed.model:
                if idx + 1 < len(chain):
                    return chain[idx + 1]
                return None
        return self.config.fallbacks[0] if self.config.fallbacks else None
