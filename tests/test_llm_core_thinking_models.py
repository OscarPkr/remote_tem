"""Regression coverage for structured-thinking model detection."""

import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import pytest

from src.llm_core import _supports_thinking
from src.model_profiles import supports_user_thinking_toggle


@pytest.mark.parametrize(
    "model",
    [
        "deepseek-v4",
        "deepseek-v4-flash",
        "DeepSeek-V4-Flash",
        "deepseek/deepseek-v4-flash",
    ],
)
def test_deepseek_v4_models_support_thinking(model):
    assert _supports_thinking(model) is True


@pytest.mark.parametrize("model", ["deepseek-v3", "deepseek-chat"])
def test_other_deepseek_models_are_not_promoted_to_thinking(model):
    assert _supports_thinking(model) is False


@pytest.mark.parametrize(
    "model",
    [
        "deepseek-v4",
        "deepseek-v4-flash",
        "DeepSeek-V4-Flash",
        "deepseek/deepseek-v4-flash",
    ],
)
def test_deepseek_v4_models_expose_the_user_thinking_toggle(model):
    assert supports_user_thinking_toggle(model) is True
