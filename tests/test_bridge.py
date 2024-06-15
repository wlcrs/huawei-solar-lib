import huawei_solar.register_names as rn
import pytest


@pytest.mark.asyncio()
async def test_get_model_name(huawei_bridge):
    result = await huawei_bridge.batch_update([rn.MODEL_NAME])
    assert len(result) == 1
    assert result[rn.MODEL_NAME].value == "SUN2000-3KTL-L1"
    assert result[rn.MODEL_NAME].unit is None


@pytest.mark.asyncio()
async def test_get_multiple(huawei_bridge):
    result = await huawei_bridge.batch_update(
        [rn.INPUT_POWER, rn.LINE_VOLTAGE_A_B, rn.LINE_VOLTAGE_B_C, rn.LINE_VOLTAGE_C_A],
    )
    assert len(result) == 4
    assert result[rn.INPUT_POWER].value == 0
    assert result[rn.INPUT_POWER].unit == "W"
    assert result[rn.LINE_VOLTAGE_A_B].value == 0
    assert result[rn.LINE_VOLTAGE_A_B].unit == "V"
    assert result[rn.LINE_VOLTAGE_B_C].value == 0
    assert result[rn.LINE_VOLTAGE_B_C].unit == "V"
    assert result[rn.LINE_VOLTAGE_C_A].value == 0
    assert result[rn.LINE_VOLTAGE_C_A].unit == "V"
