"""Huawei SmartAssistant (SA4H) device support."""

from .emma import EMMADevice


class SmartAssistantDevice(EMMADevice):
    """A Huawei SmartAssistant (SA4H) device."""

    @classmethod
    def supports_device(cls, model_name: str) -> bool:
        """Check if this class supports the given device."""
        return model_name.startswith(("SmartAssistant", "SA4H"))
